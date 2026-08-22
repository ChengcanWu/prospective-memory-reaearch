"""
A-Mem backend — paper write + paper recall.

Write  = paper `AgenticMemorySystem.add_note`
         (analyze → evolve/links → embed)

Read   = paper eval path:
         optional keyword expansion, then `find_related_memories_raw`
         (top-k hits + each hit's link neighbors, raw content/context/keywords/tags)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .common import format_turn_note, scrub_task_handles, truncate


class AMemBackend:
    name = "amem"

    def __init__(
        self,
        system,
        *,
        top_k: int = 5,
        use_keyword_query: bool = True,
        max_inject_chars: int = 8000,
    ):
        self.system = system
        self.top_k = top_k
        self.use_keyword_query = use_keyword_query
        self.max_inject_chars = max_inject_chars

    def recall(self, query: str, *, top_k: int | None = None) -> str:
        if not query or not self.system.memories:
            return ""
        k = int(top_k or self.top_k)
        search_q = query
        if self.use_keyword_query:
            search_q = self._keywords_from_query(query) or query
        raw = self.system.find_related_memories_raw(search_q, k=k)
        if not raw:
            return ""
        # Paper returns a flat string; keep that shape, only scrub PM handles.
        text = scrub_task_handles(str(raw)).strip()
        return truncate(text, self.max_inject_chars)

    def encode(self, turn: dict[str, Any]) -> None:
        content = format_turn_note(turn)
        if not content.strip():
            return
        time_str = f"{turn.get('day', '')} {turn.get('step', '')}".strip() or None
        self.system.add_note(content, time=time_str)

    def _keywords_from_query(self, question: str) -> str:
        """Paper eval helper: LLM expands the query into retrieval keywords."""
        prompt = f"""Given the following question, generate several keywords, using 'cosmos' as the separator.

                Question: {question}

                Format your response as a JSON object with a "keywords" field containing the selected text. 

                Example response format:
                {{"keywords": "keyword1, keyword2, keyword3"}}"""
        response = self.system.llm_controller.llm.get_completion(
            prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": {
                        "type": "object",
                        "properties": {"keywords": {"type": "string"}},
                        "required": ["keywords"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )
        try:
            return json.loads(response)["keywords"]
        except Exception:
            return (response or "").strip()


def build_amem_backend(
    *,
    model: str,
    api_key: str,
    base_url: str | None,
    top_k: int = 5,
    evo_threshold: int = 100,
    use_keyword_query: bool = True,
    max_inject_chars: int = 8000,
) -> AMemBackend:
    root = Path(__file__).resolve().parents[2] / "third_party" / "amem-paper"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from memory_layer import AgenticMemorySystem

    embed_model = os.environ.get("AMEM_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    system = AgenticMemorySystem(
        model_name=embed_model,
        llm_backend="openai",
        llm_model=model,
        evo_threshold=evo_threshold,
        api_key=api_key,
        api_base=base_url,
    )
    return AMemBackend(
        system,
        top_k=top_k,
        use_keyword_query=use_keyword_query,
        max_inject_chars=max_inject_chars,
    )
