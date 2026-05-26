from fastapi import APIRouter
from .routes.extract_dxf import router as extract_router
from .routes.rag import router as rag_router
from .routes.relatorios import router as relatorios_router

router = APIRouter()
router.include_router(extract_router, prefix="/v1")
router.include_router(rag_router, prefix="/v1")
router.include_router(relatorios_router, prefix="/v1")
