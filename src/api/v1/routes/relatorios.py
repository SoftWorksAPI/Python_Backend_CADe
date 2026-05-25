"""
Rotas para geracao de relatorios standalone (PDF e Markdown).

Recebem o memorial_descritivo e dados_extracao ja gerados pelo pipeline
e retornam o relatorio correspondente como arquivo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.api.v1.services.report.markdown_generator import gerar_markdown
from src.api.v1.services.report.pdf_generator import gerar_pdf

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RelatorioRequest(BaseModel):
    """Request body para geracao de relatorios standalone."""
    memorial_descritivo: dict[str, Any] = Field(
        ..., description="Memorial descritivo completo (retorno da IA)"
    )
    dados_extracao: dict[str, Any] = Field(
        ..., description="Dados brutos da extracao DXF"
    )
    arquivo_original: str = Field(
        default="arquivo.dxf",
        description="Nome do arquivo DXF original (usado no cabecalho do relatorio)",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/relatorios/pdf",
    summary="Gerar relatorio PDF",
    description="Gera um relatorio PDF profissional a partir do memorial descritivo e dados de extracao ja existentes.",
    response_class=FileResponse,
)
async def gerar_relatorio_pdf(req: RelatorioRequest):
    """Gera PDF e retorna como arquivo para download."""
    try:
        caminho = gerar_pdf(
            memorial=req.memorial_descritivo,
            dados_extracao=req.dados_extracao,
            arquivo_original=req.arquivo_original,
        )
        caminho_path = Path(caminho)
        return FileResponse(
            path=caminho,
            media_type="application/pdf",
            filename=caminho_path.name,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar PDF: {str(e)}",
        )


@router.post(
    "/relatorios/markdown",
    summary="Gerar relatorio Markdown",
    description="Gera um relatorio Markdown a partir do memorial descritivo e dados de extracao ja existentes.",
    response_class=FileResponse,
)
async def gerar_relatorio_markdown(req: RelatorioRequest):
    """Gera Markdown e retorna como arquivo para download."""
    try:
        caminho = gerar_markdown(
            memorial=req.memorial_descritivo,
            dados_extracao=req.dados_extracao,
            arquivo_original=req.arquivo_original,
        )
        caminho_path = Path(caminho)
        return FileResponse(
            path=caminho,
            media_type="text/markdown",
            filename=caminho_path.name,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar Markdown: {str(e)}",
        )
