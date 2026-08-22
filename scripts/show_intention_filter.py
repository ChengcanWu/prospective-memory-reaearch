#!/usr/bin/env python3
"""Print time / event / channel fields and the code filter pipeline for a step.

Does not call any LLM. Prefers `filter_trace` already stored on a recall row;
otherwise rebuilds calendar + TIME-DUE from the step snapshot.

  python scripts/show_intention_filter.py
  python scripts/show_intention_filter.py --run data/PMBench/runs/intention/v4.5/deepseek-chat
  python scripts/show_intention_filter.py --day Wednesday --step s4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from pm_memory.intention_store import IntentionStoreBackend

RUNS_INTENTION = ROOT / "data" / "PMBench" / "runs" / "intention"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--run",
        default=None,
        help="Run dir, a *.intentions.steps.jsonl, or a filters.md. "
        "Default: newest intention steps.jsonl",
    )
    p.add_argument("--day", default="", help="e.g. Wednesday")
    p.add_argument("--step", default="", help="e.g. s4")
    p.add_argument(
        "--all",
        action="store_true",
        help="Print every recall row (default: last matching / last recall)",
    )
    return p.parse_args()


def _newest_steps(root: Path) -> Path | None:
    hits = sorted(
        root.rglob("*.intentions.steps.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return hits[0] if hits else None


def _resolve_steps(run: str | None) -> Path:
    if not run:
        found = _newest_steps(RUNS_INTENTION)
        if not found:
            raise SystemExit("no *.intentions.steps.jsonl under data/PMBench/runs/intention")
        return found
    path = Path(run)
    if path.is_file() and path.name.endswith(".steps.jsonl"):
        return path
    if path.is_file() and path.name.endswith(".filters.md"):
        alt = path.with_name(path.name.replace(".filters.md", ".steps.jsonl"))
        if alt.exists():
            return alt
        raise SystemExit(f"no steps jsonl next to {path}")
    if path.is_dir():
        found = _newest_steps(path)
        if not found:
            raise SystemExit(f"no *.intentions.steps.jsonl under {path}")
        return found
    raise SystemExit(f"not a run dir or steps jsonl: {path}")


def _load_recalls(steps_path: Path) -> list[dict[str, Any]]:
    rows = []
    with steps_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("event") == "recall":
                rows.append(rec)
    return rows


def _match(rec: dict[str, Any], day: str, step: str) -> bool:
    if day and str(rec.get("day") or "").lower() != day.lower():
        return False
    if step and str(rec.get("step") or "").lower() != step.lower():
        return False
    return True


def _rebuild_trace(rec: dict[str, Any]) -> dict[str, Any]:
    s = IntentionStoreBackend(use_llm_update=False, use_llm_extract=False)
    for item in rec.get("intentions") or []:
        if not isinstance(item, dict):
            continue
        intent = IntentionStoreBackend._intention_from_raw(item)
        s.intentions[intent.intent_id] = intent
    day = str(rec.get("day") or "")
    time_str = str(rec.get("time") or "")
    pending = [i for i in s.intentions.values() if i.status == "pending"]
    today = [i for i in pending if s._is_active_on_day(i, day)]
    time_hits = s._filter_time_due(today, time_str)
    needed = s._watch_needed(today, [])
    stored = rec.get("filter_trace") if isinstance(rec.get("filter_trace"), dict) else {}
    return s._build_filter_trace(
        pending=pending,
        today_pending=today,
        time_hits=time_hits,
        channel_needed=needed,
        day=day,
        step=str(rec.get("step") or ""),
        time_str=time_str,
        messages=[],
        extracted=list(stored.get("extracted") or []),
        extract_added=int(stored.get("extract_added") or 0),
    )


def _print_one(rec: dict[str, Any]) -> None:
    s = IntentionStoreBackend(use_llm_update=False, use_llm_extract=False)
    text = ""
    recall = rec.get("recall") if isinstance(rec.get("recall"), dict) else {}
    if recall.get("filter_trace_text"):
        text = str(recall["filter_trace_text"])
    elif rec.get("filter_trace"):
        text = s._format_filter_trace(rec["filter_trace"])
    else:
        text = s._format_filter_trace(_rebuild_trace(rec))
        text = (
            "（本步日志没有 filter_trace，按库存快照重建日历/TIME-DUE；"
            "extract 原始字段与本步 CHECK 已查过的 channel 可能缺失）\n\n"
            + text
        )
    print(text)


def main() -> int:
    args = _parse_args()
    steps_path = _resolve_steps(args.run)
    rows = _load_recalls(steps_path)
    if not rows:
        print(f"no recall rows in {steps_path}", file=sys.stderr)
        return 1
    picked = [r for r in rows if _match(r, args.day, args.step)]
    if not picked:
        print(
            f"no recall row for day={args.day!r} step={args.step!r} in {steps_path}",
            file=sys.stderr,
        )
        return 1
    if not args.all and not (args.day or args.step):
        picked = picked[-1:]
    elif not args.all and (args.day or args.step):
        picked = picked[-1:]
    print(f"# {steps_path}")
    print()
    for rec in picked:
        _print_one(rec)
        print()
    filters = steps_path.with_name(
        steps_path.name.replace(".steps.jsonl", ".filters.md")
    )
    if filters.exists():
        print(f"（完整逐步文本也在 {filters}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
