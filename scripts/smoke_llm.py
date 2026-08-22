"""Minimal OpenAI-compatible smoke test. Settings come from `.env` / CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from openai import OpenAI

from llm_env import load_dotenv_files, resolve_llm


def main() -> int:
    load_dotenv_files()
    p = argparse.ArgumentParser(description="Smoke-test a configured LLM provider")
    p.add_argument("--provider", default=None, help="qwen / deepseek / any NAME in .env")
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    args = p.parse_args()

    import os

    provider = args.provider or os.environ.get("DEFAULT_PROVIDER") or "qwen"
    cfg = resolve_llm(
        provider,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    response = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "user", "content": "你好"}],
    )
    print(f"[{cfg['name']}] {cfg['model']}")
    print(response.choices[0].message.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
