"""
Prospective Intention Store (PIS) — structured external memory for PM-Bench.

Unlike Mem0 / A-Mem (semantic episode recall), this store keeps *condition
intentions* with an explicit lifecycle:

  write   → action, due {day, time?}, event_cue, watch names, status
  scene   → one judge: cancel / reschedule / override, plus this-step
            event_due / channel_due labels (labels do not change status)
  encode  → Done Judge marks fulfilled pending by list number n; extract plants new ones

No scenario ground-truth is read. Everything is derived from model-visible
text (day plan, vignette, action menu, State [channel] replies).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .common import (
    INTENTION_DONE_JUDGE_PROMPT,
    INTENTION_EXTRACT_JUDGE_PROMPT,
    INTENTION_SCENE_JUDGE_PROMPT,
    current_step_start_index,
    resolve_action_labels,
    scrub_task_handles,
    truncate,
)


def _fail(where: str, detail: str) -> None:
    """Hard-fail so a bad judge step is visible instead of silently recovering."""
    raise RuntimeError(f"[intention:{where}] {detail}")


CHANNEL_HINTS: dict[str, tuple[str, ...]] = {
    "appointment_portal": ("appointment portal", "portal posts", "portal", "better slot"),
    "library_hold": ("library hold", "library notice", "hold is ready", "reserve reading"),
    "email": ("email", "confirmation email", "vendor reply"),
    "calendar": ("calendar", "calendar update", "room shift", "new block"),
    "course_portal": ("course portal", "grade", "grades released"),
    "bank_balance": ("balance", "bank", "below $"),
    "shipment_status": ("shipment", "out for delivery", "delivery"),
    "laundry_status": ("laundry", "laundry room"),
    "reservation_waitlist": ("waitlist", "reservation"),
    "price_tracker": ("price tracker", "price drop"),
    "clock": ("clock",),
}

_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_PLAN_BULLET_RE = re.compile(r"^\s*[-•]\s+(.+?)\s*$")
_CROSS_DAY_RE = re.compile(
    r"\bOn\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b[,:]?\s*(.+?)(?:\.(?:\s|$)|$)",
    re.I,
)
_WHEN_RE = re.compile(r"\bwhen\b\s+(.+?)(?:\.(?:\s|$)|$)", re.I)
_AT_TIME_RE = re.compile(r"\bat\s+(\d{1,2}:\d{2})\b", re.I)
_WATCH_ALLOWED = tuple(name for name in CHANNEL_HINTS if name != "clock")
_EMPTY_DUE_DAY = frozenset({"", "null", "none", "-", "unknown", "today", "todays"})
_STATE_REPLY_RE = re.compile(
    r"^State\s*\[([^\]]+)\]\s*:\s*(.+)$",
    re.I | re.M,
)
_CUE_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Dropped before comparing stored event_cue strings (not vignette scan).
_CUE_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "appear",
        "appears",
        "arrive",
        "arrives",
        "at",
        "before",
        "comes",
        "come",
        "for",
        "free",
        "from",
        "in",
        "inside",
        "is",
        "it",
        "its",
        "land",
        "lands",
        "later",
        "notice",
        "now",
        "of",
        "on",
        "once",
        "open",
        "reach",
        "reaches",
        "show",
        "shows",
        "the",
        "this",
        "to",
        "tucked",
        "unlocked",
        "up",
        "waiting",
        "when",
        "with",
        "you",
        "your",
    }
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.I | re.DOTALL)
_THINK_UNCLOSED_RE = re.compile(r"<think>.*", re.I | re.DOTALL)


@dataclass
class DueSlot:
    """When the commitment should be carried out.

    `day` is optional: only a named calendar weekday, never the planting day
    just because the reminder appeared then. `time` is optional HH:MM.
    """

    day: str = ""
    time: str = ""


@dataclass
class Intention:
    intent_id: str
    action: str
    status: str = "pending"  # pending | done | canceled
    due: DueSlot = field(default_factory=DueSlot)
    event_cue: str = ""
    watch: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IntentionStoreBackend:
    """Structured prospective-memory backend."""

    name = "intention"

    def __init__(
        self,
        *,
        store_path: str | None = None,
        max_inject_chars: int = 6000,
        time_tolerance_minutes: int = 0,
        llm_client: Any | None = None,
        llm_model: str | None = None,
        use_llm_update: bool = False,
        use_llm_extract: bool = False,
        use_llm_done: bool = False,
        use_llm_match: bool = False,
    ):
        self.store_path = Path(store_path) if store_path else None
        self.max_inject_chars = max_inject_chars
        self.time_tolerance_minutes = time_tolerance_minutes
        self.llm_client = llm_client
        self.llm_model = llm_model or ""
        self.use_llm_update = bool(use_llm_update and llm_client and llm_model)
        self.use_llm_extract = bool(use_llm_extract and llm_client and llm_model)
        self.use_llm_done = bool(use_llm_done and llm_client and llm_model)
        self.use_llm_match = bool(use_llm_match and llm_client and llm_model)
        self.intentions: dict[str, Intention] = {}
        self._seeded_days: set[str] = set()
        self._daily_day: str = ""
        self._last_update_obs_key: str = ""
        self._last_update_hits: int = 0
        self._patched_ids: list[str] = []
        self._judge_index_to_id: dict[int, str] = {}
        self._update_skipped: list[dict[str, Any]] = []
        self._last_extract_obs_key: str = ""
        self._last_extract_added: int = 0
        self._last_extract_items: list[dict[str, Any]] = []
        self.last_encode_info: dict[str, Any] = {}
        self.last_recall_info: dict[str, Any] = {}
        self.last_update_info: dict[str, Any] = {}
        self.last_extract_info: dict[str, Any] = {}
        self.last_done_info: dict[str, Any] = {}
        self.last_match_info: dict[str, Any] = {}
        self._last_scene_key: str = ""
        self._last_match_labels: dict[str, Any] = {}
        self._step_log_path = (
            self.store_path.with_name(self.store_path.stem + ".steps.jsonl")
            if self.store_path
            else None
        )
        self._filter_log_path = (
            self.store_path.with_name(self.store_path.stem + ".filters.md")
            if self.store_path
            else None
        )
        if self.store_path and self.store_path.exists():
            self._load()

    # ------------------------------------------------------------------ API
    def recall(self, query: str, *, top_k: int | None = None, context: dict | None = None) -> str:
        ctx = context or {}
        day = str(ctx.get("day") or "")
        time_str = str(ctx.get("time") or "")
        observation = str(ctx.get("observation") or query or "")
        messages = ctx.get("messages") or []

        self._maybe_seed_daily(day=day)
        self._maybe_seed_day_plan(messages, day=day, time_str=time_str)
        update_hits = self.apply_observation_updates(
            observation, day=day, time_str=time_str, messages=messages
        )
        extract_added = self._extract_observation(
            observation, day=day, time_str=time_str
        )

        pending = [i for i in self.intentions.values() if i.status == "pending"]
        today_pending = [i for i in pending if self._is_active_on_day(i, day)]
        match = self._match_event_channel(
            today_pending,
            observation=observation,
            day=day,
            time_str=time_str,
            messages=messages,
        )
        choose_pool = match["kept"]
        event_hits = match["event_due"]
        channel_hits = match["channel_due"]
        time_hits = self._filter_time_due(choose_pool, time_str)
        channel_needed = self._watch_needed(choose_pool, messages)

        pending_time = [i for i in choose_pool if i.due.time]
        # No trusted clock ⇒ cannot score TIME-DUE; ask session to force check_time.
        force_check_time = (not time_str) and bool(pending_time)
        step = str(ctx.get("step") or "")
        filter_trace = self._build_filter_trace(
            pending=pending,
            today_pending=today_pending,
            time_hits=time_hits,
            channel_needed=channel_needed,
            day=day,
            step=step,
            time_str=time_str,
            messages=messages,
            extracted=(
                (self.last_extract_info or {}).get("extracted") or []
                if extract_added
                else []
            ),
            extract_added=extract_added,
            match=match,
        )
        filter_trace_text = self._format_filter_trace(filter_trace)

        text = self._format_injection(
            time_hits=time_hits,
            event_hits=event_hits,
            channel_hits=channel_hits,
            channel_needed=channel_needed,
            today_pending=choose_pool,
            day=day,
            time_str=time_str,
            force_check_time=force_check_time,
            pending_time_n=len(pending_time),
            match_filtered=match.get("mode") == "llm",
        )
        self.last_recall_info = {
            "pending": len(pending),
            "pending_time": len(pending_time),
            "clock_known": bool(time_str),
            "force_check_time": force_check_time,
            "time_hits": len(time_hits),
            "event_hits": len(event_hits),
            "channel_hits": len(channel_hits),
            "channel_needed": channel_needed,
            "today_pending": len(today_pending),
            "choose_pool": len(choose_pool),
            "aligned": len(choose_pool),
            "updates": update_hits,
            "extract_added": extract_added,
            "filter_dropped_future": len(filter_trace.get("drop_future_due_day") or []),
            "filter_time_not_due": len(filter_trace.get("time_not_due") or []),
            "filter_trace_text": filter_trace_text,
            **{f"update_{k}": v for k, v in (self.last_update_info or {}).items()},
            **{
                f"extract_{k}": v
                for k, v in (self.last_extract_info or {}).items()
                if k != "extracted"
            },
            **{f"match_{k}": v for k, v in (self.last_match_info or {}).items()},
        }
        injected = truncate(text, self.max_inject_chars) if text else ""
        self._save()
        self._append_filter_log(filter_trace_text)
        self._save_step(
            event="recall",
            day=day,
            step=step,
            time_str=time_str,
            extra={
                "injected": injected,
                "recall": dict(self.last_recall_info),
                "filter_trace": filter_trace,
            },
        )
        return injected

    def encode(self, turn: dict[str, Any]) -> None:
        day = str(turn.get("day") or "")
        time_str = str(turn.get("time") or "")
        observation = str(turn.get("observation") or "")
        self.apply_observation_updates(observation, day=day, time_str=time_str)

        labels = resolve_action_labels(turn)
        done_n = self._mark_done_by_choice(labels, day=day)

        # Keep any newly stated deferred intentions from the scene (cross-day notes).
        added = self._extract_observation(observation, day=day, time_str=time_str)
        self.last_encode_info = {
            "mode": "intention",
            "marked_done": done_n,
            "added": added,
            "store_size": len(self.intentions),
            "pending": sum(1 for i in self.intentions.values() if i.status == "pending"),
            **{f"update_{k}": v for k, v in (self.last_update_info or {}).items()},
            **{f"extract_{k}": v for k, v in (self.last_extract_info or {}).items()},
            **{f"done_{k}": v for k, v in (self.last_done_info or {}).items()},
        }
        self._save()
        self._save_step(
            event="encode",
            day=day,
            step=str(turn.get("step") or ""),
            time_str=time_str,
            extra={"encode": dict(self.last_encode_info)},
        )

    def apply_observation_updates(
        self,
        observation: str,
        *,
        day: str = "",
        time_str: str = "",
        messages: list | None = None,
    ) -> int:
        """Apply scene-judge revisions. Also caches this-step due labels.

        LLM only. Empty scene / no pending → no-op. Anything else that fails raises.
        """
        text = (observation or "").strip()
        if not text:
            self._patched_ids = []
            self.last_update_info = {"mode": "empty", "patched_ids": []}
            return 0

        pending = [i for i in self.intentions.values() if i.status == "pending"]
        if not pending:
            obs_key = f"{day}|{time_str}|{text}"
            self._last_update_obs_key = obs_key
            self._last_update_hits = 0
            self.last_update_info = {"mode": "no_pending", "patched_ids": []}
            return 0

        if not self.use_llm_update:
            _fail(
                "scene",
                "改任务的模型必须开着，没有关键词后手。"
                "不要加 --no-intention-llm-update。",
            )

        return self._ensure_scene_judge(
            text,
            pending,
            day=day,
            time_str=time_str,
            messages=messages or [],
            apply_updates=True,
        )

    def _ensure_scene_judge(
        self,
        observation: str,
        pending: list[Intention],
        *,
        day: str,
        time_str: str,
        messages: list,
        apply_updates: bool,
    ) -> int:
        """One LLM call: store patches + this-step event/channel labels."""
        text = (observation or "").strip()
        obs_key = f"{day}|{time_str}|{text}"
        states = self._state_replies_this_step(messages)
        state_fp = "|".join(f"{k}={states[k]}" for k in sorted(states))
        scene_key = f"{obs_key}|{state_fp}"
        if scene_key == self._last_scene_key and self._last_match_labels:
            return self._last_update_hits
        if apply_updates and obs_key == self._last_update_obs_key and not states:
            # encode / same clock, no new State: do not re-ask.
            return self._last_update_hits

        data = self._call_scene_judge(
            text,
            pending,
            day=day,
            time_str=time_str,
            states=states,
        )
        labels = {
            "event_due_ids": list(data.get("event_due_ids") or []),
            "event_wait_ids": list(data.get("event_wait_ids") or []),
            "channel_due_ids": list(data.get("channel_due_ids") or []),
            "channel_wait_ids": list(data.get("channel_wait_ids") or []),
        }
        patches = list(data.get("updates") or [])
        event_due_ids = self._expand_event_due_ids(
            pending, set(labels["event_due_ids"])
        )
        labels["event_due_ids"] = list(event_due_ids)

        if apply_updates and obs_key != self._last_update_obs_key:
            self._patched_ids = []
            hits = self._apply_update_patches(
                patches,
                day=day,
                time_str=time_str,
                event_due_ids=event_due_ids,
            )
            self._last_update_obs_key = obs_key
            self._last_update_hits = hits
            self.last_update_info = {
                "mode": "llm",
                "hits": hits,
                "patches": len(patches),
                "candidates": len(self._judge_index_to_id),
                "skipped": list(self._update_skipped),
                "patched_ids": list(self._patched_ids),
            }
            if hits:
                self._save()
        elif apply_updates:
            hits = self._last_update_hits
        else:
            hits = self._last_update_hits

        self._last_scene_key = scene_key
        self._last_match_labels = labels
        return hits

    def _call_scene_judge(
        self,
        observation: str,
        pending: list[Intention],
        *,
        day: str,
        time_str: str,
        states: dict[str, str],
    ) -> dict[str, Any]:
        """Ask the LLM for revisions and this-step due labels together."""
        ordered = self._pending_for_judge(pending, day=day)
        self._judge_index_to_id = {}
        lines = []
        for n, i in enumerate(ordered, start=1):
            self._judge_index_to_id[n] = i.intent_id
            lines.append(f"{n}. " + " | ".join(self._intent_field_bits(i)))
        state_block = (
            "\n".join(f"State [{name}]: {text}" for name, text in sorted(states.items()))
            if states
            else "(none yet)"
        )
        prompt = (
            f"{INTENTION_SCENE_JUDGE_PROMPT}\n\n"
            f"Day: {day}  Observed clock (may be empty): {time_str or 'unknown'}\n\n"
            f"CURRENT SCENE:\n{observation[:2500]}\n\n"
            f"THIS STEP STATE REPLIES:\n{state_block}\n\n"
            "PENDING INTENTIONS (point to a row by n only):\n"
            + ("\n".join(lines) if lines else "(none)")
        )
        n_max = max(len(ordered), 1)
        data = self._complete_judge_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a scene judge. Output valid JSON only. "
                        "n is the PENDING list number. "
                        "Only mark rows that changed; cue firing is event_due, not cancel. "
                        "If a cue is in the scene, event_due lists every matching n, not one."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
            schema_name="intention_scene",
            schema=self._scene_judge_schema(n_max),
            where="scene",
        )
        updates = data.get("updates")
        if updates is None:
            updates = []
        if not isinstance(updates, list):
            _fail("scene", f"updates 不是列表: {type(updates).__name__}")
        bad = [u for u in updates if not isinstance(u, dict)]
        if bad:
            _fail("scene", f"updates 里有不是对象的项: {bad[:3]!r}")
        index = self._judge_index_to_id
        return {
            "updates": updates,
            "event_due_ids": self._ns_to_ids(data.get("event_due"), index),
            "event_wait_ids": self._ns_to_ids(data.get("event_wait"), index),
            "channel_due_ids": self._ns_to_ids(data.get("channel_due"), index),
            "channel_wait_ids": self._ns_to_ids(data.get("channel_wait"), index),
        }

    @staticmethod
    def _scene_judge_schema(n_max: int) -> dict[str, Any]:
        """Lock n to 1..n_max so the model cannot emit an out-of-list index."""
        n_item = {
            "type": "integer",
            "minimum": 1,
            "maximum": n_max,
        }
        return {
            "type": "object",
            "properties": {
                "updates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "n": n_item,
                            "action": {
                                "type": "string",
                                "enum": ["cancel", "reschedule", "override"],
                            },
                            "new_time": {"type": ["string", "null"]},
                            "new_day": {"type": ["string", "null"]},
                            "new_trigger": {"type": ["string", "null"]},
                            "new_action": {"type": ["string", "null"]},
                            "rationale": {"type": "string"},
                        },
                        "required": [
                            "n",
                            "action",
                            "new_time",
                            "new_day",
                            "new_trigger",
                            "new_action",
                            "rationale",
                        ],
                        "additionalProperties": False,
                    },
                },
                "event_due": {"type": "array", "items": n_item},
                "event_wait": {"type": "array", "items": n_item},
                "channel_due": {"type": "array", "items": n_item},
                "channel_wait": {"type": "array", "items": n_item},
            },
            "required": [
                "updates",
                "event_due",
                "event_wait",
                "channel_due",
                "channel_wait",
            ],
            "additionalProperties": False,
        }

    def _complete_judge_json(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int,
        schema_name: str,
        schema: dict[str, Any],
        where: str,
    ) -> dict[str, Any]:
        """Try json_schema, then json_object, then raw. Parse after each 200."""
        kwargs: dict[str, Any] = {
            "model": self.llm_model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        formats: list[dict[str, Any] | None] = [
            {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
            {"type": "json_object"},
            None,
        ]
        errors: list[str] = []
        for fmt in formats:
            try:
                call = dict(kwargs)
                if fmt is not None:
                    call["response_format"] = fmt
                resp = self.llm_client.chat.completions.create(**call)
            except Exception as exc:
                errors.append(f"http:{type(exc).__name__}: {exc}")
                continue
            try:
                content = (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                errors.append(f"read:{type(exc).__name__}: {exc}")
                continue
            data = self._try_parse_judge_json(content)
            if data is not None:
                return data
            preview = content.replace("\n", " ")[:80]
            errors.append(f"parse:{preview!r}")
        _fail(where, "模型没给出能解析的 JSON: " + " | ".join(errors)[:500])
        raise AssertionError("unreachable")

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_str = False
        esc = False
        for i, ch in enumerate(text[start:], start=start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    @staticmethod
    def _try_parse_judge_json(content: str) -> dict[str, Any] | None:
        raw = (content or "").strip()
        if not raw:
            return None
        stripped = _THINK_RE.sub("", raw).strip()
        stripped = _THINK_UNCLOSED_RE.sub("", stripped).strip()
        blobs = [raw, stripped]
        candidates: list[str] = []
        for blob in blobs:
            if not blob:
                continue
            text = blob
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text).strip()
            if text and text not in candidates:
                candidates.append(text)
            extracted = IntentionStoreBackend._extract_json_object(text)
            if extracted and extracted not in candidates:
                candidates.append(extracted)
        for cand in candidates:
            try:
                data = json.loads(cand)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
        return None

    @staticmethod
    def _parse_judge_json(content: str, *, where: str) -> dict[str, Any]:
        data = IntentionStoreBackend._try_parse_judge_json(content)
        if data is None:
            preview = (content or "").replace("\n", " ")[:240]
            _fail(where, f"返回的不是 JSON; 原文前 240 字: {preview!r}")
        return data

    def _pending_for_judge(self, pending: list[Intention], *, day: str) -> list[Intention]:
        """All pending, today first. No word-overlap ranking."""
        today = (day or "").strip().lower()

        def sort_key(i: Intention) -> tuple:
            due = (i.due.day or "").strip().lower()
            today_first = 0 if (not due or due == today) else 1
            di = self._weekday_index(i.due.day)
            return (today_first, di if di is not None else 99, (i.action or "").lower())

        return sorted(pending, key=sort_key)

    def _resolve_patch_intent(self, patch: dict[str, Any]) -> Intention | None:
        """Map a judge patch to a pending row by list number n only."""
        raw_n = patch.get("n", patch.get("index", patch.get("item")))
        if raw_n is None:
            raw_id = str(patch.get("intent_id") or "").strip()
            if raw_id.isdigit():
                raw_n = raw_id
        try:
            if raw_n is None or str(raw_n).strip() == "":
                return None
            idx = int(raw_n)
        except (TypeError, ValueError):
            return None
        iid = self._judge_index_to_id.get(idx)
        if not iid:
            return None
        cand = self.intentions.get(iid)
        if cand is None or cand.status != "pending":
            return None
        return cand

    def _apply_update_patches(
        self,
        patches: list[dict[str, Any]],
        *,
        day: str,
        time_str: str,
        event_due_ids: set[str] | None = None,
    ) -> int:
        del time_str
        hits = 0
        self._update_skipped = []
        due_now = event_due_ids or set()
        for patch in patches:
            verb = str(patch.get("action") or "").strip().lower()
            if verb in ("", "none", "null"):
                continue
            if verb not in ("cancel", "reschedule", "override"):
                continue
            intent = self._resolve_patch_intent(patch)
            if intent is None:
                _fail(
                    "scene",
                    "点名的序号对不上待做列表，没有用词去猜。"
                    f" patch={patch!r} 有效序号={sorted(self._judge_index_to_id)}",
                )

            if verb == "cancel" and intent.intent_id in due_now:
                self._update_skipped.append(
                    {
                        "intent_id": intent.intent_id,
                        "reason": "cue_firing_not_cancel",
                    }
                )
                continue

            if verb == "cancel":
                intent.status = "canceled"
            elif verb == "reschedule":
                new_time = str(patch.get("new_time") or "").strip()
                if not new_time:
                    new_time = self._first_time(
                        str(patch.get("new_summary") or patch.get("new_action") or "")
                    )
                new_action = str(
                    patch.get("new_action") or patch.get("new_summary") or ""
                ).strip()
                new_day = str(patch.get("new_day") or "").strip() or day
                self._rewrite_due_world(intent, day=new_day, new_time=new_time)
                if new_action:
                    intent.action = self._action_phrase(new_action)
            elif verb == "override":
                new_trigger = str(patch.get("new_trigger") or "").strip()
                if new_trigger:
                    intent.event_cue = new_trigger
                    if not intent.due.time:
                        intent.due.time = ""
                new_action = str(
                    patch.get("new_action") or patch.get("new_summary") or ""
                ).strip()
                if new_action:
                    intent.action = self._action_phrase(new_action)
                    ch = self._infer_channels(new_action)
                    if ch:
                        intent.watch = ch
                elif new_trigger:
                    ch = self._infer_channels(new_trigger)
                    if ch:
                        intent.watch = ch
            self._patched_ids.append(intent.intent_id)
            hits += 1
        return hits

    def _mark_done_by_choice(self, labels: list[str], *, day: str) -> int:
        """Ask the done judge which pending rows the chosen menu actions fulfilled."""
        if not labels:
            self.last_done_info = {"mode": "no_labels"}
            return 0
        pending = [i for i in self.intentions.values() if i.status == "pending"]
        if not pending:
            self.last_done_info = {"mode": "no_pending"}
            return 0
        if not self.use_llm_done:
            _fail(
                "done",
                "勾掉已做必须开着模型，没有词袋后手。",
            )
        ns = self._call_done_judge(labels, pending, day=day)
        hits = self._apply_done_ns(ns)
        self.last_done_info = {
            "mode": "llm",
            "labels": list(labels),
            "ns": list(ns),
            "hits": hits,
            "candidates": len(self._judge_index_to_id),
        }
        return hits

    def _call_done_judge(
        self, labels: list[str], pending: list[Intention], *, day: str
    ) -> list[int]:
        ordered = self._pending_for_judge(pending, day=day)
        self._judge_index_to_id = {}
        lines = []
        for n, i in enumerate(ordered, start=1):
            self._judge_index_to_id[n] = i.intent_id
            lines.append(f"{n}. " + " | ".join(self._intent_field_bits(i)))
        chosen = "\n".join(f"- {lab}" for lab in labels)
        prompt = (
            f"{INTENTION_DONE_JUDGE_PROMPT}\n\n"
            f"Day: {day}\n\n"
            f"CHOSEN MENU ACTIONS this step:\n{chosen}\n\n"
            "PENDING INTENTIONS (point to a row by n only):\n"
            + ("\n".join(lines) if lines else "(none)")
        )
        n_max = max(len(ordered), 1)
        data = self._complete_judge_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful intention-done judge. "
                        "Output valid JSON only. Identify rows by n, never by id."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            schema_name="intention_done",
            schema=self._done_judge_schema(n_max),
            where="done",
        )
        raw = data.get("done")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            _fail("done", f"done 不是列表: {type(raw).__name__}")
        ns: list[int] = []
        for item in raw:
            try:
                n = int(item)
            except (TypeError, ValueError):
                _fail("done", f"done 里有不是整数的项: {item!r}")
            if n not in ns:
                ns.append(n)
        return ns

    @staticmethod
    def _done_judge_schema(n_max: int) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "done": {
                    "type": "array",
                    "items": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": n_max,
                    },
                }
            },
            "required": ["done"],
            "additionalProperties": False,
        }

    def _apply_done_ns(self, ns: list[int]) -> int:
        hits = 0
        seen: set[str] = set()
        for n in ns:
            intent = self._resolve_patch_intent({"n": n})
            if intent is None:
                _fail(
                    "done",
                    "点名的序号对不上待做列表，没有用词去猜。"
                    f" n={n!r} 有效序号={sorted(self._judge_index_to_id)}",
                )
            if intent.intent_id in seen:
                continue
            seen.add(intent.intent_id)
            intent.status = "done"
            hits += 1
        return hits

    # ------------------------------------------------------------- seeding
    def _maybe_seed_daily(self, *, day: str = "") -> None:
        """Seed / re-open recurring meds once when the calendar day changes."""
        if day and day == self._daily_day:
            return
        specs = [
            ("Take antibiotic", "", "breakfast"),
            ("Take antibiotic", "", "dinner"),
            ("Take asthma medication", "11:00", ""),
            ("Take asthma medication", "21:00", ""),
        ]
        for action, due_time, event in specs:
            existing = self._find_daily(action, due_time=due_time, event_cue=event)
            slot_day = day if due_time else ""
            if existing is not None:
                existing.status = "pending"
                existing.due.day = slot_day
                existing.due.time = due_time
                existing.event_cue = event or existing.event_cue
                existing.action = action
                continue
            self._insert(
                Intention(
                    intent_id=self._new_id(),
                    action=action,
                    status="pending",
                    due=DueSlot(day=slot_day, time=due_time),
                    event_cue=event,
                )
            )
        self._daily_day = day

    def _find_daily(
        self, action: str, *, due_time: str, event_cue: str
    ) -> Intention | None:
        """Re-open the standing daily slot. Exact action + time/cue, not extract-merge."""
        want = (action or "").strip().lower()
        for intent in self.intentions.values():
            if (intent.action or "").strip().lower() != want:
                continue
            if due_time:
                if intent.due.time == due_time:
                    return intent
            elif (intent.event_cue or "").lower() == event_cue.lower():
                return intent
        return None

    def _maybe_seed_day_plan(
        self, messages: list[dict], *, day: str, time_str: str
    ) -> None:
        if not day or day in self._seeded_days:
            return
        plan_text = ""
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if content.startswith(f"=== {day}") or (
                content.startswith("=== ") and day in content.splitlines()[0]
            ):
                plan_text = content
                break
        if not plan_text:
            return
        self._seeded_days.add(day)
        self._extract_from_text(plan_text, day=day)
        self._save()

    def _extract_observation(self, text: str, *, day: str, time_str: str = "") -> int:
        """Plant new intentions from a vignette. LLM only; no regex fallback.

        Cached on (day, scene) so check_time's second recall does not re-call.
        Day-plan bullets still go through `_extract_from_text` only.
        """
        del time_str
        scene = (text or "").strip()
        if not scene:
            self.last_extract_info = {"mode": "empty", "extracted": []}
            return 0
        obs_key = f"{day}|{scene}"
        if obs_key == self._last_extract_obs_key:
            return 0

        if not self.use_llm_extract:
            _fail(
                "extract",
                "拆任务的模型必须开着，没有正则后手。"
                "不要加 --no-intention-llm-extract。",
            )

        items = self._llm_extract_intentions(scene, day=day)
        added = 0
        for intent in items:
            self._insert(intent)
            added += 1
        self.last_extract_info = {
            "mode": "llm",
            "proposed": len(items),
            "added": added,
            "extracted": list(self._last_extract_items),
        }
        self._last_extract_obs_key = obs_key
        self._last_extract_added = added
        if added:
            self._save()
        return added

    def _llm_extract_intentions(self, observation: str, *, day: str) -> list[Intention]:
        watch_list = ", ".join(_WATCH_ALLOWED)
        prompt = (
            f"{INTENTION_EXTRACT_JUDGE_PROMPT}\n\n"
            f"TODAY: {day or 'unknown'}\n"
            f"Allowed watch names: {watch_list}\n\n"
            f"CURRENT SCENE:\n{observation[:2500]}"
        )
        data = self._call_extract_json(
            system=(
                "You are a careful intention-extract judge. "
                "Output valid JSON only."
            ),
            user=prompt,
            max_tokens=1500,
        )
        raw = data.get("intentions")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            _fail("extract", f"intentions 不是列表: {type(raw).__name__}")
        out: list[Intention] = []
        traces: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                _fail("extract", f"intentions 里有不是对象的项: {item!r}")
            intent = self._intention_from_extract_item(item, today=day)
            traces.append(
                {
                    "raw": {
                        "action": item.get("action"),
                        "due_day": item.get("due_day"),
                        "due_time": item.get("due_time"),
                        "event_cue": item.get("event_cue") or item.get("event"),
                        "watch": item.get("watch"),
                    },
                    "stored": self._brief_intent(intent),
                }
            )
            out.append(intent)
        self._last_extract_items = traces
        return out

    def _call_extract_json(
        self, *, system: str, user: str, max_tokens: int
    ) -> dict[str, Any]:
        return self._complete_judge_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            schema_name="intention_extract",
            schema={
                "type": "object",
                "properties": {
                    "intentions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "due_day": {"type": ["string", "null"]},
                                "due_time": {"type": ["string", "null"]},
                                "event_cue": {"type": ["string", "null"]},
                                "watch": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "action",
                                "due_day",
                                "due_time",
                                "event_cue",
                                "watch",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["intentions"],
                "additionalProperties": False,
            },
            where="extract",
        )

    def _intention_from_extract_item(
        self, item: dict[str, Any], *, today: str
    ) -> Intention:
        action = self._action_phrase(str(item.get("action") or "").strip())
        if len(action) < 6:
            _fail("extract", f"抽到的任务名称太短或空: {item!r}")
        due_raw = item.get("due") if isinstance(item.get("due"), dict) else {}
        due_time = str(item.get("due_time") or due_raw.get("time") or "").strip()
        if due_time.lower() in ("null", "none", "-"):
            due_time = ""
        m_time = _TIME_RE.search(due_time)
        due_time = m_time.group(0) if m_time else ""
        event_cue = str(item.get("event_cue") or item.get("event") or "").strip()
        event_cue = event_cue.rstrip(".")
        if event_cue.lower() in ("null", "none"):
            event_cue = ""
        due_day = self._resolve_due_day(
            str(item.get("due_day") or due_raw.get("day") or ""),
            today=today,
            due_time=due_time,
            event_cue=event_cue,
        )
        watch = self._normalize_watch(item.get("watch") or [])
        return Intention(
            intent_id=self._new_id(),
            action=action,
            status="pending",
            due=DueSlot(day=due_day, time=due_time),
            event_cue=event_cue,
            watch=watch,
        )

    @staticmethod
    def _normalize_weekday(day: str) -> str:
        low = (day or "").strip().lower()
        for name in _WEEKDAYS:
            if name == low:
                return name.capitalize()
        return (day or "").strip()

    def _resolve_due_day(
        self,
        raw_day: str,
        *,
        today: str = "",
        due_time: str = "",
        event_cue: str = "",
        named_day: bool = False,
    ) -> str:
        """Calendar due only. Planting day is not a due.

        Clock tasks may fall back to today. Event-only keeps a weekday only
        when it is an explicit named day other than the planting day (or
        `named_day` from an `On <Day>` clause).
        """
        token = (raw_day or "").strip()
        low = token.lower()
        if low in _EMPTY_DUE_DAY:
            weekday = ""
        else:
            weekday = self._normalize_weekday(token)
            if weekday.lower() in _EMPTY_DUE_DAY:
                weekday = ""

        today_norm = self._normalize_weekday(today) if today else ""
        if named_day:
            return weekday or today_norm
        if due_time:
            return weekday or today_norm
        if event_cue:
            if not weekday:
                return ""
            if today_norm and weekday.lower() == today_norm.lower():
                return ""
            return weekday
        return weekday or today_norm

    @staticmethod
    def _normalize_watch(names: Any) -> list[str]:
        allowed = set(_WATCH_ALLOWED)
        if names in (None, "", []):
            return []
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list):
            _fail("extract", f"watch 必须是名单或空: {names!r}")
        found: list[str] = []
        unknown: list[str] = []
        for raw in names:
            if not isinstance(raw, str) or not raw.strip():
                continue
            key = raw.strip().lower().replace(" ", "_")
            if key in ("null", "none"):
                continue
            if key not in allowed:
                unknown.append(raw)
                continue
            if key not in found:
                found.append(key)
        if unknown:
            _fail(
                "extract",
                f"watch 里有不在名单中的名字: {unknown}；允许: {sorted(allowed)}",
            )
        return found

    def _extract_from_text(self, text: str, *, day: str) -> int:
        if not text:
            return 0
        added = 0
        for m in _CROSS_DAY_RE.finditer(text):
            target_day = m.group(1).capitalize()
            rest = m.group(2).strip().rstrip(".")
            if len(rest) < 8:
                continue
            intent = self._parse_intention_line(rest, day=target_day, named_day=True)
            if intent is None:
                continue
            self._insert(intent)
            added += 1

        for raw_line in text.splitlines():
            line = raw_line.strip()
            m = _PLAN_BULLET_RE.match(line)
            body = m.group(1).strip() if m else ""
            if not body:
                continue
            if body.lower().startswith("today's loose plan"):
                continue
            intent = self._parse_intention_line(body, day=day)
            if intent is None:
                continue
            self._insert(intent)
            added += 1
        return added

    def _parse_intention_line(
        self, body: str, *, day: str, named_day: bool = False
    ) -> Intention | None:
        body = body.strip().rstrip(".")
        if len(body) < 6:
            return None
        low = body.lower()
        if low.startswith("regular tasks"):
            return None

        due_time = ""
        m_at = _AT_TIME_RE.search(body)
        if m_at:
            due_time = m_at.group(1)

        when = ""
        m_when = _WHEN_RE.search(body)
        if m_when:
            when = m_when.group(1).strip().rstrip(".")

        return Intention(
            intent_id=self._new_id(),
            action=self._action_phrase(body),
            status="pending",
            due=DueSlot(
                day=self._resolve_due_day(
                    day,
                    today=day,
                    due_time=due_time,
                    event_cue=when,
                    named_day=named_day,
                ),
                time=due_time,
            ),
            event_cue=when,
            watch=self._infer_channels(when or body),
        )

    @staticmethod
    def _action_phrase(body: str) -> str:
        """What to do, without when-clause or at HH:MM."""
        text = (body or "").strip().rstrip(".")
        m_when = _WHEN_RE.search(text)
        if m_when:
            text = text[: m_when.start()].strip().rstrip(",")
        text = _AT_TIME_RE.sub("", text)
        text = re.sub(r"\s+", " ", text).strip(" ,")
        if not text:
            return (body or "").strip().rstrip(".")
        return text[0].upper() + text[1:]

    @staticmethod
    def _weekday_index(day: str) -> int | None:
        if not day:
            return None
        try:
            return _WEEKDAYS.index(day.strip().lower())
        except ValueError:
            return None

    @staticmethod
    def _due_day(intent: Intention) -> str:
        return (intent.due.day or "").strip()

    def _is_active_on_day(self, intent: Intention, day: str) -> bool:
        """Hide only commitments whose due.day is still in the future.

        Empty due.day, today's due.day, and leftover earlier due.days stay
        visible. Day change must not cancel them.
        """
        return not self._due_day_is_future(intent, day)

    def _due_day_is_future(self, intent: Intention, today: str) -> bool:
        due = self._due_day(intent)
        if not due or not today:
            return False
        if due.lower() == today.lower():
            return False
        di, ti = self._weekday_index(due), self._weekday_index(today)
        if di is None or ti is None:
            return False
        return di > ti

    def _brief_intent(self, i: Intention) -> dict[str, Any]:
        return {
            "id": i.intent_id,
            "action": i.action,
            "due_day": i.due.day or "",
            "due_time": i.due.time or "",
            "event": i.event_cue or "",
            "watch": list(i.watch or []),
        }

    def _build_filter_trace(
        self,
        *,
        pending: list[Intention],
        today_pending: list[Intention],
        time_hits: list[Intention],
        channel_needed: list[str],
        day: str,
        step: str,
        time_str: str,
        messages: list[dict],
        extracted: list[dict[str, Any]],
        extract_added: int,
        match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        today_ids = {i.intent_id for i in today_pending}
        time_hit_ids = {i.intent_id for i in time_hits}
        clock_tasks = [i for i in today_pending if i.due.time]
        event_group = [
            i for i in today_pending if (i.event_cue or "").strip()
        ]
        no_event = [
            i for i in today_pending if not (i.event_cue or "").strip()
        ]
        match = match or {}
        if match.get("mode") == "llm":
            kept_src = match.get("kept") or []
        else:
            kept_src = today_pending
        return {
            "day": day,
            "step": step,
            "clock": time_str or "",
            "extract_added": extract_added,
            "extracted": list(extracted or []),
            "pending": [self._brief_intent(i) for i in pending],
            "drop_future_due_day": [
                self._brief_intent(i) for i in pending if i.intent_id not in today_ids
            ],
            "kept_today": [self._brief_intent(i) for i in today_pending],
            "time_due": [self._brief_intent(i) for i in time_hits],
            "time_not_due": [
                self._brief_intent(i)
                for i in clock_tasks
                if i.intent_id not in time_hit_ids
            ],
            "event_group": [self._brief_intent(i) for i in event_group],
            "no_event_group": [self._brief_intent(i) for i in no_event],
            "check_channels": list(channel_needed),
            "queried_this_step": sorted(self._queried_channels_this_step(messages)),
            "match_mode": match.get("mode") or "off",
            "match_event_due": [
                self._brief_intent(i) for i in (match.get("event_due") or [])
            ],
            "match_event_drop": [
                self._brief_intent(i) for i in (match.get("event_drop") or [])
            ],
            "match_channel_due": [
                self._brief_intent(i) for i in (match.get("channel_due") or [])
            ],
            "match_channel_drop": [
                self._brief_intent(i) for i in (match.get("channel_drop") or [])
            ],
            "match_channel_wait": [
                self._brief_intent(i) for i in (match.get("channel_wait") or [])
            ],
            "match_kept": [self._brief_intent(i) for i in kept_src],
        }

    def _format_filter_trace(self, trace: dict[str, Any]) -> str:
        def rows(items: list[dict[str, Any]]) -> list[str]:
            if not items:
                return ["- （无）"]
            lines = []
            for r in items:
                bits = [r.get("action") or r.get("id")]
                due = self._due_display(
                    str(r.get("due_day") or ""), str(r.get("due_time") or "")
                )
                if due:
                    bits.append(f"due={due}")
                if r.get("event"):
                    bits.append(f"event={r['event']}")
                watch = r.get("watch") or []
                if watch:
                    bits.append("watch=" + ",".join(str(w) for w in watch))
                bits.append(r.get("id") or "")
                lines.append("- " + " | ".join(str(b) for b in bits if b))
            return lines

        clock = trace.get("clock") or "（无可信钟）"
        heading = f"## {trace.get('day') or '?'} {trace.get('step') or ''}".strip()
        lines = [
            heading + f"  clock={clock}",
            "",
            "代码筛选：隐藏未来 due.day，给时钟命中打 TIME-DUE。",
            "event / channel：Scene Judge 开时筛掉未发生的 cue / 已查未到期的 watch"
            "（不是子串 EVENT-CUED）。同线索库存 fan-out 补齐漏标的 event_due。"
            "关时全部注入。",
            "无 State 的 watch 不筛掉、不盖 CHANNEL-DUE。"
            "TIME-DUE 只打标签；未命中的时钟行仍给 choose 看。",
            "",
            f"### 库存 pending（{len(trace.get('pending') or [])}）提取字段 time / event / watch",
            *rows(trace.get("pending") or []),
            "",
            f"### 1. 日历 — 筛掉未来 due.day（{len(trace.get('drop_future_due_day') or [])}）",
            *rows(trace.get("drop_future_due_day") or []),
            "",
            f"留下 today pending {len(trace.get('kept_today') or [])}",
            "",
            (
                f"### 2. 时钟 TIME-DUE — 打标签 {len(trace.get('time_due') or [])}；"
                f"有 due.time 未命中 {len(trace.get('time_not_due') or [])}（仍进 TODAY pending）"
            ),
            "命中:",
            *rows(trace.get("time_due") or []),
            "未命中:",
            *rows(trace.get("time_not_due") or []),
            "",
            (
                f"### 3. 事件 Scene Judge — 筛掉未发生的 cue"
                f"（mode={trace.get('match_mode') or 'off'}；"
                f"due {len(trace.get('match_event_due') or [])}，"
                f"筛掉 {len(trace.get('match_event_drop') or [])}）"
            ),
            "到期:",
            *rows(trace.get("match_event_due") or []),
            "筛掉:",
            *rows(trace.get("match_event_drop") or []),
            "",
            (
                "### 4. channel Scene Judge — 有 State 且未到期才筛掉；"
                "无 State 的 wait 留给 choose 决定是否 query"
            ),
            "CHANNEL due:",
            *rows(trace.get("match_channel_due") or []),
            "筛掉（已查过、未到期）:",
            *rows(trace.get("match_channel_drop") or []),
            "仍 wait（未查）:",
            *rows(trace.get("match_channel_wait") or []),
            "",
            f"### 5. 交给 choose 的剩余（{len(trace.get('match_kept') or [])}）",
            *rows(trace.get("match_kept") or []),
            "",
            "CHECK: "
            + (", ".join(trace.get("check_channels") or []) or "（无）"),
            "本步已查过: "
            + (", ".join(trace.get("queried_this_step") or []) or "（无）"),
        ]
        extracted = trace.get("extracted") or []
        lines.append("")
        if extracted:
            lines.append(
                f"### 本步 extract 新种（{len(extracted)}，含模型原始字段）"
            )
            for ex in extracted:
                raw = ex.get("raw") if isinstance(ex, dict) else {}
                st = ex.get("stored") if isinstance(ex, dict) else {}
                raw = raw or {}
                st = st or {}
                lines.append(
                    "- raw "
                    f"due_day={raw.get('due_day')!r} due_time={raw.get('due_time')!r} "
                    f"event={raw.get('event_cue')!r} watch={raw.get('watch')!r} "
                    f"→ stored {st.get('action') or '-'} "
                    f"due={st.get('due_day') or '-'} {st.get('due_time') or ''} "
                    f"event={st.get('event') or '-'} watch={st.get('watch') or []}"
                )
        else:
            lines.append("### 本步 extract 新种：无（空场景 / 缓存 / 日计划正则另走）")
        return "\n".join(lines) + "\n"

    def _append_filter_log(self, text: str) -> None:
        if not self._filter_log_path or not text:
            return
        self._filter_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._filter_log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")

    @staticmethod
    def _rewrite_due_world(intent: Intention, *, day: str, new_time: str = "") -> None:
        """Treat a reschedule as rewriting the world's due slot."""
        if day:
            intent.due.day = day
        if new_time:
            intent.due.time = new_time

    # ------------------------------------------------------------- filters
    def _filter_time_due(self, pending: list[Intention], time_str: str) -> list[Intention]:
        if not time_str:
            return []
        cur = self._to_minutes(time_str)
        if cur is None:
            return []
        hits = []
        for intent in pending:
            tgt = self._to_minutes(intent.due.time)
            if tgt is None:
                continue
            if abs(cur - tgt) <= self.time_tolerance_minutes:
                hits.append(intent)
        return hits

    def _watch_needed(self, pending: list[Intention], messages: list[dict]) -> list[str]:
        """Watch names not yet queried in *this* step. Results live in the transcript."""
        queried = self._queried_channels_this_step(messages)
        needed: list[str] = []
        for intent in pending:
            for name in intent.watch:
                name = (name or "").strip().lower()
                if not name or name == "clock" or name in queried:
                    continue
                if name not in needed:
                    needed.append(name)
        return needed

    @staticmethod
    def _queried_channels_this_step(messages: list[dict]) -> set[str]:
        if not messages:
            return set()
        found: set[str] = set()
        for msg in messages[current_step_start_index(messages) :]:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if content.startswith("Time:"):
                found.add("clock")
            for m in _STATE_REPLY_RE.finditer(content):
                found.add(m.group(1).strip().lower())
        return found

    def _state_replies_this_step(self, messages: list[dict]) -> dict[str, str]:
        found: dict[str, str] = {}
        if not messages:
            return found
        for msg in messages[current_step_start_index(messages) :]:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            for m in _STATE_REPLY_RE.finditer(content):
                found[m.group(1).strip().lower()] = m.group(2).strip()
        return found

    def _match_event_channel(
        self,
        today_pending: list[Intention],
        *,
        observation: str,
        day: str,
        time_str: str,
        messages: list[dict],
    ) -> dict[str, Any]:
        """Apply cached scene-judge due labels. Does not force query_state."""
        empty = {
            "mode": "off",
            "kept": list(today_pending),
            "event_due": [],
            "channel_due": [],
            "event_drop": [],
            "channel_drop": [],
            "channel_wait": [],
        }
        if not self.use_llm_match:
            self.last_match_info = {"mode": "off"}
            return empty
        needs = [
            i
            for i in today_pending
            if (i.event_cue or "").strip() or list(i.watch or [])
        ]
        if not needs:
            self.last_match_info = {"mode": "skip", "reason": "no_event_or_watch"}
            empty["mode"] = "skip"
            return empty

        states = self._state_replies_this_step(messages)
        queried = set(states) | self._queried_channels_this_step(messages)
        pending = [i for i in self.intentions.values() if i.status == "pending"]
        self._ensure_scene_judge(
            observation,
            pending or today_pending,
            day=day,
            time_str=time_str,
            messages=messages,
            apply_updates=False,
        )
        labels = dict(self._last_match_labels or {})
        raw_due = set(labels.get("event_due_ids") or [])
        event_due_ids = self._expand_event_due_ids(today_pending, raw_due)
        labels["event_due_ids"] = list(event_due_ids)

        split = self._apply_match_labels(
            today_pending,
            event_due_ids=event_due_ids,
            channel_due_ids=set(labels.get("channel_due_ids") or []),
            queried=queried,
        )
        split["mode"] = "llm"
        self.last_match_info = {
            "mode": "llm",
            "event_due_ids": list(event_due_ids),
            "event_due_fanout_ids": sorted(event_due_ids - raw_due),
            "event_wait_ids": [i.intent_id for i in split["event_drop"]],
            "channel_due_ids": list(labels.get("channel_due_ids") or []),
            "channel_wait_ids": [i.intent_id for i in split["channel_wait"]],
            "channel_drop_ids": [i.intent_id for i in split["channel_drop"]],
            "kept": [i.intent_id for i in split["kept"]],
            "queried": sorted(queried),
        }
        return split

    def _ns_to_ids(self, raw: Any, index: dict[int, str]) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            try:
                n = int(item)
            except (TypeError, ValueError):
                continue
            iid = index.get(n)
            if iid and iid not in out:
                out.append(iid)
        return out

    def _apply_match_labels(
        self,
        today_pending: list[Intention],
        *,
        event_due_ids: set[str],
        channel_due_ids: set[str],
        queried: set[str],
    ) -> dict[str, Any]:
        """Drop unmatched events; drop watch rows whose State is in and not due."""
        event_due: list[Intention] = []
        event_drop: list[Intention] = []
        channel_due: list[Intention] = []
        channel_drop: list[Intention] = []
        channel_wait: list[Intention] = []
        kept: list[Intention] = []
        for intent in today_pending:
            has_event = bool((intent.event_cue or "").strip())
            watches = [
                (w or "").strip().lower()
                for w in (intent.watch or [])
                if (w or "").strip() and (w or "").strip().lower() != "clock"
            ]
            drop = False
            if has_event and intent.intent_id not in event_due_ids:
                event_drop.append(intent)
                drop = True
            elif has_event:
                event_due.append(intent)
            if watches:
                all_seen = all(w in queried for w in watches)
                # No this-step State ⇒ wait, never due (do not trust a
                # hallucinated channel_due; do not force query_state).
                if intent.intent_id in channel_due_ids and all_seen:
                    channel_due.append(intent)
                elif all_seen:
                    channel_drop.append(intent)
                    drop = True
                else:
                    channel_wait.append(intent)
            if not drop:
                kept.append(intent)
        kept_ids = {i.intent_id for i in kept}
        return {
            "kept": kept,
            "event_due": [i for i in event_due if i.intent_id in kept_ids],
            "event_drop": event_drop,
            "channel_due": [i for i in channel_due if i.intent_id in kept_ids],
            "channel_drop": channel_drop,
            "channel_wait": channel_wait,
        }

    @staticmethod
    def _event_cue_tokens(cue: str) -> tuple[str, ...]:
        raw = _CUE_TOKEN_RE.findall((cue or "").lower())
        return tuple(t for t in raw if t not in _CUE_STOP and len(t) > 1)

    @classmethod
    def _event_cues_share(cls, left: str, right: str) -> bool:
        """Same stored condition, not vignette substring EVENT-CUED."""
        a, b = cls._event_cue_tokens(left), cls._event_cue_tokens(right)
        if not a or not b:
            return False
        if a == b:
            return True
        if len(a) < 2 or len(b) < 2:
            return False
        ba = {a[i : i + 2] for i in range(len(a) - 1)}
        bb = {b[i : i + 2] for i in range(len(b) - 1)}
        if ba & bb:
            return True
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        n = len(short)
        return any(long_[i : i + n] == short for i in range(len(long_) - n + 1))

    def _expand_event_due_ids(
        self, pending: list[Intention], event_due_ids: set[str]
    ) -> set[str]:
        """If the judge hits one row, also due pending rows with the same cue."""
        if not event_due_ids:
            return set()
        by_id = {i.intent_id: i for i in pending}
        extra = set(event_due_ids)
        if not any(
            iid in by_id and (by_id[iid].event_cue or "").strip()
            for iid in extra
        ):
            return extra
        changed = True
        while changed:
            changed = False
            seeds = [
                by_id[iid]
                for iid in extra
                if iid in by_id and (by_id[iid].event_cue or "").strip()
            ]
            for intent in pending:
                if intent.intent_id in extra:
                    continue
                cue = (intent.event_cue or "").strip()
                if not cue:
                    continue
                if any(self._event_cues_share(cue, seed.event_cue) for seed in seeds):
                    extra.add(intent.intent_id)
                    changed = True
        return extra

    def _cluster_by_shared_cue(
        self, items: list[Intention]
    ) -> list[list[Intention]]:
        remaining = list(items)
        clusters: list[list[Intention]] = []
        while remaining:
            cluster = [remaining.pop(0)]
            changed = True
            while changed:
                changed = False
                keep: list[Intention] = []
                for other in remaining:
                    if any(
                        self._event_cues_share(other.event_cue, member.event_cue)
                        for member in cluster
                    ):
                        cluster.append(other)
                        changed = True
                    else:
                        keep.append(other)
                remaining = keep
            clusters.append(cluster)
        return clusters

    @classmethod
    def _shared_cue_label(cls, items: list[Intention]) -> str:
        seqs = [cls._event_cue_tokens(i.event_cue) for i in items]
        seqs = [s for s in seqs if s]
        if not seqs:
            return ((items[0].event_cue if items else "") or "cue").strip()
        first = seqs[0]
        for n in range(len(first), 1, -1):
            for i in range(len(first) - n + 1):
                span = first[i : i + n]
                if all(
                    any(s[j : j + n] == span for j in range(len(s) - n + 1))
                    for s in seqs[1:]
                ):
                    return " ".join(span)
        if all(s == first for s in seqs):
            return " ".join(first)
        return " ".join(first)

    def _append_event_inject_section(
        self,
        sections: list[str],
        items: list[Intention],
        render_lines,
        *,
        due: bool,
        match_filtered: bool,
    ) -> None:
        if due and match_filtered:
            sections.append(
                "EVENT due (scene judge: this vignette shows these event= cues. "
                "One cue can due several rows — include ALL matching menu handles "
                "in this choose; the vignette may name only one action):"
            )
        else:
            sections.append(
                "EVENT pending (not a due stamp; if THIS vignette shows "
                "event=..., do ALL rows that share that cue, not just the "
                "action named in the scene; otherwise leave them):"
            )
        for cluster in self._cluster_by_shared_cue(items):
            if len(cluster) >= 2:
                sections.append(f"  [{self._shared_cue_label(cluster)}]")
            sections.extend(render_lines(cluster, "EVENT"))

    # ----------------------------------------------------------- formatting
    def _format_injection(
        self,
        *,
        time_hits: list[Intention],
        event_hits: list[Intention],
        channel_hits: list[Intention],
        channel_needed: list[str],
        today_pending: list[Intention],
        day: str,
        time_str: str,
        force_check_time: bool = False,
        pending_time_n: int = 0,
        match_filtered: bool = False,
    ) -> str:
        sections: list[str] = []
        header = f"Prospective intention store @ {day} {time_str or '(clock unknown)'}"
        sections.append(header)
        if force_check_time:
            sections.append(
                f"MUST check_time (or query_state channel=clock) BEFORE choose: "
                f"no trusted current clock, but {pending_time_n} pending time "
                f"intention(s) need a real now to decide TIME-DUE."
            )

        def _lines(items: list[Intention], tag: str) -> list[str]:
            out = []
            seen = set()
            for i in items:
                if i.intent_id in seen:
                    continue
                seen.add(i.intent_id)
                out.append(f"- [{tag}] {self._render_intent(i)}")
            return out

        block = _lines(time_hits, "TIME-DUE")
        if block:
            sections.append("TIME-DUE (calendar-style reminder):")
            sections.extend(block)

        if channel_needed:
            sections.append(
                "CHECK channels (watchlist only — query_state is your decision; "
                "replies appear as State [channel] in this step): "
                + ", ".join(channel_needed)
            )

        block = _lines(channel_hits, "CHANNEL-DUE")
        if block:
            sections.append(
                "CHANNEL due (scene judge: this-step State satisfies watch):"
            )
            sections.extend(block)

        shown = {i.intent_id for i in time_hits + channel_hits}
        event_show = [i for i in event_hits if i.intent_id not in shown]
        event_pending = [
            i
            for i in today_pending
            if i.intent_id not in shown
            and i.intent_id not in {e.intent_id for e in event_hits}
            and (i.event_cue or "").strip()
        ]
        rest = [
            i
            for i in today_pending
            if i.intent_id not in shown
            and i.intent_id not in {e.intent_id for e in event_hits}
            and not (i.event_cue or "").strip()
        ]
        if event_show:
            self._append_event_inject_section(
                sections,
                event_show,
                _lines,
                due=True,
                match_filtered=match_filtered,
            )
            shown.update(i.intent_id for i in event_show)
        elif event_pending:
            self._append_event_inject_section(
                sections,
                event_pending,
                _lines,
                due=False,
                match_filtered=False,
            )
            shown.update(i.intent_id for i in event_pending)
        if rest:
            sections.append(
                "TODAY pending (not a due stamp; match current menu by meaning):"
            )
            sections.extend(_lines(rest, "PENDING"))

        # If everything empty, say so explicitly.
        body = "\n".join(sections)
        if body.strip() == header.strip():
            return header + "\n(No pending intentions.)"
        return scrub_task_handles(body)

    @staticmethod
    def _due_display(day: str = "", time: str = "") -> str:
        d = (day or "").strip()
        t = (time or "").strip()
        if not d and not t:
            return ""
        return f"{d} {t}".strip()

    def _intent_field_bits(self, i: Intention) -> list[str]:
        bits = [f"action={i.action}"]
        due = self._due_display(i.due.day, i.due.time)
        if due:
            bits.append(f"due={due}")
        if i.event_cue:
            bits.append(f"event={i.event_cue}")
        if i.watch:
            bits.append("watch=" + ",".join(i.watch))
        return bits

    def _render_intent(self, i: Intention) -> str:
        parts = [i.action]
        due = self._due_display(i.due.day, i.due.time)
        if due:
            parts.append(f"due={due}")
        if i.event_cue:
            parts.append(f"event={i.event_cue}")
        if i.watch:
            parts.append("watch=" + ",".join(i.watch))
        parts.append(f"status={i.status}")
        return " | ".join(parts)

    def _insert(self, intent: Intention) -> None:
        """Always add a new row. No action-overlap merge."""
        if not intent.intent_id:
            intent.intent_id = self._new_id()
        self.intentions[intent.intent_id] = intent

    def _infer_channels(self, text: str) -> list[str]:
        low = (text or "").lower()
        found: list[str] = []
        for name, hints in CHANNEL_HINTS.items():
            if name == "clock":
                continue
            if any(h in low for h in hints) and name not in found:
                found.append(name)
        return found

    @staticmethod
    def _first_time(text: str) -> str:
        m = _TIME_RE.search(text or "")
        return m.group(0) if m else ""

    @staticmethod
    def _to_minutes(t: str) -> int | None:
        m = _TIME_RE.search(t or "")
        if not m:
            return None
        return int(m.group(1)) * 60 + int(m.group(2))

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            t
            for t in re.findall(r"[a-z0-9$]+", (text or "").lower())
            if t not in {
                "a", "an", "the", "to", "of", "and", "or", "for", "on", "in",
                "at", "when", "your", "you", "with", "is", "it", "be", "do",
            }
            and len(t) > 1
        }

    def _overlap_score(self, a: Any, b: Any) -> float:
        if isinstance(a, Intention):
            a = f"{a.action} {a.event_cue}"
        if isinstance(b, Intention):
            b = f"{b.action} {b.event_cue}"
        ta, tb = self._tokens(str(a)), self._tokens(str(b))
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        return inter / float(min(len(ta), len(tb)))

    @staticmethod
    def _new_id() -> str:
        return "int_" + uuid.uuid4().hex[:10]

    def _export_payload(self) -> dict[str, Any]:
        return {
            "intentions": [i.to_dict() for i in self.intentions.values()],
            "seeded_days": sorted(self._seeded_days),
            "daily_day": self._daily_day,
        }

    def _status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for intent in self.intentions.values():
            counts[intent.status] = counts.get(intent.status, 0) + 1
        return counts

    def _save(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._export_payload()
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        md_path = self.store_path.with_suffix(".md")
        md_path.write_text(self._render_readable(payload), encoding="utf-8")

    def _save_step(
        self,
        *,
        event: str,
        day: str = "",
        step: str = "",
        time_str: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append one inspectable snapshot so a bad step can be grepped later."""
        if not self._step_log_path:
            return
        self._step_log_path.parent.mkdir(parents=True, exist_ok=True)
        rec: dict[str, Any] = {
            "event": event,
            "day": day,
            "step": step,
            "time": time_str,
            "n_intentions": len(self.intentions),
            "status_counts": self._status_counts(),
            "intentions": [i.to_dict() for i in self.intentions.values()],
        }
        if extra:
            rec.update(extra)
        with self._step_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _render_readable(self, payload: dict[str, Any]) -> str:
        """Human-readable current-board dump (overwritten; history is steps.jsonl)."""
        lines = [
            f"# Intention store  (daily_day={payload.get('daily_day') or '-'})",
            "",
        ]
        by_status: dict[str, list[dict[str, Any]]] = {
            "pending": [],
            "done": [],
            "canceled": [],
        }
        for item in payload.get("intentions") or []:
            by_status.setdefault(item.get("status") or "?", []).append(item)
        for status in ("pending", "done", "canceled"):
            items = by_status.get(status) or []
            lines.append(f"## {status} ({len(items)})")
            if not items:
                lines.append("- (none)")
                lines.append("")
                continue
            for item in items:
                due = item.get("due") if isinstance(item.get("due"), dict) else {}
                bits = [item.get("action") or item.get("intent_id")]
                due_label = self._due_display(
                    str(due.get("day") or ""), str(due.get("time") or "")
                )
                if due_label:
                    bits.append(f"due={due_label}")
                if item.get("event_cue"):
                    bits.append(f"event={item['event_cue']}")
                watch = item.get("watch") or []
                if watch:
                    bits.append("watch=" + ",".join(str(w) for w in watch))
                bits.append(item.get("intent_id") or "")
                lines.append("- " + " | ".join(str(b) for b in bits if b))
            lines.append("")
        return "\n".join(lines) + "\n"

    def _load(self) -> None:
        raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        self.intentions = {}
        for item in raw.get("intentions") or []:
            if not isinstance(item, dict):
                continue
            intent = self._intention_from_raw(item)
            self.intentions[intent.intent_id] = intent
        self._seeded_days = set(raw.get("seeded_days") or [])
        self._daily_day = str(raw.get("daily_day") or "")

    @classmethod
    def _intention_from_raw(cls, item: dict[str, Any]) -> Intention:
        due_raw = item.get("due")
        if isinstance(due_raw, dict):
            due = DueSlot(
                day=str(due_raw.get("day") or ""),
                time=str(due_raw.get("time") or ""),
            )
        else:
            due = DueSlot(
                day=str(item.get("target_day") or item.get("created_day") or ""),
                time=str(item.get("target_time") or ""),
            )
        watch: list[str] = []
        for name in item.get("watch") or []:
            if isinstance(name, str) and name:
                watch.append(name)
        if not watch:
            for c in item.get("channels") or []:
                if isinstance(c, dict) and c.get("name"):
                    watch.append(str(c["name"]))
                elif isinstance(c, str) and c:
                    watch.append(c)
        action = str(item.get("action") or "").strip()
        if not action:
            action = str(item.get("action_text") or item.get("summary") or "").strip().rstrip(".")
            action = cls._action_phrase(action)
        return Intention(
            intent_id=str(item.get("intent_id") or cls._new_id()),
            action=action,
            status=str(item.get("status") or "pending"),
            due=due,
            event_cue=str(item.get("event_cue") or item.get("trigger_event") or ""),
            watch=watch,
        )


def build_intention_backend(
    *,
    store_path: str | None = None,
    max_inject_chars: int = 6000,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    use_llm_update: bool = True,
    use_llm_extract: bool = True,
    use_llm_done: bool = True,
    use_llm_match: bool = True,
    llm_timeout: float = 120.0,
):
    """Build intention store; enable LLM judges when credentials are given."""
    client = None
    want_llm = use_llm_update or use_llm_extract or use_llm_done or use_llm_match
    if want_llm and api_key and model:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise SystemExit(
                "intention LLM features require openai: pip install openai"
            ) from exc
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=llm_timeout)
    return IntentionStoreBackend(
        store_path=store_path,
        max_inject_chars=max_inject_chars,
        llm_client=client,
        llm_model=model,
        use_llm_update=bool(client and model and use_llm_update),
        use_llm_extract=bool(client and model and use_llm_extract),
        use_llm_done=bool(client and model and use_llm_done),
        use_llm_match=bool(client and model and use_llm_match),
    )
