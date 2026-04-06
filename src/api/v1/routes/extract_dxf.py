from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from src.api.v1.schemas.dxf_schemas import DXFExtractRequest, DXFExtractResponse
from src.api.v1.services.extract_dxf_service import (
    DXFExtractionError,
    extract_dxf_from_upload,
    _generate_ai_prompt_string,
    generate_ai_report,
)


class AIPromptResponse(BaseModel):
    arquivo: str
    ai_prompt: str


class AIReportResponse(BaseModel):
    arquivo: str
    relatorio: str


router = APIRouter()


@router.post(
    "/extract/dxf",
    response_model=AIReportResponse,
    summary="Extrai informacoes de um arquivo DXF e gera relatório com IA",
    description="Recebe um arquivo DXF, extrai os dados, cria um prompt e gera um relatório completo usando IA.",
)
async def extract_dxf_content(
    file: Annotated[
        UploadFile,
        File(..., description="Arquivo DXF para extracao"),
    ],
    payload: Annotated[
        DXFExtractRequest,
        Depends(DXFExtractRequest.as_form),
    ],

) -> AIReportResponse:

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome do arquivo nao informado.",
        )

    if not file.filename.lower().endswith(".dxf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas arquivos .dxf sao aceitos.",
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo vazio.",
        )

    try:
        response_data = extract_dxf_from_upload(
            filename=file.filename,
            content=content,
            options=payload,
        )
        
        ai_prompt = _generate_ai_prompt_string(response_data)
        
        relatorio = await generate_ai_report(ai_prompt)
        
        print("\n" + "="*80)
        print(f"📄 RELATÓRIO GERADO - {file.filename}")
        print("="*80)
        print(relatorio)
        print("="*80 + "\n")
        
        return AIReportResponse(
            arquivo=file.filename,
            relatorio=relatorio,
        )

    except DXFExtractionError as exc:
        
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/extract/dxf/prompt",
    response_model=AIPromptResponse,
    summary="Extrai informacoes de um arquivo DXF e gera prompt de IA",
    description="Recebe um arquivo DXF, extrai os dados e retorna um prompt completo para geração de relatório com IA.",
)
async def extract_dxf_prompt(
    file: Annotated[
        UploadFile,
        File(..., description="Arquivo DXF para extracao"),
    ],
    payload: Annotated[
        DXFExtractRequest,
        Depends(DXFExtractRequest.as_form),
    ],

) -> AIPromptResponse:

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome do arquivo nao informado.",
        )

    if not file.filename.lower().endswith(".dxf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas arquivos .dxf sao aceitos.",
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo vazio.",
        )

    try:
        response_data = extract_dxf_from_upload(
            filename=file.filename,
            content=content,
            options=payload,
        )
        
        ai_prompt = _generate_ai_prompt_string(response_data)
        
        return AIPromptResponse(
            arquivo=file.filename,
            ai_prompt=ai_prompt,
        )

    except DXFExtractionError as exc:
        
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc