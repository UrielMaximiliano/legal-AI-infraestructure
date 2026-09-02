"""Runtime profiles for the legacy and IMI LEG API processes.

The legacy decree pipeline remains intact as a rollback path.  IMI LEG is an
isolated runtime: it uses its own re-embedded legal corpus and never queries
the legacy 4B/2560 vector store.
"""

from __future__ import annotations

from dataclasses import dataclass

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


@dataclass(frozen=True, slots=True)
class RagRuntimeProfile:
    code: str
    embedding_model: str
    embedding_dimensions: int
    embedding_storage_type: str
    embedding_context_length: int
    rag_context_length: int
    generation_model: str
    generation_context_length: int
    top_k: int
    candidate_pool_size: int
    minimum_score: float
    core_database_name: str
    rag_database_name: str


LEGACY_RAG_PROFILE = RagRuntimeProfile(
    code="legacy",
    embedding_model=EMBEDDING_MODEL,
    embedding_dimensions=EMBEDDING_DIMENSIONS,
    embedding_storage_type="halfvec(2560)",
    embedding_context_length=2048,
    rag_context_length=16_384,
    generation_model="qwen3.6:35b",
    generation_context_length=16_384,
    top_k=8,
    candidate_pool_size=24,
    minimum_score=0.0,
    core_database_name="legal_ai",
    rag_database_name="legal_ai",
)


IMI_RAG_PROFILE = RagRuntimeProfile(
    code="imi_leg_06b",
    embedding_model="qwen3-embedding:0.6b",
    embedding_dimensions=1024,
    embedding_storage_type="halfvec(1024)",
    embedding_context_length=2048,
    rag_context_length=2_048,
    generation_model="qwen3.6:35b",
    generation_context_length=16_384,
    top_k=8,
    candidate_pool_size=24,
    minimum_score=0.0,
    core_database_name="imi_leg_core",
    rag_database_name="imi_disposiciones_rag",
)


def profile_for_runtime(runtime_profile: str) -> RagRuntimeProfile:
    """Return the only supported profile for a runtime selector."""

    normalized = runtime_profile.strip().lower()
    if normalized == "legacy":
        return LEGACY_RAG_PROFILE
    if normalized in {"imi_leg", "imi_leg_06b"}:
        return IMI_RAG_PROFILE
    raise ValueError("LEGAL_AI_RUNTIME_PROFILE_INVALID")
