"""Atomicity tests for the five persistence tables introduced in 003."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.template_service import TemplateService
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.designation_data import DesignationData
from legal_ai.domain.draft import Draft, DraftTransition
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import (
    CaseStatus,
    CaseType,
    DocumentType,
    DraftStatus,
    GenerationStatus,
    TemplateDocumentType,
    TransitionAction,
)
from legal_ai.domain.generation_attempt import GenerationAttempt
from legal_ai.domain.template import Template


async def _entities() -> tuple[Employee, CaseFile, Template, DesignationData, Draft]:
    now = datetime.now(UTC)
    employee = Employee(
        id=uuid.uuid4(),
        employee_number=f"LEG-{uuid.uuid4().hex[:10]}",
        first_name="UoW",
        last_name="003",
        document_type=DocumentType.DNI,
        document_number=str(uuid.uuid4().int)[:8],
        created_at=now,
        updated_at=now,
    )
    case_file = CaseFile(
        id=uuid.uuid4(),
        case_number=f"EXP-{uuid.uuid4().hex[:10]}",
        employee_id=employee.id,
        title="Atomic case",
        case_type=CaseType.DESIGNACION,
        status=CaseStatus.DRAFT,
        opened_at=now,
        created_at=now,
        updated_at=now,
    )
    template = Template(
        id=uuid.uuid4(),
        name=f"Atomic template {uuid.uuid4().hex[:8]}",
        document_type=TemplateDocumentType.RESOLUCION,
        version=1,
        body_template="body",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    designation = DesignationData(
        id=uuid.uuid4(),
        case_file_id=case_file.id,
        position_name="Director",
        created_at=now,
        updated_at=now,
    )
    draft = Draft(
        id=uuid.uuid4(),
        template_id=template.id,
        case_file_id=case_file.id,
        title="Draft",
        content="content",
        status=DraftStatus.GENERADO,
        version=1,
        generation_number=1,
        context_snapshot={"metadata": {"immutable": True}},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )
    return employee, case_file, template, designation, draft


@pytest.mark.integration
async def test_uow_commit_persists_all_five_new_tables() -> None:
    employee, case_file, template, designation, draft = await _entities()
    now = datetime.now(UTC)
    transition = DraftTransition(
        id=uuid.uuid4(),
        draft_id=draft.id,
        from_status=DraftStatus.GENERADO,
        to_status=DraftStatus.EN_REVISION,
        action=TransitionAction.SEND_TO_REVIEW,
        created_at=now,
    )
    attempt = GenerationAttempt(
        id=uuid.uuid4(),
        case_file_id=case_file.id,
        template_id=template.id,
        model="test",
        prompt_hash="b" * 64,
        prompt_content="private prompt",
        status=GenerationStatus.COMPLETED,
        started_at=now,
        created_at=now,
    )
    async with UnitOfWork() as uow:
        await uow.employees.create(employee)
        await uow.case_files.create(case_file)
        await uow.templates.create(template)
        await uow.designations.create(designation)
        await uow.drafts.create(draft)
        await uow.draft_transitions.create(transition)
        await uow.generation_attempts.create(attempt)

    async with UnitOfWork() as uow:
        assert await uow.templates.get_by_id(template.id) is not None
        assert await uow.designations.get_by_case_file_id(case_file.id) is not None
        assert await uow.drafts.get_by_id(draft.id) is not None
        assert len(await uow.draft_transitions.list_by_draft(draft.id)) == 1
        assert await uow.generation_attempts.get_by_id(attempt.id) is not None


@pytest.mark.integration
async def test_uow_rollback_discards_all_new_rows() -> None:
    employee, case_file, template, designation, draft = await _entities()
    try:
        async with UnitOfWork() as uow:
            await uow.employees.create(employee)
            await uow.case_files.create(case_file)
            await uow.templates.create(template)
            await uow.designations.create(designation)
            await uow.drafts.create(draft)
            await uow.draft_transitions.create(
                DraftTransition(
                    id=uuid.uuid4(),
                    draft_id=draft.id,
                    from_status=DraftStatus.GENERADO,
                    to_status=DraftStatus.EN_REVISION,
                    action=TransitionAction.SEND_TO_REVIEW,
                    created_at=datetime.now(UTC),
                )
            )
            await uow.generation_attempts.create(
                GenerationAttempt(
                    id=uuid.uuid4(),
                    case_file_id=case_file.id,
                    template_id=template.id,
                    model="test",
                    prompt_hash="c" * 64,
                    prompt_content="private prompt",
                    status=GenerationStatus.IN_PROGRESS,
                    started_at=datetime.now(UTC),
                    created_at=datetime.now(UTC),
                )
            )
            raise RuntimeError("force transaction rollback")
    except RuntimeError:
        pass

    async with UnitOfWork() as uow:
        assert await uow.employees.get_by_id(employee.id) is None
        assert await uow.case_files.get_by_id(case_file.id) is None
        assert await uow.templates.get_by_id(template.id) is None
        assert await uow.drafts.get_by_id(draft.id) is None


@pytest.mark.integration
async def test_draft_and_transition_are_atomic() -> None:
    employee, case_file, template, designation, draft = await _entities()
    async with UnitOfWork() as uow:
        await uow.employees.create(employee)
        await uow.case_files.create(case_file)
        await uow.templates.create(template)
        await uow.designations.create(designation)
        await uow.drafts.create(draft)
        await uow.draft_transitions.create(
            DraftTransition(
                id=uuid.uuid4(),
                draft_id=draft.id,
                from_status=DraftStatus.GENERADO,
                to_status=DraftStatus.EN_REVISION,
                action=TransitionAction.SEND_TO_REVIEW,
                created_at=datetime.now(UTC),
            )
        )
    async with UnitOfWork() as uow:
        assert len(await uow.draft_transitions.list_by_draft(draft.id)) == 1


@pytest.mark.integration
async def test_template_versioning_rolls_back_deactivation_on_create_failure() -> None:
    _, _, template, _, _ = await _entities()
    async with UnitOfWork() as uow:
        await uow.templates.create(template)

    with pytest.raises(RuntimeError):
        async with UnitOfWork() as uow:
            uow.templates.create = AsyncMock(side_effect=RuntimeError("version write"))
            with pytest.raises(RuntimeError):
                await TemplateService(uow).update_template(
                    str(template.id), body_template="version 2"
                )
            raise RuntimeError("rollback versioning")

    async with UnitOfWork() as uow:
        active = await uow.templates.get_active_version(
            template.name, template.document_type
        )
        assert active is not None
        assert active.version == 1
        assert active.is_active is True
