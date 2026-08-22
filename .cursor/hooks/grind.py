#!/usr/bin/env python3
"""Cursor stop-hook grind loop with autonomous scratchpad updates.

This hook is designed for long-running unattended project work:
- continue while STATUS is in_progress
- synthesize recent failures from the active workspace terminal
- auto-backfill scratchpad memory fields when they are placeholders
- append lightweight run-memory entries for later review
- archive + reset scratchpad when STATUS is DONE
- warn when the same error repeats across loops (anti-spin)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRATCHPAD = Path(".cursor/scratchpad.md")
TEMPLATE = Path(".cursor/scratchpad.template.md")
ENABLED_FILE = Path(".cursor/grind.enabled")
RUN_MEMORY_DIR = Path(".cursor/run-memory")
TRUE_VALUES = {"on", "true", "1", "yes", "enabled"}
FALSE_VALUES = {"off", "false", "0", "no", "disabled"}
CURSOR_PROJECTS = Path.home() / ".cursor" / "projects"
WORKSPACE_ROOT = Path.cwd().resolve()
LOOP_LIMIT = 20
SPIN_WINDOW = 3
DONE_MARKERS = ("STATUS: DONE", "STATUS:DONE")
ACTIVE_MARKERS = ("STATUS: IN_PROGRESS", "STATUS:IN_PROGRESS")
PLACEHOLDERS = {
    "（空）",
    "(空)",
    "（当前正在推进的唯一下一步）",
    "（最近一次关键报错或失败现象）",
    "（当前对原因的判断）",
    "（日志 / 测试 / 文件路径）",
    "（这轮准备怎么改）",
    "（已证伪的方法、不要再试的路）",
    "（最近跑了什么验证）",
    "（pass / fail + 摘要）",
    "（下一次准备跑什么）",
}
ERROR_HINTS = (
    "traceback",
    "error",
    "exception",
    "failed",
    "failure",
    "path_invalid",
    "timed out",
    "timeout",
    "denied",
    "refused",
    "connectionreseterror",
)
NOISY_HINTS = (
    "timeout_millis",
    "add-content",
    "ps-script-",
    "node_modules",
    "://",
)
NEGATED_ERROR_HINTS = (
    "no failure",
    "no error",
    "without error",
    "everything ok",
    "all good",
    "success",
)
LEARNING_RULES = (
    (
        ("path_invalid", "readable directory", "no such file", "not found"),
        "不要在路径、快照源或工作目录未确认存在前反复重跑；先验证真实目录与输入源。",
    ),
    (
        ("timeout", "timed out"),
        "不要在未缩小范围前直接整套重跑长耗时验证；先定位阻塞点或最小复现。",
    ),
    (
        ("connectionreseterror", "refused", "denied"),
        "不要在依赖服务、网络或权限前提未确认前盲目重试；先检查外部条件。",
    ),
    (
        ("importerror", "modulenotfounderror", "no module named"),
        "不要在依赖未安装或环境未准备好时继续推进功能层修复；先处理环境前置条件。",
    ),
    (
        ("rate limit", "ratelimit", "insufficient_quota", "429"),
        "不要在额度/限流未恢复时重跑完整周 LLM；先换小验证或等用户确认。",
    ),
)


def _grind_enabled() -> bool:
    """Master switch in `.cursor/grind.enabled`. Missing or `off` → no follow-up."""
    if not ENABLED_FILE.is_file():
        return False
    try:
        text = ENABLED_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        token = line.split()[0].lower()
        if token in TRUE_VALUES:
            return True
        if token in FALSE_VALUES:
            return False
        return False
    return False


def _payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalized(text: str) -> str:
    return text.upper().replace("\r\n", "\n")


def _extract_section(text: str, heading: str) -> str:
    pattern = rf"(?ms)^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text)
    if not match:
        return ""
    return match.group(1).strip()


def _replace_section(text: str, heading: str, new_body: str) -> str:
    pattern = rf"(?ms)^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text)
    if not match:
        return text
    tail = text[match.end(1) :]
    if tail and not tail.startswith("\n"):
        tail = "\n" + tail
    return text[: match.start(1)] + "\n" + new_body.strip() + "\n" + tail


def _section_contains_any_of(text: str, needles: tuple[str, ...] | set[str]) -> bool:
    lowered = _normalized(text)
    for needle in needles:
        if needle and _normalized(needle) in lowered:
            return True
    return False


def _is_placeholder_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped in PLACEHOLDERS:
        return True
    if ":" in stripped:
        _, right = stripped.split(":", 1)
        return right.strip() in PLACEHOLDERS
    return False


def _one_liner(block: str, fallback: str) -> str:
    if not block:
        return fallback
    lines: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if _is_placeholder_line(line):
            continue
        line = re.sub(r"^[-*]\s*", "", line)
        if ":" in line:
            left, right = line.split(":", 1)
            line = f"{left.strip()}: {right.strip()}"
        lines.append(line)
    if not lines:
        return fallback
    merged = "；".join(lines[:3])
    return merged[:280]


def _first_unchecked_checklist(text: str) -> str:
    block = _extract_section(text, "Checklist")
    for raw in block.splitlines():
        line = raw.strip()
        if line.startswith("- [ ]"):
            return line.replace("- [ ]", "", 1).strip()
    return ""


def _terminal_candidates() -> list[Path]:
    if not CURSOR_PROJECTS.is_dir():
        return []
    workspace_key = str(WORKSPACE_ROOT).replace(":", "").replace("\\", "-").replace("/", "-")
    direct_dir = CURSOR_PROJECTS / workspace_key / "terminals"
    if direct_dir.is_dir():
        roots = [direct_dir]
    else:
        roots = []
        try:
            for candidate in CURSOR_PROJECTS.glob("*/terminals"):
                if candidate.parent.name.endswith(workspace_key):
                    roots.append(candidate)
        except OSError:
            return []
    if not roots:
        return []
    try:
        files: list[Path] = []
        for root in roots:
            files.extend(root.glob("*.txt"))
        files = sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return files[:8]


def _terminal_meta(path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:16]
    except OSError:
        return meta
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip()
    return meta


def _is_active_terminal(path: Path) -> bool:
    meta = _terminal_meta(path)
    active_command = meta.get("active_command", "")
    return bool(active_command and active_command.lower() != "none")


def _scan_terminal_error(path: Path) -> tuple[str, int]:
    best = ""
    best_score = -1
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "", -1
    body = [line.strip() for line in lines if line.strip() and not line.startswith("---")]
    tail = body[-80:]
    for idx in range(len(tail) - 1, -1, -1):
        line = tail[idx]
        lowered = line.lower()
        if any(token in lowered for token in ERROR_HINTS):
            if any(token in lowered for token in NOISY_HINTS):
                continue
            if any(token in lowered for token in NEGATED_ERROR_HINTS):
                continue
            chosen = line
            if "traceback" in lowered and idx + 1 < len(tail):
                next_line = tail[idx + 1].strip()
                next_lowered = next_line.lower()
                if next_line and not any(token in next_lowered for token in NOISY_HINTS):
                    chosen = f"{line} -> {next_line}"
            score = sum(token in lowered for token in ERROR_HINTS)
            if "traceback" in lowered or "error" in lowered or "exception" in lowered:
                score += 2
            if len(line) < 24:
                score -= 1
            if line.count("(") > 2 and "error" not in lowered and "exception" not in lowered:
                score -= 2
            if score > best_score:
                best = chosen[:280]
                best_score = score
    return best, best_score


def _terminal_state() -> dict[str, object]:
    candidates = _terminal_candidates()
    active = [path for path in candidates if _is_active_terminal(path)]
    fallback = [path for path in candidates if path not in active]
    best = {
        "hint": "",
        "score": -1,
        "source": "",
        "path": None,
        "active_command": "",
        "last_command": "",
        "last_exit_code": "",
    }
    for source_name, bucket in (("active terminal", active), ("recent terminal log", fallback)):
        local_best = dict(best)
        for path in bucket:
            hint, score = _scan_terminal_error(path)
            meta = _terminal_meta(path)
            if score > int(local_best["score"]):
                local_best = {
                    "hint": hint,
                    "score": score,
                    "source": source_name,
                    "path": path,
                    "active_command": meta.get("active_command", ""),
                    "last_command": meta.get("last_command", ""),
                    "last_exit_code": meta.get("last_exit_code", ""),
                }
        if local_best["hint"]:
            return local_best
    return best


def _last_failure_is_placeholder(text: str) -> bool:
    return _section_contains_any_of(text, tuple(PLACEHOLDERS))


def _derive_learning(error_hint: str) -> str:
    lowered = error_hint.lower()
    for tokens, advice in LEARNING_RULES:
        if any(token in lowered for token in tokens):
            return advice
    return ""


def _derive_next_step(error_hint: str, unchecked: str) -> str:
    if unchecked:
        return unchecked
    if not error_hint:
        return "从 Checklist 中选择最关键的一项继续推进"
    return f"围绕“{error_hint[:120]}”定位最小可复现路径，并做一次最小修复后重跑验证"


def _derive_validation(terminal: dict[str, object], error_hint: str) -> tuple[str, str, str]:
    run_cmd = str(terminal.get("active_command") or terminal.get("last_command") or "").strip()
    last_check = run_cmd or "最近终端里能观察到的主验证命令"
    exit_code = str(terminal.get("last_exit_code") or "").strip()
    if error_hint:
        result = f"fail · {error_hint}"
        next_check = "修复当前失败后，先跑最小相关验证，再决定是否全量重跑"
    elif exit_code == "0":
        result = "pass · 最近扫描到的终端未出现高信号错误"
        next_check = "继续下一项 Checklist，并在完成后运行最相关验证"
    else:
        result = "pending · 暂未从终端提取到高质量错误摘要"
        next_check = "继续当前步骤，完成改动后运行最相关验证并回写结果"
    return last_check, result, next_check


def _append_learning(text: str, learning: str) -> str:
    if not learning:
        return text
    block = _extract_section(text, "Learnings / Do Not Repeat")
    if learning in block:
        return text
    lines = [line for line in block.splitlines() if not _is_placeholder_line(line)]
    lines.append(f"- {learning}")
    return _replace_section(text, "Learnings / Do Not Repeat", "\n".join(lines))


def _auto_update_scratchpad(text: str, terminal: dict[str, object]) -> tuple[str, dict[str, str]]:
    hint = str(terminal.get("hint") or "").strip()
    path = terminal.get("path")
    unchecked = _first_unchecked_checklist(text)
    current_step_block = _extract_section(text, "Current Step")
    last_failure_block = _extract_section(text, "Last Failure")
    validation_block = _extract_section(text, "Validation")

    if hint and _last_failure_is_placeholder(last_failure_block):
        evidence_file = path.name if isinstance(path, Path) else "recent terminal log"
        text = _replace_section(
            text,
            "Last Failure",
            "\n".join(
                [
                    f"- Error / symptom: {hint}",
                    "- Root-cause guess: （根据错误信息推断；本轮先做最小可验证修复）",
                    f"- Evidence: {evidence_file}",
                    "- Fix attempt: （下一轮按最小修复假设改代码/重跑验证；把结果写到 Validation）",
                ]
            ),
        )

    if _last_failure_is_placeholder(current_step_block) or not _one_liner(current_step_block, ""):
        text = _replace_section(
            text,
            "Current Step",
            _derive_next_step(hint, unchecked) or "从 Checklist 中选择最关键的一项继续推进",
        )

    last_check, result, next_check = _derive_validation(terminal, hint)
    if _last_failure_is_placeholder(validation_block) or True:
        text = _replace_section(
            text,
            "Validation",
            "\n".join(
                [
                    f"- Last check run: {last_check}",
                    f"- Result: {result}",
                    f"- Next check: {next_check}",
                ]
            ),
        )

    learning = _derive_learning(hint)
    text = _append_learning(text, learning)

    return text, {
        "last_check": last_check,
        "result": result,
        "next_check": next_check,
        "auto_learning": learning,
    }


def _idle_template() -> str:
    if TEMPLATE.is_file():
        try:
            return TEMPLATE.read_text(encoding="utf-8")
        except OSError:
            pass
    return (
        "# Scratchpad\n\nSTATUS: idle\n\n"
        "仅当 `.cursor/grind.enabled` 为 `on` 时才使用本文件。\n"
        "多步实现任务开始时，把 STATUS 改成 `in_progress` 并填写下面各节。\n"
        "全部完成后改成 `DONE`。开关为 `off` 或普通问答保持 `idle`，stop hook 不会自动续跑。\n\n"
        "## Goal\n\n（空）\n\n## Checklist\n\n- [ ]\n\n"
        "## Current Step\n\n（当前正在推进的唯一下一步）\n\n"
        "## Last Failure\n\n"
        "- Error / symptom: （最近一次关键报错或失败现象）\n"
        "- Root-cause guess: （当前对原因的判断）\n"
        "- Evidence: （日志 / 测试 / 文件路径）\n"
        "- Fix attempt: （这轮准备怎么改）\n\n"
        "## Learnings / Do Not Repeat\n\n- （已证伪的方法、不要再试的路）\n\n"
        "## Validation\n\n"
        "- Last check run: （最近跑了什么验证）\n"
        "- Result: （pass / fail + 摘要）\n"
        "- Next check: （下一次准备跑什么）\n\n"
        "## Notes\n\n（空）\n"
    )


def _archive_and_reset(raw_text: str) -> Path | None:
    """Keep the finished task, then restore the idle template so the next task is clean."""
    archive: Path | None = None
    try:
        RUN_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        archive = RUN_MEMORY_DIR / f"{stamp}-scratchpad-done.md"
        archive.write_text(raw_text, encoding="utf-8")
    except OSError:
        archive = None
    try:
        SCRATCHPAD.write_text(_idle_template(), encoding="utf-8")
    except OSError:
        pass
    return archive


def _hint_key(hint: str) -> str:
    text = re.sub(r"\s+", " ", (hint or "").strip().lower())
    return text[:80]


def _spin_warning(current_hint: str) -> str:
    """If the same terminal error repeats, tell the agent to shrink scope instead of retrying."""
    key = _hint_key(current_hint)
    if not key:
        return ""
    keys = [key]
    try:
        files = sorted(
            RUN_MEMORY_DIR.glob("*-loop-*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[: SPIN_WINDOW - 1]
    except OSError:
        files = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        prev = _hint_key(str((data.get("terminal") or {}).get("hint") or ""))
        if prev:
            keys.append(prev)
    if len(keys) < SPIN_WINDOW:
        return ""
    if len(set(keys[:SPIN_WINDOW])) != 1:
        return ""
    return (
        f"\n- 防空转：最近 {SPIN_WINDOW} 轮是同一类错误。缩小复现范围，不要重复同一修复；"
        "若仍无进展，把 STATUS 改成 DONE，并在 Notes 写清需要人判断的点。"
        "不要为此去跑完整周 LLM。"
    )


def _write_run_memory(
    *,
    payload: dict,
    terminal: dict[str, object],
    scratchpad_text: str,
    loop_count: int,
) -> Path | None:
    try:
        RUN_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    path = RUN_MEMORY_DIR / f"{stamp}-loop-{loop_count + 1:02d}.json"
    data = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "loop_count": loop_count,
        "hook_status": payload.get("status"),
        "workspace": str(WORKSPACE_ROOT),
        "terminal": {
            "source": terminal.get("source"),
            "hint": terminal.get("hint"),
            "active_command": terminal.get("active_command"),
            "last_command": terminal.get("last_command"),
            "last_exit_code": terminal.get("last_exit_code"),
            "path": str(terminal.get("path")) if terminal.get("path") else None,
        },
        "scratchpad": {
            "goal": _extract_section(scratchpad_text, "Goal"),
            "current_step": _extract_section(scratchpad_text, "Current Step"),
            "last_failure": _extract_section(scratchpad_text, "Last Failure"),
            "learnings": _extract_section(scratchpad_text, "Learnings / Do Not Repeat"),
            "validation": _extract_section(scratchpad_text, "Validation"),
        },
    }
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return None
    return path


def main() -> None:
    payload = _payload()
    status = str(payload.get("status") or "")
    loop_count = int(payload.get("loop_count") or 0)

    if status == "aborted":
        print("{}")
        return
    if not _grind_enabled():
        print("{}")
        return
    if not SCRATCHPAD.is_file():
        print("{}")
        return

    raw_text = SCRATCHPAD.read_text(encoding="utf-8", errors="replace")
    normalized = _normalized(raw_text)
    if any(marker in normalized for marker in DONE_MARKERS):
        _archive_and_reset(raw_text)
        print("{}")
        return
    if not any(marker in normalized for marker in ACTIVE_MARKERS):
        print("{}")
        return

    terminal = _terminal_state()
    updated_text, auto = _auto_update_scratchpad(raw_text, terminal)
    if updated_text != raw_text:
        SCRATCHPAD.write_text(updated_text, encoding="utf-8", errors="replace")
    refreshed = SCRATCHPAD.read_text(encoding="utf-8", errors="replace")

    nxt = loop_count + 1
    current_step = _one_liner(
        _extract_section(refreshed, "Current Step"),
        "从 Checklist 中选择最关键的一项继续推进",
    )
    last_failure = _one_liner(
        _extract_section(refreshed, "Last Failure"),
        "目前还没有写下最近一次失败，请先补上关键报错、证据和修复假设",
    )
    validation = _one_liner(
        _extract_section(refreshed, "Validation"),
        "做完修改后运行最相关的验证，并把结果写回 scratchpad",
    )
    learning = _one_liner(_extract_section(refreshed, "Learnings / Do Not Repeat"), "")
    run_memory = _write_run_memory(
        payload=payload,
        terminal=terminal,
        scratchpad_text=refreshed,
        loop_count=loop_count,
    )
    spin = _spin_warning(str(terminal.get("hint") or ""))

    source = (
        "scratchpad.Last Failure"
        if not _last_failure_is_placeholder(_extract_section(raw_text, "Last Failure"))
        else str(terminal.get("source") or "manual backfill needed")
    )
    near_limit = ""
    if nxt >= LOOP_LIMIT:
        near_limit = (
            "\n- 已达到 loop_limit。保持现状等待用户下一轮；"
            "不要为了续跑去跑完整周 LLM。"
        )
    message = (
        f"[Grind {nxt}/{LOOP_LIMIT}] 任务未完成：`.cursor/scratchpad.md` 仍是 "
        "STATUS: in_progress（没有 STATUS: DONE）。"
        "先复盘最近一次失败，再继续执行当前步骤，不要询问用户是否继续。"
        f"\n- 先复盘失败：{last_failure}"
        f"\n- 失败来源：{source}"
        f"\n- 当前步骤：{current_step}"
        f"\n- 最近验证：{validation}"
        f"\n- 当前负知识：{learning or '暂未形成新负知识；若本轮证伪某方法，请写回 Learnings / Do Not Repeat'}"
        f"\n- Run memory：{run_memory.as_posix() if run_memory else '.cursor/run-memory/ 写入失败，可忽略'}"
        f"{spin}"
        f"{near_limit}"
        "\n- 继续时优先采用最小修复 + 最小验证；若失败模式改变，回写 scratchpad 并推进 Checklist。"
        "\n- 未要求时不要跑完整周 LLM 实验。"
        "\n- 全部达成后把 STATUS 改成 DONE（hook 会归档 scratchpad 并重置为 idle）。"
    )
    print(json.dumps({"followup_message": message}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        main()
    except Exception as exc:  # pragma: no cover - fail open
        print(f"[grind] {exc}", file=sys.stderr)
        print("{}")
