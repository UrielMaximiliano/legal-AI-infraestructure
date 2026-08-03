"""Draft application service."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.generation_context import GenerationContext
from legal_ai.application.ollama_client import OllamaClient, OllamaError
from legal_ai.application.prompt_builder import PromptBuilder
from legal_ai.domain.draft import Draft, DraftTransition, can_transition
from legal_ai.domain.enums import DraftStatus, GenerationStatus, TransitionAction
from legal_ai.domain.generation_attempt import GenerationAttempt


class DraftNotFoundError(Exception):
    """Draft not found."""

    def __init__(self, draft_id: str) -> None:
        self.draft_id = draft_id
        super().__init__(f"Draft not found: {draft_id}")


class DraftReadOnlyError(Exception):
    """Draft is in a read-only state."""

    def __init__(self, draft_id: str, status: str) -> None:
        self.draft_id = draft_id
        self.status = status
        super().__init__(f"Draft is read-only: {draft_id} (status: {status})")


class InvalidDraftTransitionError(Exception):
    """Invalid draft state transition."""

    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition: {from_status} -> {to_status}")


class ConcurrentModificationError(Exception):
    """Concurrent modification detected."""

    def __init__(self, resource_id: str) -> None:
        self.resource_id = resource_id
        super().__init__(f"Concurrent modification: {resource_id}")


class TemplateNotFoundError(Exception):
    """Template not found."""

    def __init__(self, template_id: str) -> None:
        self.template_id = template_id
        super().__init__(f"Template not found: {template_id}")


class TemplateInactiveError(Exception):
    """Template is inactive."""

    def __init__(self, template_id: str) -> None:
        self.template_id = template_id
        super().__init__(f"Template is inactive: {template_id}")


class CaseFileNotFoundError(Exception):
    """Case file not found."""

    def __init__(self, case_file_id: str) -> None:
        self.case_file_id = case_file_id
        super().__init__(f"Case file not found: {case_file_id}")


class IdempotencyKeyMismatchError(Exception):
    """Idempotency key exists with different payload."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Idempotency key mismatch: {key}")


class GenerationInProgressError(Exception):
    """Generation already in progress for this idempotency key."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Generation in progress: {key}")


class DraftAlreadyApprovedError(Exception):
    """Draft has already been approved and cannot be approved again."""

    def __init__(self, draft_id: str) -> None:
        self.draft_id = draft_id
        super().__init__(f"Draft already approved: {draft_id}")


class ContentTooLargeError(Exception):
    """Content exceeds size limit."""

    def __init__(self, size: int, limit: int = 100 * 1024) -> None:
        self.size = size
        self.limit = limit
        super().__init__(f"Content too large: {size} bytes (limit: {limit})")


class DraftService:
    """Service handling draft business operations."""

    IDEMPOTENCY_WINDOW = timedelta(hours=24)

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow
        self._context_builder = GenerationContext(uow)
        self._prompt_builder = PromptBuilder()
        self._ollama = OllamaClient()

    @staticmethod
    def _request_hash(
        template_id: str,
        case_file_id: str,
        variables: dict[str, str],
    ) -> str:
        payload = {
            "case_file_id": case_file_id,
            "template_id": template_id,
            "variables": variables,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    async def _find_draft_for_attempt(
        self, case_file_id: uuid.UUID, attempt_id: uuid.UUID
    ) -> Draft | None:
        drafts, _ = await self._uow.drafts.list_by_case_file(
            case_file_id, None, 0, 1000
        )
        expected_attempt_id = str(attempt_id)
        for draft in drafts:
            metadata = draft.context_snapshot.get("metadata")
            if (
                isinstance(metadata, dict)
                and metadata.get("attempt_id") == expected_attempt_id
            ):
                return draft
        return None

    async def generate_draft(
        self,
        template_id: str,
        case_file_id: str,
        variables: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Draft:
        """Generate a new draft using Ollama."""
        # Validate inputs
        tid = uuid.UUID(template_id)
        cf_id = uuid.UUID(case_file_id)

        supplied_variables = variables or {}
        request_hash = self._request_hash(template_id, case_file_id, supplied_variables)

        # Check idempotency before doing any external work.
        if idempotency_key:
            existing = await self._uow.generation_attempts.get_by_idempotency_key(
                idempotency_key
            )
            if (
                existing
                and existing.created_at < datetime.now(UTC) - self.IDEMPOTENCY_WINDOW
            ):
                # Idempotency keys are reusable after the documented 24-hour
                # retention window. Remove the stale attempt before creating a
                # new one so the database uniqueness constraint is respected.
                await self._uow.generation_attempts.delete_by_idempotency_key(
                    idempotency_key
                )
                existing = None
            if existing:
                if existing.prompt_hash != request_hash:
                    raise IdempotencyKeyMismatchError(idempotency_key)
                if existing.status == GenerationStatus.COMPLETED:
                    cached = await self._find_draft_for_attempt(cf_id, existing.id)
                    if cached:
                        return cached
                elif existing.status == GenerationStatus.IN_PROGRESS:
                    raise GenerationInProgressError(idempotency_key)
                elif existing.status == GenerationStatus.FAILED:
                    await self._uow.generation_attempts.delete_by_idempotency_key(
                        idempotency_key
                    )

        # Validate template
        template = await self._uow.templates.get_by_id(tid)
        if not template:
            raise TemplateNotFoundError(template_id)
        if not template.is_active:
            raise TemplateInactiveError(template_id)

        # Validate case file
        case_file = await self._uow.case_files.get_by_id(cf_id)
        if not case_file:
            raise CaseFileNotFoundError(case_file_id)

        # Build context
        context = await self._context_builder.build_context(
            tid, cf_id, supplied_variables
        )
        self._context_builder.validate_variables(template.variables, supplied_variables)
        metadata = context["metadata"]
        if isinstance(metadata, dict):
            metadata["model"] = self._ollama.model

        # Render prompt
        rendered = self._prompt_builder.render_template(template.body_template, context)
        prompt = self._prompt_builder.build_prompt(rendered, context)

        attempt = GenerationAttempt(
            id=uuid.uuid4(),
            case_file_id=cf_id,
            template_id=tid,
            idempotency_key=idempotency_key,
            model=self._ollama.model,
            prompt_hash=request_hash,
            prompt_content=prompt,
            status=GenerationStatus.IN_PROGRESS,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        await self._uow.generation_attempts.create(attempt)
        await self._uow.commit()

        # Call Ollama (outside transaction)
        try:
            ollama_response = await self._ollama.generate(prompt)
        except OllamaError as exc:
            attempt.status = GenerationStatus.FAILED
            attempt.error_code = exc.error_code
            attempt.error_message = str(exc)
            attempt.completed_at = datetime.now(UTC)
            await self._uow.generation_attempts.update(attempt)
            await self._uow.commit()
            raise

        # Create draft
        if isinstance(metadata, dict):
            metadata["attempt_id"] = str(attempt.id)
        draft = Draft(
            id=uuid.uuid4(),
            template_id=tid,
            case_file_id=cf_id,
            title=f"Borrador - {template.name}",
            content=ollama_response.content,
            status=DraftStatus.GENERADO,
            version=1,
            generation_number=1,
            context_snapshot=context,
            context_hash=GenerationContext.compute_hash(context),
            variables_used=supplied_variables,
            request_id=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await self._uow.drafts.create(draft)

        # Update attempt
        attempt.status = GenerationStatus.COMPLETED
        attempt.completed_at = datetime.now(UTC)
        await self._uow.generation_attempts.update(attempt)
        await self._uow.commit()

        return draft

    async def get_draft(self, draft_id: str) -> Draft:
        """Get draft by ID."""
        draft = await self._uow.drafts.get_by_id(uuid.UUID(draft_id))
        if not draft:
            raise DraftNotFoundError(draft_id)
        return draft

    async def list_drafts(
        self,
        case_file_id: str,
        status: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Draft], int]:
        """List drafts for a case file."""
        parsed_case_file_id = uuid.UUID(case_file_id)
        if not await self._uow.case_files.get_by_id(parsed_case_file_id):
            raise CaseFileNotFoundError(case_file_id)
        return await self._uow.drafts.list_by_case_file(
            parsed_case_file_id, status, skip, limit
        )

    async def edit_content(
        self,
        draft_id: str,
        content: str,
        expected_version: int,
    ) -> Draft:
        """Edit draft content with optimistic locking."""
        if len(content.encode()) > 100 * 1024:
            raise ContentTooLargeError(len(content.encode()))

        draft = await self._uow.drafts.get_by_id(uuid.UUID(draft_id))
        if not draft:
            raise DraftNotFoundError(draft_id)

        if draft.version != expected_version:
            raise ConcurrentModificationError(draft_id)

        if draft.status not in (DraftStatus.EN_REVISION, DraftStatus.RECHAZADO):
            raise DraftReadOnlyError(draft_id, draft.status)

        draft.content = content
        result = await self._uow.drafts.update_with_optimistic_lock(
            draft, expected_version
        )
        if not result:
            raise ConcurrentModificationError(draft_id)

        # Record transition
        transition = DraftTransition(
            id=uuid.uuid4(),
            draft_id=uuid.UUID(draft_id),
            from_status=draft.status,
            to_status=draft.status,
            action=TransitionAction.EDIT_CONTENT,
            created_at=datetime.now(UTC),
        )
        await self._uow.draft_transitions.create(transition)
        await self._uow.commit()

        return result

    async def transition_draft(
        self,
        draft_id: str,
        action: TransitionAction,
        expected_version: int,
        observations: str | None = None,
    ) -> Draft:
        """Transition draft state with optimistic locking."""
        draft = await self._uow.drafts.get_by_id(uuid.UUID(draft_id))
        if not draft:
            raise DraftNotFoundError(draft_id)

        if draft.version != expected_version:
            raise ConcurrentModificationError(draft_id)

        from_status = DraftStatus(draft.status)

        if action == TransitionAction.SEND_TO_REVIEW:
            to_status = DraftStatus.EN_REVISION
        elif action == TransitionAction.APPROVE:
            to_status = DraftStatus.APROBADO
        elif action == TransitionAction.REJECT:
            to_status = DraftStatus.RECHAZADO
        else:
            raise InvalidDraftTransitionError(draft.status, action)

        # Idempotent: if already in target status, return current
        if from_status == to_status:
            if (
                action == TransitionAction.APPROVE
                and from_status == DraftStatus.APROBADO
            ):
                raise DraftAlreadyApprovedError(draft_id)
            return draft

        if not can_transition(from_status, to_status):
            raise InvalidDraftTransitionError(draft.status, to_status)

        result = await self._uow.drafts.update_status(
            uuid.UUID(draft_id), to_status, expected_version
        )
        if not result:
            raise ConcurrentModificationError(draft_id)

        # Record transition
        transition = DraftTransition(
            id=uuid.uuid4(),
            draft_id=uuid.UUID(draft_id),
            from_status=from_status,
            to_status=to_status,
            action=action,
            observations=observations,
            created_at=datetime.now(UTC),
        )
        await self._uow.draft_transitions.create(transition)
        await self._uow.commit()

        return result

    async def regenerate_draft(
        self,
        draft_id: str,
        expected_version: int,
        observations: str | None = None,
    ) -> Draft:
        """Regenerate a draft with Ollama."""
        original = await self._uow.drafts.get_by_id(uuid.UUID(draft_id))
        if not original:
            raise DraftNotFoundError(draft_id)

        if original.version != expected_version:
            raise ConcurrentModificationError(draft_id)

        # Can only regenerate from EN_REVISION or RECHAZADO
        if original.status not in (
            DraftStatus.EN_REVISION,
            DraftStatus.RECHAZADO,
        ):
            raise InvalidDraftTransitionError(original.status, "regenerate")

        # Get current active template
        template = await self._uow.templates.get_by_id(original.template_id)
        if not template:
            raise TemplateNotFoundError(str(original.template_id))

        # Build fresh context
        context = await self._context_builder.build_context(
            original.template_id, original.case_file_id, original.variables_used
        )
        self._context_builder.validate_variables(
            template.variables, original.variables_used
        )

        # Render prompt
        rendered = self._prompt_builder.render_template(template.body_template, context)
        prompt = self._prompt_builder.build_prompt(rendered, context)

        attempt = GenerationAttempt(
            id=uuid.uuid4(),
            case_file_id=original.case_file_id,
            template_id=original.template_id,
            idempotency_key=None,
            model=self._ollama.model,
            prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
            prompt_content=prompt,
            status=GenerationStatus.IN_PROGRESS,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        await self._uow.generation_attempts.create(attempt)
        await self._uow.commit()

        # Call Ollama
        try:
            ollama_response = await self._ollama.generate(prompt)
        except OllamaError as exc:
            attempt.status = GenerationStatus.FAILED
            attempt.error_code = exc.error_code
            attempt.error_message = str(exc)
            attempt.completed_at = datetime.now(UTC)
            await self._uow.generation_attempts.update(attempt)
            await self._uow.commit()
            raise

        # Create new draft
        metadata = context.get("metadata")
        if isinstance(metadata, dict):
            metadata["attempt_id"] = str(attempt.id)
        new_draft = Draft(
            id=uuid.uuid4(),
            template_id=original.template_id,
            case_file_id=original.case_file_id,
            title=f"Borrador - {template.name}",
            content=ollama_response.content,
            status=DraftStatus.GENERADO,
            version=1,
            generation_number=original.generation_number + 1,
            context_snapshot=context,
            context_hash=GenerationContext.compute_hash(context),
            variables_used=original.variables_used,
            parent_draft_id=original.id,
            request_id=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await self._uow.drafts.create(new_draft)

        # Mark original as SUPERSEDED
        from_status = original.status
        original.status = DraftStatus.SUPERSEDED
        original.observations = observations
        updated_original = await self._uow.drafts.update(original, expected_version)
        if not updated_original:
            await self._uow.rollback()
            raise ConcurrentModificationError(draft_id)

        # Record transition on original
        transition = DraftTransition(
            id=uuid.uuid4(),
            draft_id=original.id,
            from_status=from_status,
            to_status=DraftStatus.SUPERSEDED,
            action=TransitionAction.SEND_TO_REVIEW,
            observations=observations,
            created_at=datetime.now(UTC),
        )
        await self._uow.draft_transitions.create(transition)

        # Update attempt
        attempt.status = GenerationStatus.COMPLETED
        attempt.completed_at = datetime.now(UTC)
        await self._uow.generation_attempts.update(attempt)
        await self._uow.commit()

        return new_draft

    async def get_history(self, draft_id: str) -> list[DraftTransition]:
        """Get transition history for a draft."""
        draft = await self._uow.drafts.get_by_id(uuid.UUID(draft_id))
        if not draft:
            raise DraftNotFoundError(draft_id)
        return await self._uow.draft_transitions.list_by_draft(uuid.UUID(draft_id))
