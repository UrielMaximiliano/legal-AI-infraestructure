"""Router principal de la API."""

from __future__ import annotations

from fastapi import APIRouter

from legal_ai.api.routes.case_files import router as case_files_router
from legal_ai.api.routes.employees import router as employees_router
from legal_ai.api.routes.health import router as health_router

router = APIRouter()
router.include_router(health_router)
router.include_router(employees_router)
router.include_router(case_files_router)
