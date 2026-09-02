"""Validate the static separation contract for the IMI LEG databases."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_SQL = ROOT / "infra/database/imi-core/init/001_schema.sql"
RAG_SQL = ROOT / "infra/database/imi-disposiciones-rag/init/001_schema.sql"


def _require(text: str, fragment: str, source: Path) -> None:
    if fragment not in text:
        raise AssertionError(f"{source}: falta {fragment!r}")


def validate() -> None:
    core = CORE_SQL.read_text(encoding="utf-8")
    rag = RAG_SQL.read_text(encoding="utf-8")

    _require(core, "CREATE SCHEMA IF NOT EXISTS auth", CORE_SQL)
    _require(core, "CREATE TABLE imi.document_templates", CORE_SQL)
    _require(core, "CREATE TABLE imi.document_variable_values", CORE_SQL)
    _require(core, "CREATE TABLE imi.official_number_sequences", CORE_SQL)
    _require(core, "CREATE TABLE imi.official_document_numbers", CORE_SQL)
    _require(core, "trg_official_document_number_year", CORE_SQL)
    _require(core, "CREATE TABLE imi.document_versions", CORE_SQL)
    _require(core, "uq_imi_active_template_per_organization_type", CORE_SQL)
    template_seed = ROOT / "infra/database/imi-core/init/002_seed_fondo_permanente_template.sql"
    _require(template_seed.read_text(encoding="utf-8"), "Disposición IMI — Fondo Permanente", template_seed)
    _require(rag, "CREATE EXTENSION IF NOT EXISTS vector", RAG_SQL)
    _require(rag, "CREATE TABLE rag.corpus_documents", RAG_SQL)
    _require(rag, "CREATE TABLE rag.corpus_chunks", RAG_SQL)
    _require(rag, "CREATE TABLE rag.retrieval_statuses", RAG_SQL)
    _require(rag, "embedding halfvec(1024)", RAG_SQL)
    _require(rag, "CREATE TABLE rag.runtime_profiles", RAG_SQL)
    _require(rag, "qwen3-embedding:0.6b", RAG_SQL)
    _require(rag, "'imi_leg_06b'", RAG_SQL)
    _require(rag, "CREATE VIEW rag.eligible_legal_chunks", RAG_SQL)
    _require(rag, "VALUES ('DECRETO', 'Decreto')", RAG_SQL)
    _require(rag, "ck_rag_document_types_only_decrees", RAG_SQL)

    forbidden_in_core = ("corpus_documents", "corpus_chunks", "halfvec(", "CREATE EXTENSION IF NOT EXISTS vector")
    for fragment in forbidden_in_core:
        if fragment in core:
            raise AssertionError(f"{CORE_SQL}: contiene objeto vectorial/RAG {fragment!r}")

    forbidden_in_rag = (
        "CREATE TABLE rag.employees",
        "CREATE TABLE rag.document_templates",
        "CREATE TABLE rag.employee_auth_accounts",
        "CREATE TABLE rag.document_versions",
        "halfvec(2560)",
        "qwen3-embedding:4b-q4_K_M",
    )
    for fragment in forbidden_in_rag:
        if fragment in rag:
            raise AssertionError(f"{RAG_SQL}: mezcla dominio core o decretos {fragment!r}")

    print("database contract: OK")


if __name__ == "__main__":
    try:
        validate()
    except (AssertionError, OSError) as exc:
        print(f"database contract: FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
