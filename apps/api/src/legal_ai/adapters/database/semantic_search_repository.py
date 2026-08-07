"""Persistence adapters for minimized search audit and human evaluation."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.domain.semantic_search import (
    HumanRetrievalEvaluation,
    SemanticSearchRun,
)

from .semantic_search_mappers import (
    human_evaluation_to_model,
    semantic_search_run_to_model,
)


class SQLAlchemySemanticSearchRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: SemanticSearchRun) -> SemanticSearchRun:
        self._session.add(semantic_search_run_to_model(run))
        await self._session.flush()
        return run

    async def record(self, run: SemanticSearchRun) -> None:
        await self.create(run)


class SQLAlchemyHumanRetrievalEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, evaluation: HumanRetrievalEvaluation
    ) -> HumanRetrievalEvaluation:
        self._session.add(human_evaluation_to_model(evaluation))
        await self._session.flush()
        return evaluation


SemanticSearchRunRepository = SQLAlchemySemanticSearchRunRepository
