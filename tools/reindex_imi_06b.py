"""Copy the reviewed legacy corpus into the isolated IMI 0.6B index.

The source database is read-only from this process.  The destination is
resumable: documents/chunks are deterministic, embeddings are filled only
when missing, and the destination becomes searchable only after every copied
chunk has a 1024-dimensional 0.6B embedding.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx

MODEL = "qwen3-embedding:0.6b"
DIMENSIONS = 1024
EMBEDDING_CONTEXT = 2048
MAX_EMBEDDING_CHARS = 8_000
NAMESPACE = uuid.UUID("b2fca1c9-e8d6-4c88-a0f0-8e6c1e7f0d06")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def database_url(prefix: str, *, async_driver: bool = False) -> str:
    host = env(f"{prefix}_HOST", "127.0.0.1")
    port = env(f"{prefix}_PORT", "5432")
    database = env(f"{prefix}_DB", "legal_ai")
    user = env(f"{prefix}_USER", "legal_ai")
    password = env(f"{prefix}_PASSWORD", "change-me")
    scheme = "postgresql+asyncpg" if async_driver else "postgresql"
    return f"{scheme}://{user}:{password}@{host}:{port}/{database}"


async def connect_database(prefix: str, default_db: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=env(f"{prefix}_HOST", "127.0.0.1"),
        port=int(env(f"{prefix}_PORT", "5432")),
        database=env(f"{prefix}_DB", default_db),
        user=env(f"{prefix}_USER", "legal_ai"),
        password=env(f"{prefix}_PASSWORD", "change-me"),
    )


def split_for_embedding(content: str) -> list[str]:
    """Split oversized source chunks at whitespace without silent truncation."""

    clean = content.strip()
    if len(clean) <= MAX_EMBEDDING_CHARS:
        return [clean]
    parts: list[str] = []
    start = 0
    while start < len(clean):
        end = min(start + MAX_EMBEDDING_CHARS, len(clean))
        if end < len(clean):
            boundary = clean.rfind(" ", start, end)
            if boundary > start + MAX_EMBEDDING_CHARS // 2:
                end = boundary
        part = clean[start:end].strip()
        if not part:
            raise RuntimeError("EMPTY_REINDEX_SUBCHUNK")
        parts.append(part)
        start = end
        while start < len(clean) and clean[start].isspace():
            start += 1
    return parts


def code(value: str | None, fallback: str) -> str:
    normalized = (value or fallback).strip().upper()
    normalized = re.sub(r"[^A-Z0-9_]+", "_", normalized).strip("_")
    return (normalized or fallback)[:80]


async def ensure_catalogs(destination: asyncpg.Connection) -> dict[str, Any]:
    document_type = await destination.fetchval(
        "SELECT id FROM rag.document_types WHERE code = 'DECRETO'"
    )
    jurisdiction = await destination.fetchval(
        "SELECT id FROM rag.jurisdictions WHERE code = 'NACION'"
    )
    model_id = await destination.fetchval(
        "SELECT id FROM rag.embedding_models WHERE model_name = $1",
        MODEL,
    )
    if document_type is None or jurisdiction is None or model_id is None:
        raise RuntimeError("IMI_06B_DESTINATION_SCHEMA_NOT_READY")
    return {"document_type": document_type, "jurisdiction": jurisdiction, "model": model_id}


async def ensure_code_row(
    destination: asyncpg.Connection,
    table: str,
    key: str,
    name: str,
) -> uuid.UUID:
    if table == "document_subtypes":
        raise RuntimeError("USE_TYPED_CATALOG_INSERT")
    await destination.execute(
        f"""INSERT INTO rag.{table} (code, name)
            VALUES ($1, $2) ON CONFLICT (code) DO NOTHING""",
        key,
        name[:200],
    )
    result = await destination.fetchval(
        f"SELECT id FROM rag.{table} WHERE code = $1", key
    )
    if result is None:
        raise RuntimeError(f"CATALOG_ROW_NOT_FOUND:{table}:{key}")
    return result


async def ensure_subtype(
    destination: asyncpg.Connection,
    document_type_id: uuid.UUID,
    source_subtype: str | None,
) -> uuid.UUID:
    subtype_code = code(source_subtype, "GENERAL")
    await destination.execute(
        """INSERT INTO rag.document_subtypes
           (document_type_id, code, name)
           VALUES ($1, $2, $3)
           ON CONFLICT (document_type_id, code) DO NOTHING""",
        document_type_id,
        subtype_code,
        source_subtype or "General",
    )
    result = await destination.fetchval(
        """SELECT id FROM rag.document_subtypes
           WHERE document_type_id = $1 AND code = $2""",
        document_type_id,
        subtype_code,
    )
    if result is None:
        raise RuntimeError(f"SUBTYPE_NOT_FOUND:{subtype_code}")
    return result


async def upsert_document(
    destination: asyncpg.Connection,
    row: asyncpg.Record,
    catalogs: dict[str, Any],
) -> tuple[uuid.UUID, uuid.UUID, int]:
    source_type = str(row["document_type"] or "").strip().lower()
    if source_type != "decreto":
        raise RuntimeError(f"UNEXPECTED_SOURCE_DOCUMENT_TYPE:{source_type}")
    source_name = str(row["source_name"] or "BORA").strip()
    source_code = code(source_name, "BORA")
    source_id = await ensure_code_row(destination, "source_catalog", source_code, source_name)
    provenance = code(str(row["provenance_type"] or "OFFICIAL"), "OFFICIAL")
    if provenance not in {"OFFICIAL", "AUTOMATED", "MANUAL"}:
        provenance = "OFFICIAL"
    jurisdiction_code = code(str(row["jurisdiction"] or "NACION"), "NACION")
    jurisdiction_id = catalogs["jurisdiction"]
    if jurisdiction_code != "NACION":
        jurisdiction_id = await ensure_code_row(
            destination, "jurisdictions", jurisdiction_code, str(row["jurisdiction"])
        )
    organization_id = None
    if row["organization"]:
        organization_name = str(row["organization"]).strip()
        organization_id = await ensure_code_row(
            destination,
            "organizations",
            code(organization_name, "UNKNOWN_ORGANIZATION"),
            organization_name,
        )
    subtype_id = await ensure_subtype(
        destination, catalogs["document_type"], row["document_subtype"]
    )
    external_id = str(row["external_id"])
    document_id = uuid.uuid5(NAMESPACE, f"document:{external_id}")
    source_identifier = str(row["source_identifier"] or external_id)
    await destination.execute(
        """INSERT INTO rag.corpus_documents
           (id, external_id, title, document_type_id, document_subtype_id,
            jurisdiction_id, organization_id, language_code, source_id,
            source_identifier, source_url, publication_date, provenance_type_code,
            active)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,false)
           ON CONFLICT (external_id) DO NOTHING""",
        document_id,
        external_id,
        row["title"],
        catalogs["document_type"],
        subtype_id,
        jurisdiction_id,
        organization_id,
        str(row["language"] or "es").lower()[:16],
        source_id,
        source_identifier,
        row["source_url"],
        row["publication_date"],
        provenance,
    )
    existing_document_id = await destination.fetchval(
        "SELECT id FROM rag.corpus_documents WHERE external_id = $1", external_id
    )
    if existing_document_id is None:
        raise RuntimeError(f"DOCUMENT_NOT_FOUND_AFTER_INSERT:{external_id}")
    document_id = existing_document_id
    raw = str(row["raw_content"] or row["normalized_content"] or "")
    normalized = str(row["normalized_content"] or raw)
    if not raw.strip() or not normalized.strip():
        raise RuntimeError(f"EMPTY_SOURCE_DOCUMENT:{external_id}")
    raw_hash = str(row["raw_content_hash"] or sha256_text(raw)).strip()
    normalized_hash = str(
        row["normalized_content_hash"] or sha256_text(normalized)
    ).strip()
    version_id = uuid.uuid5(NAMESPACE, f"version:{external_id}:1")
    await destination.execute(
        """INSERT INTO rag.corpus_document_versions
           (id, document_id, version, raw_content, raw_content_sha256,
            normalized_content, normalized_content_sha256, review_status_code,
            reviewed_by_auth_user_id, reviewed_at, review_notes,
            ingestion_status_code, embedding_status_code, pipeline_version,
            normalization_version, chunking_version, is_active)
           VALUES ($1,$2,1,$3,$4,$5,$6,'REVIEWED',$7,$8,$9,'INGESTED',
                   'PENDING','imi-legacy-copy-v1',$10,$11,false)
           ON CONFLICT (document_id, version) DO NOTHING""",
        version_id,
        document_id,
        raw,
        raw_hash,
        normalized,
        normalized_hash,
        str(row["reviewed_by"] or "legacy-reindex")[:200],
        row["reviewed_at"] or datetime.now(UTC),
        "Copied from immutable legal_ai corpus; re-embedded with 0.6B/1024.",
        str(row["normalization_version"] or "legacy"),
        str(row["chunking_version"] or "legacy-split-8000"),
    )
    actual_version_id = await destination.fetchval(
        "SELECT id FROM rag.corpus_document_versions WHERE document_id=$1 AND version=1",
        document_id,
    )
    if actual_version_id is None:
        raise RuntimeError(f"VERSION_NOT_FOUND_AFTER_INSERT:{external_id}")
    await destination.execute(
        """INSERT INTO rag.corpus_document_version_splits
           (document_version_id, split_code)
           VALUES ($1, 'INDEX_90') ON CONFLICT DO NOTHING""",
        actual_version_id,
    )
    return document_id, actual_version_id, int(row["active_generation"] or 1)


async def copy_corpus(
    source: asyncpg.Connection,
    destination: asyncpg.Connection,
    *,
    limit: int | None,
) -> dict[str, int]:
    catalogs = await ensure_catalogs(destination)
    docs = await source.fetch(
        """SELECT id, external_id, title, document_type, document_subtype,
                   jurisdiction, language, organization, source_name,
                   source_identifier, source_url, publication_date, raw_content,
                   raw_content_hash, normalized_content, normalized_content_hash,
                   provenance_type, review_status, reviewed_by, reviewed_at,
                   review_notes, normalization_version, chunking_version,
                   active_generation
            FROM public.corpus_documents
            WHERE active_generation IS NOT NULL
            ORDER BY id
            """ + (f" LIMIT {int(limit)}" if limit is not None else "")
    )
    source_chunks = 0
    destination_chunks = 0
    split_count = 0
    async with destination.transaction():
        for doc in docs:
            document_id, version_id, generation = await upsert_document(
                destination, doc, catalogs
            )
            chunks = await source.fetch(
                """SELECT id, section_type, section_index, paragraph_index,
                          article_number, content, content_hash, token_count,
                          metadata
                   FROM public.corpus_chunks
                   WHERE document_id=$1 AND generation=$2
                   ORDER BY section_index, paragraph_index, id""",
                doc["id"],
                generation,
            )
            source_chunks += len(chunks)
            for chunk in chunks:
                parts = split_for_embedding(str(chunk["content"] or ""))
                if len(parts) > 1:
                    split_count += len(parts) - 1
                for part_index, part in enumerate(parts):
                    chunk_id = uuid.uuid5(
                        NAMESPACE,
                        f"chunk:{chunk['id']}:{part_index}",
                    )
                    content_hash = sha256_text(part)
                    section_index = int(chunk["section_index"] or 0) * 100_000 + part_index
                    paragraph_index = int(chunk["paragraph_index"] or 0) * 1_000 + part_index
                    await destination.execute(
                        """INSERT INTO rag.corpus_chunks
                           (id, document_version_id, generation, state_code,
                            section_type, section_index, paragraph_index,
                            article_number, content, content_sha256, token_count,
                            embedding_model_id, embedding)
                           VALUES ($1,$2,1,'INACTIVE',$3,$4,$5,$6,$7,$8,$9,NULL,NULL)
                           ON CONFLICT (id) DO NOTHING""",
                        chunk_id,
                        version_id,
                        str(chunk["section_type"] or "general")[:40],
                        section_index,
                        paragraph_index,
                        chunk["article_number"],
                        part,
                        content_hash,
                        max(1, (len(part.encode("utf-8")) + 3) // 4),
                    )
                    destination_chunks += 1
            await destination.execute(
                """UPDATE rag.corpus_documents SET active=false, updated_at=now()
                   WHERE id=$1""",
                document_id,
            )
    return {
        "source_documents": len(docs),
        "source_chunks": source_chunks,
        "destination_chunks": destination_chunks,
        "oversized_source_chunks_split": split_count,
    }


async def embed_pending(
    destination: asyncpg.Connection,
    client: httpx.AsyncClient,
    *,
    concurrency: int,
    batch_size: int,
) -> int:
    model_id = await destination.fetchval(
        "SELECT id FROM rag.embedding_models WHERE model_name=$1", MODEL
    )
    if model_id is None:
        raise RuntimeError("IMI_06B_EMBEDDING_MODEL_NOT_SEEDED")
    semaphore = asyncio.Semaphore(concurrency)
    total = 0
    while True:
        rows = await destination.fetch(
            """SELECT id, content FROM rag.corpus_chunks
               WHERE embedding IS NULL ORDER BY id LIMIT $1""",
            batch_size,
        )
        if not rows:
            break

        async def embed_one(row: asyncpg.Record) -> tuple[uuid.UUID, list[float]]:
            async with semaphore:
                response = await client.post(
                    "/api/embed",
                    json={
                        "model": MODEL,
                        "input": [str(row["content"])],
                        "dimensions": DIMENSIONS,
                        "options": {"num_ctx": EMBEDDING_CONTEXT},
                    },
                )
                response.raise_for_status()
                body = response.json()
                embeddings = body.get("embeddings") if isinstance(body, dict) else None
                if not isinstance(embeddings, list) or len(embeddings) != 1:
                    raise RuntimeError("OLLAMA_EMBEDDING_COUNT_MISMATCH")
                vector = embeddings[0]
                if not isinstance(vector, list) or len(vector) != DIMENSIONS:
                    raise RuntimeError("OLLAMA_EMBEDDING_DIMENSIONS_MISMATCH")
                if not all(isinstance(value, (int, float)) for value in vector):
                    raise RuntimeError("OLLAMA_EMBEDDING_VECTOR_INVALID")
                return row["id"], [float(value) for value in vector]

        results = await asyncio.gather(*(embed_one(row) for row in rows))
        async with destination.transaction():
            for chunk_id, vector in results:
                await destination.execute(
                    """UPDATE rag.corpus_chunks
                       SET embedding=CAST($1 AS halfvec), embedding_model_id=$2
                       WHERE id=$3 AND embedding IS NULL""",
                    json.dumps(vector, separators=(",", ":")),
                    model_id,
                    chunk_id,
                )
        total += len(results)
        print(f"embedded={total}", flush=True)
    return total


async def finalize(destination: asyncpg.Connection) -> dict[str, int]:
    pending = await destination.fetchval(
        "SELECT count(*) FROM rag.corpus_chunks WHERE embedding IS NULL"
    )
    if pending:
        raise RuntimeError(f"EMBEDDINGS_PENDING:{pending}")
    await destination.execute(
        """UPDATE rag.corpus_document_versions
           SET embedding_status_code='COMPLETED', is_active=true
           WHERE version=1"""
    )
    await destination.execute(
        """UPDATE rag.corpus_documents d SET active=true, updated_at=now()
           WHERE EXISTS (
             SELECT 1 FROM rag.corpus_document_versions v
             WHERE v.document_id=d.id AND v.is_active
           )"""
    )
    await destination.execute(
        """UPDATE rag.corpus_chunks SET state_code='ACTIVE'
           WHERE embedding IS NOT NULL"""
    )
    await destination.execute(
        """CREATE INDEX IF NOT EXISTS ix_rag_corpus_chunks_embedding_hnsw
           ON rag.corpus_chunks USING hnsw (embedding halfvec_cosine_ops)
           WHERE embedding IS NOT NULL"""
    )
    row = await destination.fetchrow(
        """SELECT
             (SELECT count(*) FROM rag.corpus_documents WHERE active) AS documents,
             (SELECT count(*) FROM rag.corpus_document_versions WHERE is_active AND review_status_code='REVIEWED') AS versions,
             (SELECT count(*) FROM rag.corpus_chunks WHERE state_code='ACTIVE' AND embedding IS NOT NULL) AS chunks,
             (SELECT count(*) FROM rag.corpus_chunks WHERE embedding_model_id=(SELECT id FROM rag.embedding_models WHERE model_name=$1)) AS model_chunks
           """,
        MODEL,
    )
    values = {
        key: int(row[key])
        for key in ("documents", "versions", "chunks", "model_chunks")
    }
    if values["chunks"] != values["model_chunks"]:
        raise RuntimeError("IMI_06B_MODEL_MIX_DETECTED")
    return values


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Copy only the first N documents")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--manifest", type=Path, default=Path("/tmp/imi-06b-reindex-manifest.json"))
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if not 1 <= args.concurrency <= 32:
        parser.error("--concurrency must be between 1 and 32")

    source = await connect_database("POSTGRES", "legal_ai")
    destination = await connect_database(
        "IMI_DISPOSITIONS_RAG_POSTGRES", "imi_disposiciones_rag"
    )
    base_url = env("OLLAMA_EMBEDDING_BASE_URL", env("OLLAMA_BASE_URL", "http://host.docker.internal:11434"))
    token = env("OLLAMA_EMBEDDING_TOKEN", env("OLLAMA_API_TOKEN", ""))
    try:
        counts = await copy_corpus(source, destination, limit=args.limit)
        timeout = httpx.Timeout(180.0, connect=30.0)
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            counts["embedded_now"] = await embed_pending(
                destination,
                client,
                concurrency=args.concurrency,
                batch_size=args.batch_size,
            )
        pending = await destination.fetchval(
            "SELECT count(*) FROM rag.corpus_chunks WHERE embedding IS NULL"
        )
        if pending:
            raise RuntimeError(f"EMBEDDINGS_PENDING:{pending}")
        counts.update(await finalize(destination))
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "profile_code": "imi_leg_06b",
            "embedding_model": MODEL,
            "embedding_dimensions": DIMENSIONS,
            "embedding_context_length": EMBEDDING_CONTEXT,
            "rag_context_length": 2048,
            "generation_model": "qwen3.6:35b",
            "generation_context_length": 16384,
            "top_k": 8,
            "candidate_pool_size": 24,
            "minimum_score": 0.0,
            "max_embedding_chars": MAX_EMBEDDING_CHARS,
            **counts,
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2), flush=True)
    finally:
        await source.close()
        await destination.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except (asyncpg.PostgresError, httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"reindex failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
