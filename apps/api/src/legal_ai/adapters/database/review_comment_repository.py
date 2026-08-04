"""SQLAlchemy review-comment repository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.adapters.database.models import ReviewCommentModel
from legal_ai.domain.enums import CommentSeverity, CommentStatus
from legal_ai.domain.review_comment import ReviewComment


class SQLAlchemyReviewCommentRepository:
    """Persist comments while keeping body and anchors immutable."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, comment_id: UUID) -> ReviewComment | None:
        result = await self._session.execute(
            select(ReviewCommentModel).where(ReviewCommentModel.id == comment_id)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def create(self, comment: ReviewComment) -> ReviewComment:
        model = ReviewCommentModel(
            id=comment.id,
            review_id=comment.review_id,
            parent_comment_id=comment.parent_comment_id,
            draft_version=comment.draft_version,
            author=comment.author,
            severity=comment.severity,
            status=comment.status,
            body=comment.body,
            anchor=comment.anchor,
            version=comment.version,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
            resolved_by=comment.resolved_by,
            resolved_at=comment.resolved_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def update(
        self, comment: ReviewComment, expected_version: int
    ) -> ReviewComment | None:
        result = await self._session.execute(
            update(ReviewCommentModel)
            .where(
                ReviewCommentModel.id == comment.id,
                ReviewCommentModel.version == expected_version,
            )
            .values(
                status=comment.status,
                version=expected_version + 1,
                resolved_by=comment.resolved_by,
                resolved_at=comment.resolved_at,
                updated_at=datetime.now(UTC),
            )
            .returning(ReviewCommentModel)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def list_by_review(
        self, review_id: UUID, offset: int, limit: int
    ) -> tuple[list[ReviewComment], int]:
        filters = [ReviewCommentModel.review_id == review_id]
        total = await self._session.scalar(
            select(func.count()).select_from(ReviewCommentModel).where(*filters)
        )
        result = await self._session.execute(
            select(ReviewCommentModel)
            .where(*filters)
            .order_by(
                ReviewCommentModel.created_at.desc(), ReviewCommentModel.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return [self._to_domain(model) for model in result.scalars().all()], int(
            total or 0
        )

    async def count_open_blocking(self, review_id: UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(ReviewCommentModel)
            .where(
                ReviewCommentModel.review_id == review_id,
                ReviewCommentModel.severity == CommentSeverity.BLOCKING,
                ReviewCommentModel.status == CommentStatus.OPEN,
            )
        )
        return int(total or 0)

    @staticmethod
    def _to_domain(model: ReviewCommentModel) -> ReviewComment:
        return ReviewComment(
            id=model.id,
            review_id=model.review_id,
            draft_version=model.draft_version,
            author=model.author,
            severity=CommentSeverity(model.severity),
            status=CommentStatus(model.status),
            body=model.body,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
            parent_comment_id=model.parent_comment_id,
            anchor=model.anchor,
            resolved_by=model.resolved_by,
            resolved_at=model.resolved_at,
        )
