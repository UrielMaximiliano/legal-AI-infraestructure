"""Router principal de la API."""

from __future__ import annotations

from fastapi import APIRouter

from legal_ai.api.routes.case_files import router as case_files_router
from legal_ai.api.routes.designation import router as designation_router
from legal_ai.api.routes.drafts import router as drafts_router
from legal_ai.api.routes.employees import router as employees_router
from legal_ai.api.routes.exports import router as exports_router
from legal_ai.api.routes.generation import router as generation_router
from legal_ai.api.routes.health import router as health_router
from legal_ai.api.routes.rag import router as rag_router
from legal_ai.api.routes.reviews import router as reviews_router
from legal_ai.api.routes.semantic_search import router as semantic_search_router
from legal_ai.api.routes.templates import router as templates_router

router = APIRouter()
router.include_router(health_router)
router.include_router(employees_router)
router.include_router(case_files_router)
router.include_router(templates_router)
router.include_router(designation_router)
router.include_router(drafts_router)
router.include_router(generation_router)
router.include_router(reviews_router)
router.include_router(semantic_search_router)
router.include_router(rag_router)
router.include_router(exports_router)
