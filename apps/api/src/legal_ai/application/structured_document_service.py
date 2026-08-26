"""Application service for manual and editable structured documents."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.draft_service import (
    CaseFileNotFoundError,
    DraftNotFoundError,
    TemplateInactiveError,
    TemplateNotFoundError,
)
from legal_ai.domain.draft import Draft, DraftTransition
from legal_ai.domain.draft_document import DraftDocumentVersion
from legal_ai.domain.enums import DraftStatus, ReviewStatus, TransitionAction
from legal_ai.domain.errors import (
    ConcurrentModification004Error,
    DraftDocumentLockedError,
    DraftDocumentNotFoundError,
    StructuredDocumentInvalidError,
)
from legal_ai.schemas.document import LegalDocument


def render_document(document: LegalDocument) -> str:
    """Render structured fields into the legacy text column deterministically."""

    lines = [document.title.strip() or "Borrador"]
    lines.append("VISTO")
    lines.extend(item.text.strip() for item in document.visto if item.text.strip())
    lines.append("CONSIDERANDO")
    lines.extend(
        item.text.strip() for item in document.considerandos if item.text.strip()
    )
    if document.dispositive_intro.strip():
        lines.append(document.dispositive_intro.strip())
    lines.extend(
        f"ARTÍCULO {item.number}. {item.text.strip()}"
        for item in document.articles
        if item.text.strip()
    )
    lines.extend(
        value.strip()
        for value in (document.closing, document.authority, document.signature)
        if value.strip()
    )
    if document.warnings:
        lines.append("ADVERTENCIAS")
        lines.extend(
            f"- {warning.strip()}"
            for warning in document.warnings
            if warning.strip()
        )
    return "\n".join(lines)


class StructuredDocumentService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def create_manual(
        self,
        *,
        template_id: uuid.UUID,
        case_file_id: uuid.UUID,
        variables: dict[str, str],
        document: LegalDocument,
        actor: str,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> Draft:
        if idempotency_key:
            existing = await self._uow.drafts.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                if (
                    request_hash is not None
                    and existing.context_snapshot.get("manual_request_hash")
                    != request_hash
                ):
                    raise StructuredDocumentInvalidError(
                        details={"field": "idempotency_key"}
                    )
                return existing
        template = await self._uow.templates.get_by_id(template_id)
        if template is None:
            raise TemplateNotFoundError(str(template_id))
        if not template.is_active:
            raise TemplateInactiveError(str(template_id))
        if document.document_type != str(template.document_type):
            raise StructuredDocumentInvalidError(details={"field": "document_type"})
        case_file = await self._uow.case_files.get_by_id(case_file_id)
        if case_file is None:
            raise CaseFileNotFoundError(str(case_file_id))
        self._validate_variables(template.variables, variables)

        now = datetime.now(UTC)
        content = render_document(document)
        context: dict[str, object] = {
            "locale": "es-AR",
            "institutional_header": template.organ_emisor or "IMI",
            "creation_mode": "manual",
        }
        if request_hash is not None:
            context["manual_request_hash"] = request_hash
        draft = Draft(
            id=uuid.uuid4(),
            template_id=template_id,
            case_file_id=case_file_id,
            title=document.title.strip() or f"Borrador - {template.name}",
            content=content,
            document=document.model_dump(mode="json"),
            status=DraftStatus.GENERADO,
            version=1,
            generation_number=1,
            context_snapshot=context,
            context_hash=hashlib.sha256(
                json.dumps(context, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            variables_used=variables,
            request_id=None,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        created = await self._uow.drafts.create(draft)
        await self._save_version(created, document, "MANUAL", actor, now)
        return created

    async def get(
        self, draft_id: uuid.UUID
    ) -> tuple[Draft, LegalDocument, DraftDocumentVersion]:
        draft = await self._uow.drafts.get_by_id(draft_id)
        if draft is None:
            raise DraftNotFoundError(str(draft_id))
        version = await self._uow.draft_document_versions.get_current(draft_id)
        if version is None:
            payload = dict(draft.document or {})
            payload.setdefault("schema_version", 1)
            payload.setdefault("document_type", draft.document_type)
            payload.setdefault("title", draft.title)
            payload.setdefault("locale", "es-AR")
            payload.setdefault("institutional_header", "IMI")
            payload.setdefault("dispositive_intro", draft.content or "")
            try:
                document = LegalDocument.model_validate(payload)
            except Exception as exc:
                raise DraftDocumentNotFoundError(
                    details={"draft_id": str(draft_id)}
                ) from exc
            serialized = document.model_dump(mode="json")
            legacy_content = render_document(document)
            version = DraftDocumentVersion(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"legacy:{draft.id}"),
                draft_id=draft.id,
                version=draft.version,
                document=serialized,
                content=legacy_content,
                content_sha256=hashlib.sha256(
                    legacy_content.encode("utf-8")
                ).hexdigest(),
                source="LEGACY",
                edited_by=None,
                created_at=draft.updated_at,
            )
            return draft, document, version
        try:
            document = LegalDocument.model_validate(version.document)
        except Exception as exc:
            raise StructuredDocumentInvalidError() from exc
        return draft, document, version

    async def update(
        self,
        *,
        draft_id: uuid.UUID,
        expected_version: int,
        document: LegalDocument,
        actor: str,
    ) -> tuple[Draft, LegalDocument, DraftDocumentVersion]:
        draft, _current, _version = await self.get(draft_id)
        if draft.is_finalized() or draft.status in (
            DraftStatus.APROBADO,
            DraftStatus.SUPERSEDED,
        ):
            raise DraftDocumentLockedError()
        review = await self._uow.reviews.get_current(draft.id, draft.version)
        if review is not None and review.status in {
            ReviewStatus.OPEN,
            ReviewStatus.SUBMITTED,
        }:
            raise DraftDocumentLockedError()
        if draft.version != expected_version:
            raise ConcurrentModification004Error(details={"draft_id": str(draft_id)})

        template = await self._uow.templates.get_by_id(draft.template_id)
        if template is None:
            raise TemplateNotFoundError(str(draft.template_id))
        if document.document_type != str(template.document_type):
            raise StructuredDocumentInvalidError(details={"field": "document_type"})
        content = render_document(document)
        draft.content = content
        draft.document = document.model_dump(mode="json")
        draft.title = document.title.strip() or draft.title
        updated = await self._uow.drafts.update_with_optimistic_lock(
            draft, expected_version
        )
        if updated is None:
            raise ConcurrentModification004Error(details={"draft_id": str(draft_id)})
        now = datetime.now(UTC)
        version = await self._save_version(updated, document, "HUMAN_EDIT", actor, now)
        await self._uow.draft_transitions.create(
            DraftTransition(
                id=uuid.uuid4(),
                draft_id=updated.id,
                from_status=updated.status,
                to_status=updated.status,
                action=TransitionAction.EDIT_CONTENT,
                performed_by=actor,
                created_at=now,
            )
        )
        return updated, document, version

    async def _save_version(
        self,
        draft: Draft,
        document: LegalDocument,
        source: str,
        actor: str,
        created_at: datetime,
    ) -> DraftDocumentVersion:
        content = render_document(document)
        payload = document.model_dump(mode="json")
        digest = hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()
        return await self._uow.draft_document_versions.create(
            DraftDocumentVersion(
                id=uuid.uuid4(),
                draft_id=draft.id,
                version=draft.version,
                document=payload,
                content=content,
                content_sha256=digest,
                source=source,
                edited_by=actor,
                created_at=created_at,
            )
        )

    @staticmethod
    def _validate_variables(required: list[str], supplied: dict[str, str]) -> None:
        missing = set(required) - set(supplied)
        unexpected = set(supplied) - set(required)
        if missing or unexpected:
            raise StructuredDocumentInvalidError(
                details={"missing": sorted(missing), "unexpected": sorted(unexpected)}
            )
