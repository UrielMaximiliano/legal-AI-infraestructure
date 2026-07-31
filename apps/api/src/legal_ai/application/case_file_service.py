"""Case file application service."""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.case_file import (
    TRANSITIONS_INITIAL_HISTORY_CHANGED_BY,
    CaseFile,
    can_transition,
)
from legal_ai.domain.case_status_history import CaseStatusHistory
from legal_ai.domain.enums import CaseStatus, CaseType
from legal_ai.domain.normalization import normalize_text


class CaseFileService:
    """Service handling case file business operations."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def create(
        self,
        employee_id: uuid.UUID,
        title: str,
        case_type: str,
        description: str | None = None,
        request_id: str | None = None,
    ) -> CaseFile:
        """Create a new case file with initial history atomically."""
        # Validate employee exists and is active
        employee = await self._uow.employees.get_by_id(employee_id)
        if employee is None:
            raise CaseFileEmployeeNotFoundError(employee_id)
        if not employee.active:
            raise CaseFileEmployeeInactiveError(employee_id)

        # Normalize inputs
        normalized_title = normalize_text(title)
        normalized_description = description.strip() if description else None

        # Generate case number
        case_number = f"CF-{uuid.uuid4()}"

        # Create case file
        now = datetime.now(UTC)
        case_file = CaseFile(
            id=uuid.uuid4(),
            case_number=case_number,
            employee_id=employee_id,
            title=normalized_title,
            description=normalized_description,
            case_type=CaseType(case_type),
            status=CaseStatus.DRAFT,
            version=1,
            opened_at=now,
            created_at=now,
            updated_at=now,
            closed_at=None,
        )

        # Create initial history entry
        history_entry = CaseStatusHistory(
            id=uuid.uuid4(),
            case_file_id=case_file.id,
            from_status=None,
            to_status=CaseStatus.DRAFT,
            changed_by=TRANSITIONS_INITIAL_HISTORY_CHANGED_BY,
            reason=None,
            request_id=request_id,
            changed_at=now,
        )

        # Persist atomically (if history fails, case file rolls back)
        created_case_file = await self._uow.case_files.create(case_file)
        await self._uow.case_status_history.create(history_entry)

        return created_case_file

    async def get_by_id(self, case_file_id: uuid.UUID) -> CaseFile:
        """Get case file by ID."""
        case_file = await self._uow.case_files.get_by_id(case_file_id)
        if case_file is None:
            raise CaseFileNotFoundError(case_file_id)
        return case_file

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        query: str | None = None,
        employee_id: uuid.UUID | None = None,
        status: str | None = None,
        case_type: str | None = None,
        opened_from: datetime | None = None,
        opened_to: datetime | None = None,
    ) -> tuple[list[CaseFile], int]:
        """List case files with pagination and filters."""
        return await self._uow.case_files.list(
            page=page,
            page_size=page_size,
            query=query,
            employee_id=employee_id,
            status=status,
            case_type=case_type,
            opened_from=opened_from,
            opened_to=opened_to,
        )

    async def update(
        self,
        case_file_id: uuid.UUID,
        title: str | None = None,
        description: str | None = None,
        expected_version: int | None = None,
    ) -> CaseFile:
        """Partial update of case file fields with optimistic locking."""
        case_file = await self._uow.case_files.get_by_id(case_file_id)
        if case_file is None:
            raise CaseFileNotFoundError(case_file_id)

        # Check if archived
        if case_file.status == CaseStatus.ARCHIVED:
            raise CaseFileArchivedError(case_file_id)

        # Check optimistic locking
        if expected_version is not None and case_file.version != expected_version:
            raise ConcurrentModificationError(case_file_id)

        # Apply updates
        if title is not None:
            case_file.title = normalize_text(title)
        if description is not None:
            case_file.description = description.strip() if description else None

        case_file.version += 1
        case_file.updated_at = datetime.now(UTC)

        return await self._uow.case_files.update(case_file)

    async def transition(
        self,
        case_file_id: uuid.UUID,
        status: CaseStatus,
        expected_version: int,
        changed_by: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> CaseFile:
        """Execute a state transition with atomic history creation."""
        case_file = await self._uow.case_files.get_by_id(case_file_id)
        if case_file is None:
            raise CaseFileNotFoundError(case_file_id)

        # Check if archived
        if case_file.status == CaseStatus.ARCHIVED:
            raise CaseFileArchivedError(case_file_id)

        # Check optimistic locking
        if case_file.version != expected_version:
            raise ConcurrentModificationError(case_file_id)

        # Check if transition is valid
        if not can_transition(case_file.status, status):
            raise InvalidStatusTransitionError(case_file.status, status)

        # Store from_status before modification
        from_status = case_file.status

        # Apply transition
        now = datetime.now(UTC)
        case_file.status = status
        case_file.version += 1
        case_file.updated_at = now

        # Set closed_at only when transitioning to archived
        if status == CaseStatus.ARCHIVED:
            case_file.closed_at = now

        # Persist case file
        updated_case_file = await self._uow.case_files.update(case_file)

        # Create history entry
        history_entry = CaseStatusHistory(
            id=uuid.uuid4(),
            case_file_id=case_file.id,
            from_status=from_status,
            to_status=status,
            changed_by=changed_by,
            reason=reason,
            request_id=request_id,
            changed_at=now,
        )
        await self._uow.case_status_history.create(history_entry)

        return updated_case_file

    async def get_history(
        self, case_file_id: uuid.UUID
    ) -> builtins.list[CaseStatusHistory]:
        """Get case file history ordered chronologically."""
        # Verify case file exists
        case_file = await self._uow.case_files.get_by_id(case_file_id)
        if case_file is None:
            raise CaseFileNotFoundError(case_file_id)

        return await self._uow.case_status_history.list_by_case_file(case_file_id)


# Domain exceptions


class CaseFileNotFoundError(Exception):
    """Raised when case file is not found."""

    def __init__(self, case_file_id: uuid.UUID) -> None:
        self.case_file_id = case_file_id
        super().__init__(f"Case file {case_file_id} not found")


class CaseFileEmployeeNotFoundError(Exception):
    """Raised when employee for case file is not found."""

    def __init__(self, employee_id: uuid.UUID) -> None:
        self.employee_id = employee_id
        super().__init__(f"Employee {employee_id} not found for case file")


class CaseFileEmployeeInactiveError(Exception):
    """Raised when trying to create case file for inactive employee."""

    def __init__(self, employee_id: uuid.UUID) -> None:
        self.employee_id = employee_id
        super().__init__(f"Employee {employee_id} is inactive, cannot create case file")


class CaseFileArchivedError(Exception):
    """Raised when trying to modify an archived case file."""

    def __init__(self, case_file_id: uuid.UUID) -> None:
        self.case_file_id = case_file_id
        super().__init__(f"Case file {case_file_id} is archived")


class ConcurrentModificationError(Exception):
    """Raised when version does not match (optimistic locking)."""

    def __init__(self, case_file_id: uuid.UUID) -> None:
        self.case_file_id = case_file_id
        super().__init__(f"Concurrent modification on case file {case_file_id}")


class InvalidStatusTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""

    def __init__(self, from_status: CaseStatus, to_status: CaseStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition from {from_status} to {to_status}")
