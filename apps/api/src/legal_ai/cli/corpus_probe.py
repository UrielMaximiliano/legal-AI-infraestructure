"""Sanitized G1-B Ollama probe for the real Docker/local HTTPS path."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from typing import Any

import httpx

from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

MODEL = EMBEDDING_MODEL
DIMENSIONS = EMBEDDING_DIMENSIONS
NATIVE_ENDPOINT = "/api/embed"
LEGACY_ENDPOINT = "/api/embeddings"
ALLOWED_ENDPOINTS = frozenset({NATIVE_ENDPOINT, LEGACY_ENDPOINT})
_DOCUMENTS = (
    "El decreto dispone una designaciÃ³n transitoria conforme a la Ley NÂ° 27.000.",
    "VISTO el expediente EX-2026-00000001 y CONSIDERANDO las competencias legales.",
)
_QUERY = "designaciÃ³n transitoria conforme a la ley"


def _vector_digest(vectors: Any) -> str:
    serialized = json.dumps(vectors, sort_keys=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_vectors(
    body: Any, count: int, *, endpoint: str = NATIVE_ENDPOINT
) -> tuple[int, bool, str]:
    if endpoint == NATIVE_ENDPOINT:
        vectors = body.get("embeddings") if isinstance(body, dict) else None
    else:
        embedding = body.get("embedding") if isinstance(body, dict) else None
        vectors = [embedding] if embedding is not None else None
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError("G1_EMBEDDING_COUNT_MISMATCH")
    finite = all(
        isinstance(vector, list)
        and len(vector) == DIMENSIONS
        and all(
            isinstance(value, (int, float)) and math.isfinite(value) for value in vector
        )
        for vector in vectors
    )
    if not finite:
        raise ValueError("G1_EMBEDDING_VECTOR_INVALID")
    return len(vectors), finite, _vector_digest(vectors)


async def probe(
    base_url: str,
    token: str,
    timeout: float = 10.0,
    endpoint: str = NATIVE_ENDPOINT,
) -> dict[str, object]:
    if not base_url.startswith("https://"):
        raise ValueError("G1_EXTERNAL_HTTPS_REQUIRED")
    if not token:
        raise ValueError("G1_BEARER_TOKEN_REQUIRED")
    if endpoint not in ALLOWED_ENDPOINTS:
        raise ValueError("G1_EMBEDDING_ENDPOINT_INVALID")
    started = time.monotonic()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers=headers,
        timeout=timeout,
    ) as client:
        version_response = await client.get("/api/version")
        if version_response.status_code != 200:
            raise ValueError("G1_VERSION_FAILED")
        version_body = version_response.json()
        show_response = await client.post("/api/show", json={"name": MODEL})
        if show_response.status_code != 200:
            raise ValueError("G1_SHOW_FAILED")

        async def embed_documents(documents: tuple[str, ...]) -> tuple[int, bool, str]:
            if endpoint == NATIVE_ENDPOINT:
                response = await client.post(
                    endpoint,
                    json={
                        "model": MODEL,
                        "input": list(documents),
                        "dimensions": DIMENSIONS,
                    },
                )
                if response.status_code != 200:
                    raise ValueError("G1_EMBED_FAILED")
                return _validate_vectors(
                    response.json(), len(documents), endpoint=endpoint
                )

            vectors: list[list[float]] = []
            for document in documents:
                response = await client.post(
                    endpoint, json={"model": MODEL, "prompt": document}
                )
                if response.status_code != 200:
                    raise ValueError("G1_EMBED_FAILED")
                payload = response.json()
                _validate_vectors(payload, 1, endpoint=endpoint)
                embedding = payload.get("embedding")
                if not isinstance(embedding, list):
                    raise ValueError("G1_EMBEDDING_VECTOR_INVALID")
                vectors.append(embedding)
            return _validate_vectors(
                {"embeddings": vectors}, len(documents), endpoint=NATIVE_ENDPOINT
            )

        count, finite, digest = await embed_documents(_DOCUMENTS)
        _, _, second_digest = await embed_documents(_DOCUMENTS)
        query_count, query_finite, _ = await embed_documents((_QUERY,))
    return {
        "status": "passed",
        "model": MODEL,
        "dimensions": DIMENSIONS,
        "endpoint": endpoint,
        "transport_batch_supported": endpoint == NATIVE_ENDPOINT,
        "application_batch_mode": (
            "native" if endpoint == NATIVE_ENDPOINT else "sequential"
        ),
        "version_present": isinstance(version_body, dict)
        and isinstance(version_body.get("version"), str),
        "show_status": "ok",
        "vector_count": count,
        "query_vector_count": query_count,
        "finite": finite and query_finite,
        "stable": digest == second_digest,
        "document_query_compatible": count == len(_DOCUMENTS) and query_count == 1,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "authorization_sent": True,
        "vectors_emitted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="corpus-probe")
    parser.add_argument(
        "--base-url",
        default=os.getenv("OLLAMA_EMBEDDING_BASE_URL")
        or os.getenv("OLLAMA_BASE_URL", ""),
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("OLLAMA_EMBEDDING_ENDPOINT", NATIVE_ENDPOINT),
        choices=sorted(ALLOWED_ENDPOINTS),
        help="Embedding endpoint profile exposed by the Ollama proxy.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("OLLAMA_EMBEDDING_TOKEN")
        or os.getenv("OLLAMA_API_TOKEN", ""),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        import asyncio

        result = asyncio.run(
            probe(args.base_url, args.token, args.timeout, args.endpoint)
        )
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except (OSError, httpx.HTTPError, ValueError, TimeoutError):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": "G1_EXTERNAL_PROBE_FAILED",
                },
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
