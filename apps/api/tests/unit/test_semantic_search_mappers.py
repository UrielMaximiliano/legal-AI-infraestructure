import uuid
from datetime import UTC, datetime

from legal_ai.adapters.database.semantic_search_mappers import (
    human_evaluation_from_model,
    human_evaluation_to_model,
)
from legal_ai.domain.semantic_search import HumanRetrievalEvaluation


def test_human_evaluation_mapper_is_allowlisted_and_round_trips() -> None:
    now = datetime.now(UTC)
    evaluation = HumanRetrievalEvaluation(
        id=uuid.uuid4(),
        evaluation_run_id=uuid.uuid4(),
        query_id="query-1",
        result_document_id=uuid.uuid4(),
        result_chunk_id=uuid.uuid4(),
        evaluator_id="evaluator-1",
        usefulness_score=4,
        legally_relevant=True,
        dataset_version="005-v1",
        embedding_model="qwen3-embedding:0.6b",
        embedding_dimensions=1024,
        comments="comentario",
        evaluated_at=now,
        created_at=now,
    )
    model = human_evaluation_to_model(evaluation)
    restored = human_evaluation_from_model(model)
    assert restored == evaluation
    assert not hasattr(model, "raw_content")
