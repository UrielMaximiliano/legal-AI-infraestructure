"""Deterministic, bounded context assembly with resolvable citations."""

from __future__ import annotations

from dataclasses import dataclass, replace

from legal_ai.domain.rag import (
    RagRetrievedSource,
    RagSourceDisposition,
    estimate_tokens,
    sha256_text,
)


@dataclass(frozen=True, slots=True)
class RagContext:
    sources: tuple[RagRetrievedSource, ...]
    text: str
    context_hash: str
    context_bytes: int
    context_tokens_estimate: int


class ContextAssembler:
    """Select evidence within dual budgets without splitting an excerpt."""

    def __init__(
        self, *, max_bytes: int = 65_536, max_tokens_estimate: int = 16_384
    ) -> None:
        if max_bytes <= 0 or max_tokens_estimate <= 0:
            raise ValueError("RAG_CONTEXT_LIMIT_INVALID")
        self.max_bytes = max_bytes
        self.max_tokens_estimate = max_tokens_estimate

    @staticmethod
    def _data_value(value: str | None, fallback: str = "unknown") -> str:
        cleaned = " ".join((value or fallback).split())
        for marker in (
            "EVIDENCE_DATA_BEGIN",
            "EVIDENCE_DATA_END",
            "[/EVIDENCE",
            "[EVIDENCE",
        ):
            cleaned = cleaned.replace(marker, f"{marker}_ESCAPED")
        return cleaned

    @staticmethod
    def _block(source: RagRetrievedSource) -> str:
        excerpt = ContextAssembler._data_value(source.excerpt, "")
        return "\n".join(
            (
                f"[EVIDENCE {source.citation_id} DATA_ONLY]",
                f"title={ContextAssembler._data_value(source.title)}",
                f"external_id={ContextAssembler._data_value(source.external_id)}",
                "publication_date="
                f"{ContextAssembler._data_value(source.publication_date)}",
                f"section={ContextAssembler._data_value(source.section_type)}",
                "article="
                f"{ContextAssembler._data_value(source.article_number, 'none')}",
                f"extract={excerpt}",
                f"[/EVIDENCE {source.citation_id}]",
            )
        )

    def assemble(self, sources: tuple[RagRetrievedSource, ...]) -> RagContext:
        selected: list[RagRetrievedSource] = []
        blocks: list[str] = []
        byte_count = 0
        token_count = 0
        updated: list[RagRetrievedSource] = []
        for source in sources:
            if source.disposition is not RagSourceDisposition.SELECTED:
                updated.append(source)
                continue
            block = self._block(source)
            block_bytes = len(block.encode("utf-8"))
            block_tokens = estimate_tokens(block)
            separator_bytes = 2 if blocks else 0
            separator_tokens = estimate_tokens("\n\n") if blocks else 0
            if (
                byte_count + separator_bytes + block_bytes > self.max_bytes
                or token_count + separator_tokens + block_tokens
                > self.max_tokens_estimate
            ):
                updated.append(
                    replace(
                        source,
                        disposition=RagSourceDisposition.EXCLUDED_BUDGET,
                        context_rank=None,
                    )
                )
                continue
            context_rank = len(selected) + 1
            selected_source = replace(
                source,
                disposition=RagSourceDisposition.SELECTED,
                context_rank=context_rank,
            )
            selected.append(selected_source)
            updated.append(selected_source)
            blocks.append(block)
            byte_count += separator_bytes + block_bytes
            token_count += separator_tokens + block_tokens
        text = "\n\n".join(blocks)
        return RagContext(
            sources=tuple(updated),
            text=text,
            context_hash=sha256_text(text),
            context_bytes=byte_count,
            context_tokens_estimate=token_count,
        )
