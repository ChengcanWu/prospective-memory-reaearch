#!/usr/bin/env python3
"""
CLI: run PM-Bench with baseline / A-Mem / Mem0 / intention.

API key / base_url / model are loaded from repo-root `.env` (see `.env.example`).
CLI flags override the file. Swap models without editing Python:

  python code/run_pm_memory.py --list-providers
  python code/run_pm_memory.py --provider deepseek --setup intention
  python code/run_pm_memory.py --provider qwen --model qwen3.5-397b --setup baseline
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
PMBENCH = ROOT / "data" / "PMBench"
RUNS = PMBENCH / "runs"
THIRD = ROOT / "third_party"

for p in (str(CODE), str(THIRD / "mem0-main"), str(PMBENCH / "sim")):
    if p not in sys.path:
        sys.path.insert(0, p)

from llm_env import format_provider_list, load_dotenv_files, resolve_llm


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PM-Bench × A-Mem / Mem0 runner")
    p.add_argument(
        "--provider",
        default=None,
        help="LLM vendor name (qwen, deepseek, or any NAME_* in .env). "
        "Falls back to DEFAULT_PROVIDER.",
    )
    p.add_argument(
        "--list-providers",
        action="store_true",
        help="Print configured providers from .env and exit.",
    )
    p.add_argument(
        "--setup",
        choices=["baseline", "amem", "mem0", "intention"],
        default=None,
        help="intention = structured prospective intention store "
        "(pending/time/event/channel filters; not Mem0/A-Mem). "
        "Required unless --list-providers.",
    )
    p.add_argument("--model", default=None, help="Override <PROVIDER>_MODEL from .env")
    p.add_argument("--base-url", default=None, help="Override <PROVIDER>_BASE_URL from .env")
    p.add_argument("--api-key", default=None, help="Override <PROVIDER>_API_KEY from .env")
    p.add_argument(
        "--response-format",
        default=None,
        choices=["json_schema", "json_object", "none"],
        help="Override <PROVIDER>_RESPONSE_FORMAT (default: json_schema for qwen, "
        "json_object otherwise).",
    )
    p.add_argument("--out-dir", default=None)
    p.add_argument("--scenario", default=str(PMBENCH / "data" / "synthetic_week_v9.json"))
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Memory retrieve top-k (A-Mem: paper hits + ≤k link neighbors each)",
    )
    p.add_argument(
        "--max-inject-chars",
        type=int,
        default=8000,
        help="Safety cap on injected memory text (paper A-Mem includes context/keywords/tags)",
    )
    p.add_argument(
        "--amem-max-note-chars",
        type=int,
        default=280,
        help="Deprecated no-op (kept for CLI compat); paper recall no longer truncates per note",
    )
    p.add_argument("--evo-threshold", type=int, default=100, help="A-Mem consolidate threshold")
    p.add_argument("--no-amem-keyword-query", action="store_true")
    p.add_argument("--no-score", action="store_true")
    p.add_argument(
        "--use-qwen-embed",
        action="store_true",
        help="Mem0: use Aliyun Qwen embedding endpoint (env-overridable).",
    )
    p.add_argument(
        "--keep-full-history",
        action="store_true",
        help="Memory setups: also send full-week chat history (legacy). "
        "Default is current-step context + retrieved memories only.",
    )
    p.add_argument(
        "--no-intention-llm-update",
        action="store_true",
        help="Intention setup: disable LLM Scene Judge revisions; "
        "there is no keyword fallback.",
    )
    p.add_argument(
        "--no-intention-llm-channel-expiry",
        action="store_true",
        help="Deprecated no-op; channel observations are no longer stored.",
    )
    p.add_argument(
        "--no-intention-llm-extract",
        action="store_true",
        help="Intention setup: disable LLM vignette split/extract; use "
        "regex only (On <Day> first sentence + plan bullets).",
    )
    p.add_argument(
        "--no-intention-llm-match",
        action="store_true",
        help="Intention setup: disable Scene Judge due labels; inject all today "
        "pending (event/channel not filtered). Default is on.",
    )
    p.add_argument(
        "--no-force-check-time",
        action="store_true",
        help="Intention setup: do not override choose→check_time when clock is "
        "unknown but pending time intentions exist.",
    )
    return p.parse_args()


def _safe_model(model: str) -> str:
    return model.replace("/", "-").replace(":", "-").replace(" ", "-")


def _prepare_qwen_embed_env() -> None:
    """Require MEM0_EMBED_API_KEY from .env; only fill non-secret defaults."""
    if not os.environ.get("MEM0_EMBED_API_KEY"):
        raise SystemExit(
            "Mem0 Qwen embedding needs MEM0_EMBED_API_KEY in .env "
            "(see .env.example; also MEM0_EMBED_BASE_URL / MEM0_EMBED_MODEL)."
        )
    os.environ.setdefault(
        "MEM0_EMBED_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    os.environ.setdefault("MEM0_EMBED_MODEL", "text-embedding-v3")
    os.environ.setdefault("MEM0_EMBED_DIMS", "1536")


def main() -> int:
    load_dotenv_files()
    args = parse_args()
    if args.list_providers:
        print(format_provider_list())
        return 0
    if not args.setup:
        raise SystemExit("Missing --setup (baseline | amem | mem0 | intention).")

    provider = args.provider or os.environ.get("DEFAULT_PROVIDER")
    cfg = resolve_llm(
        provider,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        response_format=args.response_format,
        out_dir=args.out_dir,
        runs_dir=RUNS,
    )
    model = cfg["model"]
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    out_dir = cfg["out_dir"]
    response_format = cfg["response_format"]
    args.provider = cfg["name"]

    import pm_bench as PM_BENCH

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_prefix = {
        "baseline": "single-baseline",
        "amem": "amem",
        "mem0": "mem0",
        "intention": "intention",
    }[args.setup]
    run_name = f"{run_prefix}-{_safe_model(model)}-v9-{timestamp}"
    run_dir = Path(out_dir) / _safe_model(model) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"provider={cfg['label']} model={model} setup={args.setup}")
    print(f"out={run_dir}")

    session_cm = None
    if args.setup == "amem":
        from pm_memory.amem import build_amem_backend
        from pm_memory.session import MemorySession, install_memory_session

        backend = build_amem_backend(
            model=model,
            api_key=api_key,
            base_url=base_url,
            top_k=args.top_k,
            evo_threshold=args.evo_threshold,
            use_keyword_query=not args.no_amem_keyword_query,
            max_inject_chars=args.max_inject_chars,
        )
        session = MemorySession(
            backend,
            top_k=args.top_k,
            log_path=str(run_dir / f"{run_name}.memory.jsonl"),
            keep_full_history=args.keep_full_history,
        )
        session_cm = install_memory_session(PM_BENCH, session)
    elif args.setup == "mem0":
        from pm_memory.mem0_backend import build_mem0_backend
        from pm_memory.session import MemorySession, install_memory_session

        # DeepSeek's OpenAI-compatible gateway is not a reliable embedder for
        # Mem0 (and fact extraction often returns []). Prefer the known-good
        # Qwen embedding endpoint unless the caller already set MEM0_EMBED_*.
        auto_qwen_embed = args.provider == "deepseek" and not os.environ.get("MEM0_EMBED_BASE_URL")
        if (
            args.use_qwen_embed
            or auto_qwen_embed
            or os.environ.get("MEM0_USE_QWEN_EMBED", "").lower() in ("1", "true", "yes")
        ):
            _prepare_qwen_embed_env()
        backend = build_mem0_backend(
            provider_key=args.provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            out_dir=out_dir,
            user_id=f"{args.provider}_mem0",
            top_k=args.top_k,
            max_inject_chars=args.max_inject_chars,
        )
        session = MemorySession(
            backend,
            top_k=args.top_k,
            log_path=str(run_dir / f"{run_name}.memory.jsonl"),
            keep_full_history=args.keep_full_history,
        )
        session_cm = install_memory_session(PM_BENCH, session)
    elif args.setup == "intention":
        from pm_memory.intention_store import build_intention_backend
        from pm_memory.session import MemorySession, install_memory_session

        backend = build_intention_backend(
            store_path=str(run_dir / f"{run_name}.intentions.json"),
            max_inject_chars=args.max_inject_chars,
            model=model,
            api_key=api_key,
            base_url=base_url,
            use_llm_update=not args.no_intention_llm_update,
            use_llm_extract=not args.no_intention_llm_extract,
            use_llm_match=not args.no_intention_llm_match,
        )
        print(
            "intention_llm_update="
            + ("on" if getattr(backend, "use_llm_update", False) else "off")
            + " intention_llm_extract="
            + ("on" if getattr(backend, "use_llm_extract", False) else "off")
            + " intention_llm_done="
            + ("on" if getattr(backend, "use_llm_done", False) else "off")
            + " intention_llm_match="
            + ("on" if getattr(backend, "use_llm_match", False) else "off")
            + " force_check_time="
            + ("on" if not args.no_force_check_time else "off")
        )
        session = MemorySession(
            backend,
            top_k=args.top_k,
            log_path=str(run_dir / f"{run_name}.memory.jsonl"),
            keep_full_history=args.keep_full_history,
            force_check_time=not args.no_force_check_time,
        )
        session_cm = install_memory_session(PM_BENCH, session)

    scenario = PM_BENCH.load_scenario(args.scenario)
    log_path = str(run_dir / f"{run_name}.jsonl")
    prompt_log = str(run_dir / f"{run_name}.prompt.txt")

    def _run():
        return PM_BENCH.run_llm(
            scenario,
            log_path=log_path,
            model=model,
            env_path=None,
            max_time_requests=5,
            backend="sglang",
            base_url=base_url,
            api_key=api_key,
            out_dir=None,
            max_tokens=args.max_tokens,
            response_format_mode=response_format,
            prompt_log_path=prompt_log,
        )

    if session_cm is not None:
        with session_cm:
            log_entries = _run()
    else:
        log_entries = _run()

    if not args.no_score:
        entries, meta = PM_BENCH.read_log_with_metadata(log_path)
        if not entries:
            entries = log_entries
        summary, per_day, summary_steps = PM_BENCH.score_log(scenario, entries)
        PM_BENCH.print_report(summary, per_day, summary_steps, run_metadata=meta)
        report = PM_BENCH.build_markdown_report(
            summary, per_day, summary_steps, run_metadata=meta
        )
        score_path = str(run_dir / f"{run_name}.score.md")
        Path(score_path).write_text(report, encoding="utf-8")
        print(f"Wrote score report: {score_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
