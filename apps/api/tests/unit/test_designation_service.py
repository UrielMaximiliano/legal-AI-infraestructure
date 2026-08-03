"""Unit tests for designation service."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from legal_ai.application.designation_service import (
    CaseFileNotFoundError,
    CaseFileTypeIncompatibleError,
    DesignationExistsError,
    DesignationNotFoundError,
    DesignationService,
)
from legal_ai.domain.enums import CaseType


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.case_files = AsyncMock()
    uow.designations = AsyncMock()
    return uow


@pytest.fixture
def service(mock_uow):
    return DesignationService(mock_uow)


class TestCreateDesignation:
    def test_create_designation_success(self, service, mock_uow):
        mock_uow.case_files.get_by_id.return_value = MagicMock(
            case_type=CaseType.DESIGNACION
        )
        mock_uow.designations.get_by_case_file_id.return_value = None
        mock_uow.designations.create.side_effect = lambda d: d

        result = asyncio.run(
            service.create_designation(
                case_file_id=str(uuid.uuid4()),
                position_name="Director",
            )
        )
        assert result.position_name == "Director"

    def test_create_designation_case_file_not_found(self, service, mock_uow):
        mock_uow.case_files.get_by_id.return_value = None

        with pytest.raises(CaseFileNotFoundError):
            asyncio.run(
                service.create_designation(
                    case_file_id=str(uuid.uuid4()),
                    position_name="Director",
                )
            )

    def test_create_designation_wrong_type(self, service, mock_uow):
        mock_uow.case_files.get_by_id.return_value = MagicMock(
            case_type=CaseType.LICENCIA
        )

        with pytest.raises(CaseFileTypeIncompatibleError):
            asyncio.run(
                service.create_designation(
                    case_file_id=str(uuid.uuid4()),
                    position_name="Director",
                )
            )

    def test_create_designation_already_exists(self, service, mock_uow):
        mock_uow.case_files.get_by_id.return_value = MagicMock(
            case_type=CaseType.DESIGNACION
        )
        mock_uow.designations.get_by_case_file_id.return_value = MagicMock()

        with pytest.raises(DesignationExistsError):
            asyncio.run(
                service.create_designation(
                    case_file_id=str(uuid.uuid4()),
                    position_name="Director",
                )
            )


class TestGetDesignation:
    def test_get_designation_not_found(self, service, mock_uow):
        mock_uow.designations.get_by_case_file_id.return_value = None

        with pytest.raises(DesignationNotFoundError):
            asyncio.run(service.get_designation(str(uuid.uuid4())))

    def test_get_designation_found(self, service, mock_uow):
        mock_uow.designations.get_by_case_file_id.return_value = MagicMock()

        result = asyncio.run(service.get_designation(str(uuid.uuid4())))
        assert result is not None
