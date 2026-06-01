import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel

from src.api.v1.schemas.dxf_schemas import DXFExtractRequest, DXFExtractResponse
from src.api.v1.services.extract_dxf_service import (
    DXFExtractionError,
    extract_dxf_from_upload,
    generate_ai_prompt_string,
)
from src.api.v1.services.ai.pipeline import executar_analise_dxf
from src.api.v1.services.ai.client import chamar_ia
from src.api.v1.services.ai.config_fetcher import fetch_ai_config
from src.api.v1.services.callback import enviar_callback
from src.api.v1.dependencies import verify_api_key


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


class RevisaoResponse(BaseModel):
    revisado: bool | None = None
    status: str | None = None
    problemas: list[str] | None = None
    sugestao: str | None = None
    tentativas: int | None = None


class MemorialResponse(BaseModel):
    arquivo: str
    sucesso: bool
    memorial_descritivo: dict[str, Any] | None = None
    dados_extracao: dict[str, Any] | None = None
    confianca: str | None = None
    num_inconsistencias: int | None = None
    relatorio_md: str | None = None
    relatorio_pdf: str | None = None
    revisao: RevisaoResponse | None = None
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
    dependencies=[Depends(verify_api_key)],
)
async def ai_health_check():
    config = fetch_ai_config()
    provider = config.get("provider", "openrouter")
    model = config.get("model", "desconhecido")

    try:
        resposta = await asyncio.to_thread(
            chamar_ia,
            system_prompt="Responda com uma unica palavra.",
            user_prompt="Diga 'online' se voce esta funcionando.",
        )
        return {"status": "online", "provider": provider, "modelo": model, "resposta": resposta.strip()}
    except ValueError as exc:
        return {"status": "erro_config", "provider": provider, "modelo": model, "resposta": None, "erro": str(exc)}
    except Exception as exc:
        return {"status": "erro_conexao", "provider": provider, "modelo": model, "resposta": None, "erro": str(exc)}


# ---------------------------------------------------------------------------
# POST /v1/extract/dxf — Pipeline completo COM IA
# ---------------------------------------------------------------------------

def _process_pipeline_background(callback_url: str, filename: str, content: bytes, options: DXFExtractRequest, file_id: int | None):
    """Processa pipeline em background e envia resultado via callback."""
    from src.logger import log
    try:
        resultado = executar_analise_dxf(filename=filename, content=content, options=options)
        enviar_callback(callback_url, {
            "file_id": file_id,
            "sucesso": resultado.get("sucesso", False),
            "memorial_descritivo": resultado.get("memorial_descritivo"),
            "dados_extracao": resultado.get("dados_extracao"),
            "confianca": resultado.get("confianca"),
            "num_inconsistencias": resultado.get("num_inconsistencias"),
            "erro": resultado.get("erro"),
        })
    except Exception as e:
        log.error("PIPELINE", f"Erro no background: {e}")
        try:
            enviar_callback(callback_url, {"file_id": file_id, "sucesso": False, "erro": str(e)})
        except Exception:
            pass


@router.post(
    "/extract/dxf",
    summary="Extracao + RAG + LLM: extrai DXF e gera JSONs (sem relatorios)",
)
async def extract_dxf_memorial(
    file: Annotated[UploadFile, File(..., description="Arquivo DXF para extracao")],
    payload: Annotated[DXFExtractRequest, Depends(DXFExtractRequest.as_form)],
    background_tasks: BackgroundTasks = BackgroundTasks(),
    callback_url: str | None = Header(None, alias="X-Callback-URL"),
    file_id: int | None = Header(None, alias="X-File-ID"),
):
    content = await _validate_and_read(file)

    if callback_url:
        # Modo assincrono: processar em background e retornar 202
        background_tasks.add_task(_process_pipeline_background, callback_url, file.filename, content, payload, file_id)
        return {"status": "processando", "mensagem": "Processamento iniciado"}

    # Modo sincrono (fallback/compatibilidade)
    try:
        resultado = await asyncio.to_thread(
            executar_analise_dxf,
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
        def _extrair_raw():
            response_data = extract_dxf_from_upload(filename=file.filename, content=content, options=payload)
            ai_prompt = generate_ai_prompt_string(response_data)
            return response_data, ai_prompt

        response_data, ai_prompt = await asyncio.to_thread(_extrair_raw)
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
        def _extrair_prompt():
            response_data = extract_dxf_from_upload(filename=file.filename, content=content, options=payload)
            ai_prompt = generate_ai_prompt_string(response_data)
            return ai_prompt

        ai_prompt = await asyncio.to_thread(_extrair_prompt)
        return AIPromptResponse(arquivo=file.filename, ai_prompt=ai_prompt)
    except DXFExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
