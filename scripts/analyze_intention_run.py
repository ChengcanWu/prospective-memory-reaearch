#!/usr/bin/env python3
"""Diagnose an intention PM-Bench run and optionally slice a typed mini-scenario.

Does not call any LLM. Default is: read the newest *.score.md under
data/PMBench/runs/intention/, rank failure families, list likely missed
update / cross-day / time tasks, and optionally write a small scenario JSON
so the next check is not a full week.

Examples:

  python scripts/analyze_intention_run.py
  python scripts/analyze_intention_run.py --run data/PMBench/runs/intention/v3.0/deepseek-chat
  python scripts/analyze_intention_run.py --slice update --out data/slices/update.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PMBENCH = ROOT / "data" / "PMBench"
DEFAULT_SCENARIO = PMBENCH / "data" / "synthetic_week_v9.json"
RUNS_INTENTION = PMBENCH / "runs" / "intention"
SLICES = ROOT / "data" / "slices"

DAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

RATE_RE = re.compile(
    r"set_f1\s+([\d.]+)%|"
    r"hit\s+([\d.]+)%|"
    r"time\s+([\d.]+)%|"
    r"cross-day miss\s+([\d.]+)%|"
    r"update miss\s+([\d.]+)%|"
    r"false alarm/step\s+([\d.]+)%|"
    r"event\s+([\d.]+)%",
    re.I,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--run",
        default=None,
        help="Run directory or a specific *.score.md / *.jsonl. "
        "Default: newest intention score.md",
    )
    p.add_argument(
        "--scenario",
        default=str(DEFAULT_SCENARIO),
        help="Full-week JSON used to score / slice (default: synthetic_week_v9)",
    )
    p.add_argument(
        "--slice",
        choices=["update", "cross_day", "time", "event", "worst_day"],
        default=None,
        help="Write a mini scenario containing only days of this failure family",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output path for --slice (default: data/slices/<kind>.json)",
    )
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return p.parse_args()


def _newest_score(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    files = list(root.rglob("*.score.md"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _resolve_run(spec: str | None) -> tuple[Path | None, Path | None]:
    """Return (score.md, jsonl) paths. Either may be None."""
    if not spec:
        score = _newest_score(RUNS_INTENTION)
        if score is None:
            return None, None
        jsonl = score.with_suffix("").with_suffix(".jsonl")
        if not jsonl.is_file():
            stem = score.name.replace(".score.md", ".jsonl")
            jsonl = score.with_name(stem)
        return score, jsonl if jsonl.is_file() else None

    path = Path(spec)
    if path.is_file() and path.name.endswith(".score.md"):
        stem = path.name.replace(".score.md", ".jsonl")
        candidate = path.with_name(stem)
        return path, candidate if candidate.is_file() else None
    if path.is_file() and path.suffix == ".jsonl":
        score = path.with_name(path.name.replace(".jsonl", ".score.md"))
        return score if score.is_file() else None, path
    if path.is_dir():
        scores = list(path.glob("*.score.md")) + list(path.rglob("*.score.md"))
        if not scores:
            return None, None
        score = max(scores, key=lambda p: p.stat().st_mtime)
        stem = score.name.replace(".score.md", ".jsonl")
        jsonl = score.with_name(stem)
        return score, jsonl if jsonl.is_file() else None
    return None, None


def _sibling_artifacts(score_path: Path, jsonl_path: Path | None) -> dict[str, str | None]:
    """Locate the same-run logs needed to trace a missed task_id."""
    stem_dir = score_path.parent
    stem = score_path.name.replace(".score.md", "")

    def pick(*names: str) -> str | None:
        for name in names:
            path = stem_dir / name
            if path.is_file():
                return str(path)
        return None

    run_log = stem_dir / "run.log"
    if not run_log.is_file():
        run_log = stem_dir.parent / "run.log"
    return {
        "jsonl": str(jsonl_path) if jsonl_path and jsonl_path.is_file() else pick(f"{stem}.jsonl"),
        "steps": pick(f"{stem}.intentions.steps.jsonl"),
        "memory": pick(f"{stem}.memory.jsonl"),
        "intentions": pick(f"{stem}.intentions.json"),
        "run_log": str(run_log) if run_log.is_file() else None,
    }


def _parse_score_md(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = re.search(r"Set F1\s*\|\s*([\d.]+)%", text)
    if not m:
        m = re.search(r"set_f1\s+([\d.]+)%", text, re.I)
    if m:
        out["set_f1"] = float(m.group(1))
    m = re.search(r"Hit rate\s*\|\s*([\d.]+)%", text)
    if m:
        out["hit"] = float(m.group(1))
    m = re.search(r"Time hit rate\s*\|\s*([\d.]+)%", text)
    if not m:
        m = re.search(r"time\s+([\d.]+)%", text, re.I)
    if m:
        out["time_hit"] = float(m.group(1))
    m = re.search(r"\| Event \|.*?\| ([\d.]+)% \|", text)
    if m:
        out["event_hit"] = float(m.group(1))
    m = re.search(r"Cross-day miss rate\s*\|\s*([\d.]+)%", text)
    if m:
        out["cross_day_miss"] = float(m.group(1))
    m = re.search(r"Update miss rate\s*\|\s*([\d.]+)%", text)
    if m:
        out["update_miss"] = float(m.group(1))
    m = re.search(r"False alarm/step\s*\|\s*([\d.]+)%", text)
    if m:
        out["false_alarm"] = float(m.group(1))

    # Modality table is more reliable than the Rates one-liner.
    m = re.search(r"\| Time \(time \+ time_check\) \|.*?\| ([\d.]+)% \|", text)
    if m:
        out["time_hit"] = float(m.group(1))

    worst_day = None
    worst_miss = -1.0
    in_day = False
    for line in text.splitlines():
        if line.startswith("| Day |"):
            in_day = True
            continue
        if in_day and line.startswith("| ---"):
            continue
        if in_day and line.startswith("| "):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 7 and cells[0] in DAY_ORDER:
                miss = float(cells[6].rstrip("%"))
                if miss > worst_miss:
                    worst_miss = miss
                    worst_day = cells[0]
        elif in_day and not line.startswith("|"):
            in_day = False
    if worst_day:
        out["worst_day"] = worst_day
        out["worst_day_miss"] = worst_miss
    return out


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("day") and obj.get("step_id"):
            rows.append(obj)
    return rows


def _chosen_by_day(log: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for row in log:
        for tid in row.get("task_ids") or []:
            if tid:
                out[row["day"]].add(tid)
    return out


def _updates_in_day(day: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for step in day.get("steps") or []:
        for upd in step.get("updates") or []:
            if isinstance(upd, dict) and upd.get("task_id"):
                rec = dict(upd)
                rec["_step_id"] = step.get("id")
                rec["_step_text"] = (step.get("text") or "")[:180]
                rec["_day"] = day.get("name")
                found.append(rec)
    return found


def _diagnose(
    scenario: dict[str, Any], log: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    chosen = _chosen_by_day(log)
    all_chosen: set[str] = set()
    for ids in chosen.values():
        all_chosen |= ids

    update_miss: list[dict[str, Any]] = []
    cross_miss: list[dict[str, Any]] = []
    time_candidates: list[dict[str, Any]] = []

    for day in scenario.get("days") or []:
        name = day.get("name") or ""
        did_ids = chosen.get(name, set())
        for upd in _updates_in_day(day):
            tid = upd["task_id"]
            action = upd.get("action") or ""
            if action == "cancel":
                if tid in did_ids:
                    update_miss.append(
                        {
                            "family": "update",
                            "kind": "cancel_but_still_done",
                            "day": name,
                            "task_id": tid,
                            "step_id": upd.get("_step_id"),
                            "text": upd.get("_step_text"),
                        }
                    )
            else:
                if tid not in did_ids:
                    update_miss.append(
                        {
                            "family": "update",
                            "kind": action or "update",
                            "day": name,
                            "task_id": tid,
                            "step_id": upd.get("_step_id"),
                            "text": upd.get("_step_text"),
                        }
                    )
        for task in day.get("tasks") or []:
            tid = task.get("id") or ""
            if task.get("cross_day") and tid not in did_ids:
                cross_miss.append(
                    {
                        "family": "cross_day",
                        "day": name,
                        "task_id": tid,
                        "label": task.get("label") or task.get("action_text"),
                    }
                )
            if task.get("type") == "time" and tid not in did_ids:
                time_candidates.append(
                    {
                        "family": "time",
                        "day": name,
                        "task_id": tid,
                        "label": task.get("label"),
                        "target_time": task.get("target_time"),
                    }
                )
    return {
        "update": update_miss,
        "cross_day": cross_miss,
        "time": time_candidates,
    }


def _rank(metrics: dict[str, Any]) -> list[tuple[str, float, str]]:
    """Higher score = more urgent. Miss-style rates are used as-is; hit rates inverted."""
    ranked = []
    if "update_miss" in metrics:
        ranked.append(
            ("update", metrics["update_miss"], "Scene Judge 误杀 / 漏改")
        )
    if "cross_day_miss" in metrics:
        ranked.append(
            ("cross_day", metrics["cross_day_miss"], "跨天 due.day 与种植/注入")
        )
    if "time_hit" in metrics:
        ranked.append(("time", 100.0 - metrics["time_hit"], "时钟 / TIME-DUE / force_check_time"))
    if "event_hit" in metrics:
        ranked.append(("event", 100.0 - metrics["event_hit"], "事件线索 Scene Judge；禁止 EVENT-CUED 子串"))
    if "false_alarm" in metrics:
        ranked.append(("false_alarm", metrics["false_alarm"], "choose 误选菜单项或过期意图未 cancel"))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def _day_index(name: str) -> int | None:
    try:
        return DAY_ORDER.index(name)
    except ValueError:
        return None


def _slice_days(
    scenario: dict[str, Any],
    kind: str,
    worst_day: str | None,
    *,
    focus_days: list[str] | None = None,
) -> list[str]:
    names = [d.get("name") for d in scenario.get("days") or [] if d.get("name")]
    if kind == "worst_day":
        return [worst_day] if worst_day in names else names[:1]

    # Prefer days the run actually missed, so the slice is not a full week.
    if focus_days:
        keep = {d for d in focus_days if d in names}
        if kind == "cross_day":
            extra = set()
            for name in keep:
                idx = _day_index(name)
                if idx:
                    extra.add(DAY_ORDER[idx - 1])
            keep |= extra
        ordered = [n for n in DAY_ORDER if n in keep]
        if ordered:
            return ordered[:4]

    keep: set[str] = set()
    scored: list[tuple[int, str]] = []
    for day in scenario.get("days") or []:
        name = day.get("name") or ""
        if kind == "update":
            n = len(_updates_in_day(day))
            if n:
                scored.append((n, name))
        elif kind == "cross_day":
            if any(t.get("cross_day") for t in day.get("tasks") or []):
                keep.add(name)
                idx = _day_index(name)
                if idx:
                    keep.add(DAY_ORDER[idx - 1])
        elif kind == "time":
            n = sum(1 for t in day.get("tasks") or [] if t.get("type") == "time")
            if n:
                scored.append((n, name))
        elif kind == "event":
            n = sum(
                1
                for t in day.get("tasks") or []
                if t.get("type") == "event" and not t.get("cue_channel")
            )
            if n:
                scored.append((n, name))
    if scored:
        scored.sort(reverse=True)
        return [n for n in DAY_ORDER if n in {name for _, name in scored[:3]}]
    ordered = [n for n in DAY_ORDER if n in keep]
    return ordered or names[:2]


def _write_slice(scenario: dict[str, Any], keep_names: list[str], out: Path, kind: str) -> None:
    keep = set(keep_names)
    sliced = dict(scenario)
    sliced["days"] = [d for d in scenario.get("days") or [] if d.get("name") in keep]
    sliced["scenario_name"] = f"{scenario.get('scenario_name', 'week')}_{kind}_slice"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sliced, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    score_path, jsonl_path = _resolve_run(args.run)
    if score_path is None:
        print("No intention *.score.md found under data/PMBench/runs/intention/", file=sys.stderr)
        return 1

    metrics = _parse_score_md(score_path.read_text(encoding="utf-8"))
    ranked = _rank(metrics)
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    log = _load_jsonl(jsonl_path) if jsonl_path else []
    diag = _diagnose(scenario, log) if log else {"update": [], "cross_day": [], "time": []}

    artifacts = _sibling_artifacts(score_path, jsonl_path)
    payload = {
        "score": str(score_path),
        "jsonl": artifacts.get("jsonl"),
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "ranked": [{"family": f, "urgency": u, "hint": h} for f, u, h in ranked],
        "examples": {
            "update": diag["update"][:8],
            "cross_day": diag["cross_day"][:8],
            "time": diag["time"][:8],
        },
        "counts": {k: len(v) for k, v in diag.items()},
        "artifacts": artifacts,
    }

    slice_path = None
    if args.slice:
        focus = [
            row["day"]
            for row in diag.get(args.slice, [])
            if isinstance(row, dict) and row.get("day")
        ]
        keep = _slice_days(
            scenario,
            args.slice,
            metrics.get("worst_day"),
            focus_days=focus,
        )
        slice_path = Path(args.out) if args.out else SLICES / f"{args.slice}.json"
        _write_slice(scenario, keep, slice_path, args.slice)
        payload["slice"] = {"kind": args.slice, "days": keep, "path": str(slice_path)}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"run: {score_path}")
    if artifacts.get("jsonl"):
        print(f"log: {artifacts['jsonl']}")
    print("metrics:", ", ".join(f"{k}={v}" for k, v in metrics.items()))
    print("priority (do ONE family):")
    for i, (fam, urg, hint) in enumerate(ranked, 1):
        mark = " <-- start here" if i == 1 else ""
        print(f"  {i}. {fam:12} urgency={urg:5.1f}  {hint}{mark}")
    top = ranked[0][0] if ranked else None
    if top and diag.get(top):
        print(f"examples ({top}):")
        for row in diag[top][:5]:
            print("  -", row)
    print("artifacts (trace 2-3 examples before editing code):")
    for key in ("steps", "memory", "intentions", "run_log"):
        path = artifacts.get(key)
        if path:
            print(f"  {key}: {path}")
    print()
    print("next (no full week):")
    print("  grep the example task_id / dN_sM in steps.jsonl + memory.jsonl + run.log")
    print("  python scripts/probe_intention_store.py")
    if top:
        print(f"  python scripts/analyze_intention_run.py --slice {top}")
        print(
            "  python code/run_pm_memory.py --provider deepseek --setup intention "
            f"--scenario data/slices/{top}.json"
        )
        print("  (only run the last line if the user explicitly wants an LLM slice)")
    if slice_path:
        print(f"wrote slice: {slice_path} days={payload['slice']['days']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
