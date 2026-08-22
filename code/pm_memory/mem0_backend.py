"""
Mem0 backend — only the OSS Memory core write/read path.

Upstream: mem0ai/mem0 `Memory`

Write  = add(messages, user_id=..., infer=True)
         (v3: ADD-only fact extraction, hash dedup, embed, entity link)
         If extraction returns nothing / errors: skip write (no infer=False dump).
Read   = search(query, filters={user_id: ...}, top_k=...)
         (semantic + BM25 keyword + entity boost fusion in OSS)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import format_turn_messages, scrub_task_handles, truncate


class Mem0Backend:
    name = "mem0"

    def __init__(
        self,
        memory,
        *,
        user_id: str,
        top_k: int = 10,
        max_inject_chars: int = 8000,
    ):
        self.memory = memory
        self.user_id = user_id
        self.top_k = top_k
        self.max_inject_chars = max_inject_chars
        self.last_encode_info: dict[str, Any] = {}

    def recall(self, query: str, *, top_k: int | None = None) -> str:
        if not query:
            return ""
        k = int(top_k or self.top_k)
        response = self.memory.search(
            query=query,
            filters={"user_id": self.user_id},
            top_k=k,
            # PM vignettes often share little lexical overlap with extracted
            # facts; keep a low threshold so empty-store is the only miss mode.
            threshold=0.0,
        )
        items = response.get("results", []) if isinstance(response, dict) else (response or [])
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = item.get("memory") or item.get("data") or item.get("content")
            if text:
                cleaned = scrub_task_handles(str(text))
                if cleaned:
                    lines.append(f"- {cleaned}")
        return truncate("\n".join(lines), self.max_inject_chars)

    def encode(self, turn: dict[str, Any]) -> None:
        messages = format_turn_messages(turn)
        metadata = {
            "day": turn.get("day"),
            "step": turn.get("step"),
            "time": turn.get("time"),
        }
        # Prefer LLM fact extraction only. Do NOT fall back to infer=False raw
        # message dumps: those pollute recall with "PM deferred-intention note
        # [...]" blobs and hurt PM decision quality more than a missed write.
        try:
            response = self.memory.add(
                messages,
                user_id=self.user_id,
                metadata=metadata,
                infer=True,
            )
        except Exception as exc:
            self.last_encode_info = {
                "mode": "infer_error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:200],
            }
            raise

        if _add_wrote_nothing(response):
            self.last_encode_info = {"mode": "infer_empty", "results": 0}
            return

        n = 0
        if isinstance(response, dict):
            n = len(response.get("results") or [])
        elif isinstance(response, list):
            n = len(response)
        self.last_encode_info = {"mode": "infer_ok", "results": n}


def _add_wrote_nothing(response: Any) -> bool:
    if response is None:
        return True
    if isinstance(response, dict):
        results = response.get("results")
        if results is None:
            return True
        return len(results) == 0
    if isinstance(response, list):
        return len(response) == 0
    return False


def build_mem0_backend(
    *,
    provider_key: str,
    model: str,
    api_key: str,
    base_url: str,
    out_dir: str,
    user_id: str,
    top_k: int = 10,
    max_inject_chars: int = 8000,
    embed_api_key: str | None = None,
    embed_base_url: str | None = None,
    embed_model: str | None = None,
    embed_dims: int = 1536,
) -> Mem0Backend:
    """Construct official mem0.Memory.from_config(...)."""
    import os

    os.environ.setdefault("MEM0_TELEMETRY", "False")
    os.environ.setdefault("POSTHOG_DISABLED", "1")

    from mem0 import Memory

    if provider_key == "deepseek":
        os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
        llm = {
            "provider": "deepseek",
            "config": {
                "model": model,
                "api_key": api_key,
                "deepseek_base_url": base_url,
            },
        }
    else:
        llm = {
            "provider": "openai",
            "config": {
                "model": model,
                "api_key": api_key,
                "openai_base_url": base_url,
            },
        }

    # Default: reuse decision-model gateway for embeddings unless overridden.
    # For known-good Qwen embedding, set env MEM0_EMBED_* or pass args.
    e_key = embed_api_key or os.environ.get("MEM0_EMBED_API_KEY") or api_key
    e_url = embed_base_url or os.environ.get("MEM0_EMBED_BASE_URL") or base_url
    e_model = embed_model or os.environ.get("MEM0_EMBED_MODEL") or "text-embedding-3-small"
    e_dims = int(os.environ.get("MEM0_EMBED_DIMS", str(embed_dims)))

    # Fresh local Qdrant path per construction avoids cross-run payload collisions.
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    store_dir = Path(out_dir) / f"mem0_{provider_key}_{stamp}"
    store_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "llm": llm,
        "embedder": {
            "provider": "openai",
            "config": {
                "model": e_model,
                "api_key": e_key,
                "openai_base_url": e_url,
                "embedding_dims": e_dims,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": str(store_dir),
                "collection_name": "pm_bench_memories",
            },
        },
        "history_db_path": str(store_dir / "history.db"),
    }
    memory = Memory.from_config(config)
    return Mem0Backend(
        memory,
        user_id=user_id,
        top_k=top_k,
        max_inject_chars=max_inject_chars,
    )
