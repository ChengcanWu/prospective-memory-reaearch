"""
PM-Bench × external memory: clean integration layer.

Design (independent of prior adapters):

  PM-Bench is a prospective-memory *decision* loop. External memory is not a
  scaffold like todo-ledger; it is a write/read store with two hooks:

    RECALL  — before each model action request, retrieve notes relevant to the
              current vignette and inject them as one user message.
    ENCODE  — after a non-query action (choose), store a compact turn that both
              A-Mem and Mem0 can ingest with their *native* write APIs.

Backends wrap only the upstream core methods:

  A-Mem (paper AgenticMemorySystem):
      add_note(content, time=...)
      find_related_memories_raw(query, k=...)
      (+ paper eval's keyword-query LLM step before retrieve)

  Mem0 (OSS Memory):
      add(messages, user_id=..., infer=True)
      search(query, filters={user_id}, top_k=...)

The runner never reimplements retrieval/evolution/extraction. It only decides
*when* to call those APIs and *how* to place results into the PM prompt.
"""

from .amem import AMemBackend
from .intention_store import (
    DueSlot,
    Intention,
    IntentionStoreBackend,
    build_intention_backend,
)
from .mem0_backend import Mem0Backend
from .session import MemorySession, install_memory_session

__all__ = [
    "AMemBackend",
    "DueSlot",
    "Intention",
    "IntentionStoreBackend",
    "Mem0Backend",
    "MemorySession",
    "build_intention_backend",
    "install_memory_session",
]
