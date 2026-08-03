"""Unit of Work for transactional operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.case_file_repository import (
    SQLAlchemyCaseFileRepository,
)
from legal_ai.adapters.database.case_status_history_repository import (
    SQLAlchemyCaseStatusHistoryRepository,
)
from legal_ai.adapters.database.designation_repository import (
    SQLAlchemyDesignationRepository,
)
from legal_ai.adapters.database.draft_repository import SQLAlchemyDraftRepository
from legal_ai.adapters.database.draft_transition_repository import (
    SQLAlchemyDraftTransitionRepository,
)
from legal_ai.adapters.database.employee_repository import (
    SQLAlchemyEmployeeRepository,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.generation_attempt_repository import (
    SQLAlchemyGenerationAttemptRepository,
)
from legal_ai.adapters.database.template_repository import (
    SQLAlchemyTemplateRepository,
)


class UnitOfWork:
    """Unit of Work managing transactional operations across repositories."""

    def __init__(self) -> None:
        self._engine = create_engine()
        self._session: AsyncSession | None = None
        self._employees: SQLAlchemyEmployeeRepository | None = None
        self._case_files: SQLAlchemyCaseFileRepository | None = None
        self._case_status_history: SQLAlchemyCaseStatusHistoryRepository | None = None
        self._templates: SQLAlchemyTemplateRepository | None = None
        self._drafts: SQLAlchemyDraftRepository | None = None
        self._draft_transitions: SQLAlchemyDraftTransitionRepository | None = None
        self._generation_attempts: SQLAlchemyGenerationAttemptRepository | None = None
        self._designations: SQLAlchemyDesignationRepository | None = None

    async def __aenter__(self) -> UnitOfWork:
        self._session = AsyncSession(self._engine, expire_on_commit=False)
        await self._session.begin()
        self._employees = SQLAlchemyEmployeeRepository(self._session)
        self._case_files = SQLAlchemyCaseFileRepository(self._session)
        self._case_status_history = SQLAlchemyCaseStatusHistoryRepository(self._session)
        self._templates = SQLAlchemyTemplateRepository(self._session)
        self._drafts = SQLAlchemyDraftRepository(self._session)
        self._draft_transitions = SQLAlchemyDraftTransitionRepository(self._session)
        self._generation_attempts = SQLAlchemyGenerationAttemptRepository(self._session)
        self._designations = SQLAlchemyDesignationRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()

    async def commit(self) -> None:
        if self._session is not None:
            await self._session.commit()

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()

    @property
    def employees(self) -> SQLAlchemyEmployeeRepository:
        if self._employees is None:
            raise RuntimeError("UnitOfWork not initialized")
        return self._employees

    @property
    def case_files(self) -> SQLAlchemyCaseFileRepository:
        if self._case_files is None:
            raise RuntimeError("UnitOfWork not initialized")
        return self._case_files

    @property
    def case_status_history(
        self,
    ) -> SQLAlchemyCaseStatusHistoryRepository:
        if self._case_status_history is None:
            raise RuntimeError("UnitOfWork not initialized")
        return self._case_status_history

    @property
    def templates(self) -> SQLAlchemyTemplateRepository:
        if self._templates is None:
            raise RuntimeError("UnitOfWork not initialized")
        return self._templates

    @property
    def drafts(self) -> SQLAlchemyDraftRepository:
        if self._drafts is None:
            raise RuntimeError("UnitOfWork not initialized")
        return self._drafts

    @property
    def draft_transitions(self) -> SQLAlchemyDraftTransitionRepository:
        if self._draft_transitions is None:
            raise RuntimeError("UnitOfWork not initialized")
        return self._draft_transitions

    @property
    def generation_attempts(self) -> SQLAlchemyGenerationAttemptRepository:
        if self._generation_attempts is None:
            raise RuntimeError("UnitOfWork not initialized")
        return self._generation_attempts

    @property
    def designations(self) -> SQLAlchemyDesignationRepository:
        if self._designations is None:
            raise RuntimeError("UnitOfWork not initialized")
        return self._designations
