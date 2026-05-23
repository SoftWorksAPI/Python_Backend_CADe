from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from src.api.v1.schemas.dxf_schemas import DXFExtractRequest, DXFExtractResponse
from src.api.v1.services.extract_dxf_service import (
    DXFExtractionError,
    extract_dxf_from_upload,
    generate_ai_prompt_string,
)
from src.api.v1.services.ai.pipeline import executar_pipeline_memorial
from src.api.v1.services.ai.client import chamar_openrouter
from src.config import OPENROUTER_MODEL


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class AIPromptResponse(BaseModel):
    arquivo: str
    ai_prompt: str


class RawExtractResponse(BaseModel):
    arquivo: str
    dados: DXFExtractResponse
    ai_prompt: str


class MemorialResponse(BaseModel):
    arquivo: str
    sucesso: bool
    memorial_descritivo: dict[str, Any] | None = None
    dados_extracao: dict[str, Any] | None = None
    confianca: str | None = None
    num_inconsistencias: int | None = None
    relatorio_md: str | None = None
    relatorio_pdf: str | None = None
    erro: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _validate_and_read(file: UploadFile) -> bytes:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome do arquivo nao informado.")
    if not file.filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Apenas arquivos .dxf sao aceitos.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
    return content


router = APIRouter()


# ---------------------------------------------------------------------------
# GET /v1/ai/health
# ---------------------------------------------------------------------------

@router.get(
    "/ai/health",
    summary="Testa se a IA esta online e respondendo",
)
async def ai_health_check():
    try:
        resposta = chamar_openrouter(
            system_prompt="Responda com uma unica palavra.",
            user_prompt="Diga 'online' se voce esta funcionando.",
        )
        return {"status": "online", "modelo": OPENROUTER_MODEL, "resposta": resposta.strip()}
    except ValueError as exc:
        return {"status": "erro_config", "modelo": OPENROUTER_MODEL, "resposta": None, "erro": str(exc)}
    except Exception as exc:
        return {"status": "erro_conexao", "modelo": OPENROUTER_MODEL, "resposta": None, "erro": str(exc)}


# ---------------------------------------------------------------------------
# POST /v1/extract/dxf — Pipeline completo COM IA
# ---------------------------------------------------------------------------

@router.post(
    "/extract/dxf",
    response_model=MemorialResponse,
    summary="Pipeline completo: extrai DXF e gera Memorial Descritivo com IA",
)
async def extract_dxf_memorial(
    file: Annotated[UploadFile, File(..., description="Arquivo DXF para extracao")],
    payload: Annotated[DXFExtractRequest, Depends(DXFExtractRequest.as_form)],
) -> MemorialResponse:
    content = await _validate_and_read(file)
    try:
        resultado = executar_pipeline_memorial(
            filename=file.filename,
            content=content,
            options=payload,
        )
        return MemorialResponse(
            arquivo=file.filename,
            sucesso=resultado.get("sucesso", False),
            memorial_descritivo=resultado.get("memorial_descritivo"),
            dados_extracao=resultado.get("dados_extracao"),
            confianca=resultado.get("confianca"),
            num_inconsistencias=resultado.get("num_inconsistencias"),
            relatorio_md=resultado.get("relatorio_md"),
            relatorio_pdf=resultado.get("relatorio_pdf"),
            erro=resultado.get("erro"),
        )
    except DXFExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /v1/extract/dxf/raw — Extracao pura SEM IA
# ---------------------------------------------------------------------------

@router.post(
    "/extract/dxf/raw",
    response_model=RawExtractResponse,
    summary="Extrai dados de um arquivo DXF (sem IA)",
)
async def extract_dxf_raw(
    file: Annotated[UploadFile, File(..., description="Arquivo DXF para extracao")],
    payload: Annotated[DXFExtractRequest, Depends(DXFExtractRequest.as_form)],
) -> RawExtractResponse:
    content = await _validate_and_read(file)
    try:
        response_data = extract_dxf_from_upload(filename=file.filename, content=content, options=payload)
        ai_prompt = generate_ai_prompt_string(response_data)
        return RawExtractResponse(arquivo=file.filename, dados=response_data, ai_prompt=ai_prompt)
    except DXFExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /v1/extract/dxf/prompt — Apenas o prompt
# ---------------------------------------------------------------------------

@router.post(
    "/extract/dxf/prompt",
    response_model=AIPromptResponse,
    summary="Extrai dados e retorna apenas o prompt de IA",
)
async def extract_dxf_prompt(
    file: Annotated[UploadFile, File(..., description="Arquivo DXF para extracao")],
    payload: Annotated[DXFExtractRequest, Depends(DXFExtractRequest.as_form)],
) -> AIPromptResponse:
    content = await _validate_and_read(file)
    try:
        response_data = extract_dxf_from_upload(filename=file.filename, content=content, options=payload)
        ai_prompt = generate_ai_prompt_string(response_data)
        return AIPromptResponse(arquivo=file.filename, ai_prompt=ai_prompt)
    except DXFExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
