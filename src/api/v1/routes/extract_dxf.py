from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from src.api.v1.schemas.dxf_schemas import DXFExtractRequest, DXFExtractResponse
from src.api.v1.services.extract_dxf_service import (
    DXFExtractionError,
    extract_dxf_from_upload,
)


router = APIRouter()


@router.post(
    "/extract/dxf",
    response_model=DXFExtractResponse,
    summary="Extrai informacoes de um arquivo DXF",
    description="Recebe um arquivo DXF e retorna os dados extraidos em JSON.",
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

) -> DXFExtractResponse:

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
        return extract_dxf_from_upload(
            filename=file.filename,
            content=content,
            options=payload,
        )

    except DXFExtractionError as exc:
        
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc