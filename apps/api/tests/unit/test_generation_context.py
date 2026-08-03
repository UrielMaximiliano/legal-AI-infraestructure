"""Unit tests for generation context."""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from legal_ai.application.generation_context import (
    ContextBuildFailedError,
    GenerationContext,
    MissingRequiredVariablesError,
)
from legal_ai.domain.enums import CaseType, TemplateDocumentType
from legal_ai.domain.template import Template


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.templates = AsyncMock()
    uow.case_files = AsyncMock()
    uow.employees = AsyncMock()
    uow.designations = AsyncMock()
    return uow


@pytest.fixture
def context_builder(mock_uow):
    return GenerationContext(mock_uow)


class TestBuildContext:
    def test_build_context_complete(self, context_builder, mock_uow):
        template_id = uuid.uuid4()
        case_file_id = uuid.uuid4()
        employee_id = uuid.uuid4()

        mock_uow.templates.get_by_id.return_value = Template(
            id=template_id,
            name="Test",
            document_type=TemplateDocumentType.RESOLUCION,
            version=1,
            body_template="body",
            variables=["employee.first_name"],
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_uow.case_files.get_by_id.return_value = MagicMock(
            id=case_file_id,
            case_number="CF-001",
            title="Test Case",
            description="Desc",
            case_type=CaseType.DESIGNACION,
            status="draft",
            employee_id=employee_id,
        )
        mock_uow.employees.get_by_id.return_value = MagicMock(
            id=employee_id,
            first_name="Juan",
            last_name="García",
            department="Legal",
        )
        mock_uow.designations.get_by_case_file_id.return_value = MagicMock(
            position_name="Director",
            organizational_unit="Unidad A",
            start_date=None,
            legal_basis="Ley 1",
            appointing_authority="Ministro",
            salary_category="Cat I",
            work_schedule="Full",
            observations="None",
        )

        result = asyncio.run(context_builder.build_context(template_id, case_file_id))

        assert "template" in result
        assert "case_file" in result
        assert "employee" in result
        assert "designation" in result
        assert "variables" in result
        assert "metadata" in result
        assert result["template"]["name"] == "Test"
        assert result["employee"]["first_name"] == "Juan"

    def test_build_context_template_not_found(self, context_builder, mock_uow):
        mock_uow.templates.get_by_id.return_value = None

        with pytest.raises(ContextBuildFailedError):
            asyncio.run(context_builder.build_context(uuid.uuid4(), uuid.uuid4()))

    def test_build_context_case_file_not_found(self, context_builder, mock_uow):
        mock_uow.templates.get_by_id.return_value = MagicMock()
        mock_uow.case_files.get_by_id.return_value = None

        with pytest.raises(ContextBuildFailedError):
            asyncio.run(context_builder.build_context(uuid.uuid4(), uuid.uuid4()))


class TestComputeHash:
    def test_hash_deterministic(self):
        snapshot = {"key": "value", "nested": {"a": 1}}
        hash1 = GenerationContext.compute_hash(snapshot)
        hash2 = GenerationContext.compute_hash(snapshot)
        assert hash1 == hash2

    def test_hash_different_for_different_data(self):
        hash1 = GenerationContext.compute_hash({"key": "value1"})
        hash2 = GenerationContext.compute_hash({"key": "value2"})
        assert hash1 != hash2

    def test_hash_is_sha256(self):
        snapshot = {"test": "data"}
        hash_val = GenerationContext.compute_hash(snapshot)
        assert len(hash_val) == 64


class TestValidateVariables:
    def test_valid_variables_pass(self, context_builder):
        context_builder.validate_variables(
            ["name", "department"], {"name": "Juan", "department": "Legal"}
        )

    def test_missing_variables_raise(self, context_builder):
        with pytest.raises(MissingRequiredVariablesError) as exc_info:
            context_builder.validate_variables(["name", "department"], {"name": "Juan"})
        assert "department" in exc_info.value.missing

    def test_extra_variables_ignored(self, context_builder):
        context_builder.validate_variables(
            ["name"], {"name": "Juan", "extra": "ignored"}
        )
