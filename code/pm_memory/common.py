"""Shared helpers for PM-Bench memory backends."""

from __future__ import annotations

import re
from typing import Any, Protocol


MEMORY_MARKER = "[Relevant_memories]"

MEMORY_INJECT_HEADER = (
    "[Relevant_memories]\n"
    "Earlier deferred intentions / cues (not the full chat). "
    "Use these to decide which menu tasks are due now; "
    "ignore routine A/B/C activity choices stored by mistake. "
    "Historical menu handles like task_N are step-local and invalid now — "
    "match by action meaning / cue text only. "
    "If memories list CHECK channels, prefer query_state on those channels "
    "before choosing; TIME-DUE is a soft reminder. Channel query replies "
    "appear as State [channel] in this step, not in memory.\n"
)

# Decision-model guide for the prospective intention store (see docs/notes/intention.md).
INTENTION_MEMORY_INJECT_HEADER = """\
[Relevant_memories]
[Prospective Intention Memory]

This block is an external intention store.
It keeps deferred commitments: do X later when a condition holds.
The board rules (A/B/C, menu handles, query_state / check_time, follow latest
scene updates) still apply; this only explains how to read THIS memory.

Fields
- action: what to do. Align to the current Step action menu by meaning only.
  Does not include when-clauses or at HH:MM.
- status:
  - pending  = still in force; may become due
  - done     = already performed; do not repeat
  - canceled = later voided; must not be performed
- due.day: optional calendar weekday this commitment is for. If it is still in
  the future, ignore the item until that day. If missing, today, or already
  past, the commitment is still in force (leftover is not auto-canceled).
  Do not treat the day the reminder was written as a due.
- due.time: optional HH:MM. If set, due when the true current clock matches.
  If missing, this is not a clock task.
- event: optional vignette cue. A scene judge already dropped rows whose cue
  is not happening in this vignette. Remaining EVENT due rows matched this scene.
  A rewrite ("watch for X later") is not the event firing.
- watch: channel names. If THIS step has no State [channel] yet, CHECK is a
  soft reminder to query_state (your decision). The scene judge only marks
  CHANNEL due after a this-step State reply.

Injected labels (soft due hints from memory—not ground truth of the world)
- TIME-DUE: pending intention whose due.time matches current clock evidence
  (vignette "Time:", check_time, or State [clock]). Appearing here does not
  force a menu pick; you still decide. If clock evidence is missing, do not
  invent the time; check_time when time-sensitive pending work may matter.
- CHECK channels: watchlist only; querying is still your decision. This-step
  query replies are already in the dialogue as State [channel] lines.
- EVENT due: the scene judge said this vignette shows that event= cue now.
  Event-cued rows whose cue is absent were dropped from this block.
  Rows grouped under one [cue] share that condition — include every matching
  task_id this choose. The vignette may name only one of the actions.
- CHANNEL due: the scene judge said a this-step State [channel] satisfies watch.
  Watch rows with no State yet stay listed so you can still query; they are
  not due stamps.
- TODAY pending: other still-open intentions (including clock tasks that are
  not TIME-DUE). Appearing here does not mean due now.

How to decide this step
1. Ignore done and canceled. Only consider pending.
2. Ask: is this pending intention due *now* (TIME-DUE / EVENT due / CHANNEL
   due / this-step State [channel] reply)—or only relevant later?
3. If due depends on unknown clock or unqueried channels, query first, then choose.
4. Choose menu actions that fulfill currently due pending intentions; skip lures
   and obsolete cues. Match menu by meaning; skip items with no matching menu
   action. TIME-DUE is a reminder, not a required pick.
5. If the vignette revises an intention (cancel / reschedule / override—including
   polite or indirect wording), patch is already in this store. Execute against
   the stored due.time / event, not the original morning wording.
6. A scene that restates an old cue or old clock is a lure if this block already
   has a newer event or due.time. Do not fire on the obsolete condition.
7. task_ids is a list. One vignette cue can make several EVENT due rows due at
   once (same [cue] group). Include every matching menu handle this step. Do
   not stop after the morning-list / scene-named action.

"""

# Scene-judge: updates + event/channel due lists (see docs/notes/intention.md).
INTENTION_SCENE_JUDGE_PROMPT = """\
The PENDING list below is numbered 1, 2, 3, … — that integer is `n`.
Point to a row by n only. Do not copy ids.

Only mark rows that changed THIS STEP. Unmentioned rows stay as they are
(pending; cue not in this scene is not a mark).

updates.action is exactly one of: cancel | reschedule | override.
event_due / channel_due are lists of n. Labels do not change status.

event_due — CURRENT SCENE shows that row's event= happening now.
  The row stays pending. This is NOT cancel.
  One scene cue can fire several rows. Put EVERY n whose event= matches
  that cue into event_due, including rows whose action is not mentioned
  in the vignette. Do not stop after the morning-list / scene-named action.
channel_due — a THIS-STEP State [channel] satisfies that row's watch.
  No State yet ⇒ do not mark (choose may still query). Do not invent State.

Do not mark atmosphere, lures, or unrelated nearby tasks.
Never put the same n in both event_due and updates cancel.

Return JSON, nothing else. Empty scene → empty lists.
{"updates":[],"event_due":[2,7],"event_wait":[],"channel_due":[],"channel_wait":[]}
{"updates":[{"n":4,"action":"cancel","new_time":null,"new_day":null,"new_trigger":null,"new_action":null,"rationale":"..."}],"event_due":[],"event_wait":[],"channel_due":[],"channel_wait":[]}
"""

# Done-judge: which pending rows the chosen menu actions just fulfilled.
INTENTION_DONE_JUDGE_PROMPT = """\
You mark which pending intentions were just carried out this step.

The assistant already chose menu actions. Your only job: decide which numbered
PENDING rows those actions fulfill.

Do:
- Match by meaning, including paraphrases ("Pick up the replacement filter"
  vs "Collect the HVAC filter").
- Identify rows by list number n (1, 2, 3, …) only.
- Mark a row only if a chosen action actually performs that commitment now.
- If several chosen actions fulfill several pending rows (including rows that
  share a cue), mark every fulfilled n.

Do not:
- Mark two clock slots as one (asthma at 11:00 vs 21:00 stay distinct).
- Mark because of shared words alone.
- Mark cancel / reschedule / override (another judge handles those).
- Mark a pending item that was not performed this step.
- Invent rows or copy any identifier other than n.

Return JSON:
{"done":[1,3]}
Use {"done": []} if none of the pending rows were fulfilled.
"n" must be an integer that appears in the numbered list.
"""

# Extract-judge: plant NEW deferred intentions from a vignette (not day-plan bullets).
INTENTION_EXTRACT_JUDGE_PROMPT = """\
You extract NEW deferred intentions from every current scene.

A deferred intention is a commitment to do X later when a condition holds
(a weekday, a clock time, a visible vignette cue, or a hidden channel).

Read the WHOLE CURRENT SCENE. Split out every new deferred commitment, even if
the wording is indirect, polite, or jammed into one paragraph with other
sentences. Do not wait for phrases like "On Friday" or "reminder".

Do:
- Split multiple commitments in one paragraph into separate items.
- For "On <Day>, …" keep only that commitment, ending at the first period.
- action = what to do, without "when …" and without "at HH:MM".
- due_day = a weekday ONLY if the scene names when on the calendar to do it
  ("On Friday", "Wednesday"). Null if this is event-cued and no weekday is
  named. Do NOT copy TODAY / the planting day just because the reminder
  appeared today.
- due_time = HH:MM if this commitment names a clock time, else null.
- event_cue = the visible when-clause to look for in a later vignette. Empty if none.
- watch = channel names to query_state later, ONLY from the allowed list in the
  user message. Empty if the cue is something you would see in a vignette
  (notice the cart, lab cubby, doorbell, clipboard).

Do not:
- Invent commitments that are not in the scene. Atmosphere, feelings, or
  "keep meaning to" without a real later action is not a new intention.
- Extract cancel / reschedule / override of an existing task (another judge
  handles those). "No longer needs to happen" is not a new intention.
- Extract something the person should do immediately in this step.
- Put email/calendar/portal in watch just because the action verb is "Email".

Return JSON:
{"intentions":[{"action":"...","due_day":"Friday","due_time":null,"event_cue":"...","watch":[]}]}
Use {"intentions": []} if this scene has no new deferred intention.
"""


_TASK_HANDLE_RE = re.compile(r"\btask_\d+\b", re.I)
_ACTIONS_TASK_RE = re.compile(
    r"\s*\|\s*actions:\s*(?:none|task_[\w,\s]*)",
    re.I,
)
_MENU_LINE_RE = re.compile(
    r"^\s*-\s*(task_\d+)\s*:\s*(.+?)\s*$",
    re.I | re.M,
)


class MemoryBackend(Protocol):
    """Minimal surface needed by the PM-Bench memory session."""

    name: str

    def recall(self, query: str, *, top_k: int = 10) -> str:
        """Return text to inject into the prompt (may be empty)."""

    def encode(self, turn: dict[str, Any]) -> None:
        """Persist one completed PM step turn."""


def strip_action_menu(text: str) -> str:
    """Keep vignette + options (+ trailing Time line); drop the step action menu."""
    if not text:
        return ""
    lines = text.splitlines()
    kept: list[str] = []
    trailing_meta: list[str] = []
    in_menu = False
    for line in lines:
        low = line.strip().lower()
        if low.startswith("step action menu") or low.startswith("daily action-handle"):
            in_menu = True
            continue
        if in_menu:
            # Time is appended *after* the menu when visible; keep it.
            if re.match(r"^Time:\s*\d{1,2}:\d{2}", line.strip(), flags=re.I):
                trailing_meta.append(line)
            continue
        if re.match(r"^task_\d+\s*:", line.strip(), flags=re.I):
            in_menu = True
            continue
        kept.append(line)
    out = "\n".join(kept + trailing_meta).strip()
    return out or text[:1500]


def strip_abc_options(text: str) -> str:
    """Drop mandatory ongoing-activity options (A/B/C) — noise for PM memory."""
    if not text:
        return ""
    lines = [
        line
        for line in text.splitlines()
        if not re.match(r"^[ABC]\)\s+", line.strip())
    ]
    return "\n".join(lines).strip()


_CLOCK_TIME_LABELED_RE = re.compile(
    r"\bTime:\s*([0-9]{1,2}:[0-9]{2})\b",
    re.I,
)
# PM-Bench clock dumps sometimes omit the colon: "Time 15:58 | Stopwatch: …"
_CLOCK_TIME_BARE_LABEL_RE = re.compile(
    r"\bTime\s+([0-9]{1,2}:[0-9]{2})\b",
    re.I,
)
_STATE_CLOCK_RE = re.compile(r"State\s*\[clock\]", re.I)


def extract_time_str(text: str) -> str:
    """Pull *current clock* HH:MM from system-formatted evidence only.

    Trusted sources (same formats PM-Bench emits):
      - vignette / reply line: ``Time: HH:MM | Stopwatch: …``
      - ``State [clock]: …`` / ``State [clock]\\n…`` dumps (``Time:`` or ``Time HH:MM``)

    Never treat bare ``HH:MM`` in narrative ("asthma at 11:00", menu due times)
    as the current clock — that polluted TIME-DUE matching.
    """
    if not text:
        return ""
    m = _CLOCK_TIME_LABELED_RE.search(text)
    if m:
        return m.group(1)
    if _STATE_CLOCK_RE.search(text):
        m = _CLOCK_TIME_BARE_LABEL_RE.search(text)
        if m:
            return m.group(1)
    return ""


def truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated for PM context budget]"
    return text


def parse_action_menu_map(text: str) -> dict[str, str]:
    """Map step-local handles (task_N) → action text from a vignette+menu blob."""
    if not text:
        return {}
    out: dict[str, str] = {}
    for m in _MENU_LINE_RE.finditer(text):
        handle = m.group(1).lower()
        label = m.group(2).strip().rstrip(".")
        if handle and label:
            out[handle] = label
    return out


def resolve_action_labels(turn: dict[str, Any]) -> list[str]:
    """Resolve chosen task_ids to human labels; never return raw handles."""
    action = turn.get("action") or {}
    task_ids = action.get("task_ids") or []
    if not task_ids:
        return []
    menu = parse_action_menu_map(
        turn.get("step_raw") or turn.get("observation") or ""
    )
    labels: list[str] = []
    for tid in task_ids:
        key = str(tid).strip().lower()
        label = menu.get(key, "").strip()
        if label and not _TASK_HANDLE_RE.fullmatch(label):
            labels.append(label)
    return labels


def scrub_task_handles(text: str) -> str:
    """Remove step-local task_N handles from stored/recalled memory text."""
    if not text:
        return ""
    cleaned = _ACTIONS_TASK_RE.sub("", text)
    cleaned = _TASK_HANDLE_RE.sub("", cleaned)
    # Collapse horizontal whitespace only — keep newlines for paper A-Mem raw blocks.
    cleaned = re.sub(r"[^\S\n]{2,}", " ", cleaned)
    cleaned = re.sub(r"[^\S\n]*\n[^\S\n]*", "\n", cleaned)
    cleaned = re.sub(r"[^\S\n]+\|[^\S\n]+\|", " |", cleaned)
    lines = [ln.strip(" |") for ln in cleaned.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def format_memory_injection(
    memory_text: str,
    *,
    header: str | None = None,
) -> str:
    body = scrub_task_handles((memory_text or "").strip()) or "(No relevant memories)"
    return f"{header or MEMORY_INJECT_HEADER}{body}"


def _scene_for_store(turn: dict[str, Any]) -> str:
    """Compact scene text for write path: narrative cues only, no A/B/C."""
    raw = turn.get("observation") or ""
    return strip_abc_options(strip_action_menu(raw))


def format_turn_note(turn: dict[str, Any], *, max_scene_chars: int = 220) -> str:
    """Compact single-string note for A-Mem (keeps retrieval lean).

    Stores action *labels*, never step-local task_N handles.
    """
    day = turn.get("day", "")
    step = turn.get("step", "")
    time_str = turn.get("time", "")
    scene = " ".join(_scene_for_store(turn).split())
    if max_scene_chars > 0 and len(scene) > max_scene_chars:
        scene = scene[: max_scene_chars - 1] + "…"
    labels = resolve_action_labels(turn)
    head = f"[{day} {step} {time_str}]".replace("  ", " ").strip()
    if labels:
        did = "; ".join(labels)
        body = f"{head} {scene} | did: {did}" if scene else f"{head} did: {did}"
    else:
        body = f"{head} {scene}".strip() if scene else head
    return scrub_task_handles(body)


def format_turn_messages(turn: dict[str, Any]) -> list[dict[str, str]]:
    """Conversation turns for systems that extract from messages (Mem0)."""
    day = turn.get("day", "")
    step = turn.get("step", "")
    time_str = turn.get("time", "")
    scene = _scene_for_store(turn)
    labels = resolve_action_labels(turn)
    user = (
        f"PM deferred-intention note [{day} {step} {time_str}]\n"
        f"{scene}"
    )
    if labels:
        assistant = (
            "Record that these prospective actions were performed this step "
            f"(by meaning, not menu id): {'; '.join(labels)}. "
            "Keep any still-pending intentions from the scene. "
            "Never store step-local handles like task_N."
        )
    else:
        assistant = (
            "No prospective menu actions this step. "
            "Remember any new deferred intentions or cue changes in the scene. "
            "Never store step-local handles like task_N."
        )
    return [
        {"role": "user", "content": scrub_task_handles(user)},
        {"role": "assistant", "content": scrub_task_handles(assistant)},
    ]


def _is_standing_or_meta_user_content(content: str) -> bool:
    """User lines that are not a new step vignette (day header, clock dump, …)."""
    if content.startswith("=== ") and " ===" in content:
        return True
    if content.startswith("==="):
        return True
    if "Regular tasks for every day" in content:
        return True
    if content.startswith("Heartbeat"):
        return True
    if content.startswith("State ["):
        return True
    if content.startswith("Time:"):
        return True
    if MEMORY_MARKER in content:
        return True
    if content.startswith("[system]"):
        return True
    return False


def current_step_start_index(messages: list[dict]) -> int:
    """Index of the current vignette (last non-meta user scene).

    Clock / State dumps after this index belong to *this* step. Earlier
    ``Time:`` / ``State [clock]`` lines are previous steps and must not be
    treated as the current clock.
    """
    step_start = 0
    found = False
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        if _is_standing_or_meta_user_content(content):
            continue
        step_start = i
        found = True
    return step_start if found else 0


def extract_step_clock(messages: list[dict]) -> str:
    """Trusted HH:MM from the current step only (vignette + in-step replies)."""
    start = current_step_start_index(messages)
    time_str = ""
    for msg in messages[start:]:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or MEMORY_MARKER in content:
            continue
        got = extract_time_str(content)
        if got:
            time_str = got
    return time_str


def compact_day_header(content: str, *, include_plan: bool = True) -> str:
    """Optionally drop the morning list; keep ``=== Monday ===`` so weekday is known.

    The loose plan is seeded into the intention store on first recall of the
    day. Leaving the original when-clauses in the choose prompt competes with
    later reschedule/override rows.
    """
    if include_plan or not content:
        return content
    first = content.splitlines()[0].strip()
    if first.startswith("=== ") and " ===" in first:
        return first
    return content


def build_compact_messages(
    messages: list[dict], *, include_day_plan: bool = True
) -> list[dict]:
    """Keep only system + standing instructions + current day/step context.

    Full-week chat history is dropped so the model must rely on injected
    memories for cross-step / cross-day intentions.
    """
    if not messages:
        return []

    system: list[dict] = []
    daily: dict | None = None
    day_header: dict | None = None

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        if role == "system":
            system.append({"role": "system", "content": content})
            continue
        if role != "user":
            continue
        if content.startswith("=== ") and " ===" in content:
            day_header = {
                "role": "user",
                "content": compact_day_header(
                    content, include_plan=include_day_plan
                ),
            }
            continue
        # Standing weekly instructions (printed once at run start).
        if daily is None and "Regular tasks for every day" in content:
            daily = {"role": "user", "content": content}

    step_start = current_step_start_index(messages)

    compact: list[dict] = []
    compact.extend(system)
    if daily is not None:
        compact.append(daily)
    if day_header is not None:
        compact.append(day_header)

    # Current step: vignette through any in-step queries / repairs.
    for msg in messages[step_start:]:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and MEMORY_MARKER in content:
            continue
        compact.append({"role": msg.get("role"), "content": content})

    # Fallback: at least system + last user message.
    if len(compact) <= len(system):
        for msg in reversed(messages):
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                if MEMORY_MARKER not in msg["content"]:
                    compact.append({"role": "user", "content": msg["content"]})
                    break
    return compact
