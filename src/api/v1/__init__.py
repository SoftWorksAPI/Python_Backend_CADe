from fastapi import APIRouter
from .routes.extract_dxf import router as get_cad_content_router

router = APIRouter()
router.include_router(get_cad_content_router, prefix="/v1")