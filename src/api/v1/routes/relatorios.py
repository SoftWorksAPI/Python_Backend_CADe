"""
Rotas para geracao de relatorios por IA (PDF e Markdown).

Recebem memorial_descritivo e dados_extracao como JSON no body
e geram relatorios usando a IA (OpenRouter) com auxilio de RAG.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.api.v1.services.ai.pipeline import gerar_relatorio_ia
from src.api.v1.services.report.pdf_generator import gerar_pdf_de_texto
from src.api.v1.services.rag.retriever import buscar_normas_relevantes

router = APIRouter()

OUTPUT_DIR = Path(__file__).parent.parent / "services" / "report" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class RelatorioRequest(BaseModel):
    """Request body para geracao de relatorios por IA."""
    memorial_descritivo: dict[str, Any] = Field(
        ..., description="Memorial descritivo completo (retorno da IA)"
    )
    dados_extracao: dict[str, Any] = Field(
        ..., description="Dados brutos da extracao DXF"
    )
    arquivo_original: str = Field(
        default="arquivo.dxf",
        description="Nome do arquivo DXF original",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/relatorios/markdown",
    summary="Gerar relatorio Markdown via IA",
    description="Gera um relatorio Markdown completo usando IA, com base no memorial descritivo e dados de extracao.",
    response_class=FileResponse,
)
async def gerar_relatorio_markdown(req: RelatorioRequest):
    """Gera relatorio Markdown via IA e retorna como arquivo."""
    start_time = time.time()
    print(f"\n[RELATORIO] Gerando Markdown via IA - arquivo: {req.arquivo_original}")

    # Buscar contexto RAG
    normas_contexto = ""
    try:
        termos = []
        for a in (req.memorial_descritivo.get("ambientes") or [])[:5]:
            if a.get("nome"):
                termos.append(a["nome"])
        dg = req.memorial_descritivo.get("dados_gerais") or {}
        if dg.get("tipo_construcao"):
            termos.append(dg["tipo_construcao"])
        if termos:
            query = " ".join(termos)
            print(f"[RELATORIO] RAG: buscando normas (query: {query[:60]}...)")
            normas_contexto = buscar_normas_relevantes(query=query, k=5)
            print(f"[RELATORIO] RAG: {len(normas_contexto)} chars de normas")
    except Exception as rag_err:
        print(f"[RELATORIO] RAG indisponivel: {rag_err}")

    try:
        print(f"[RELATORIO] Enviando para IA (geracao de MD)...")
        conteudo = gerar_relatorio_ia(
            tipo="md",
            dados_extracao=req.dados_extracao,
            memorial_descritivo=req.memorial_descritivo,
            normas_contexto=normas_contexto,
        )

        # Salvar arquivo
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = Path(req.arquivo_original).stem
        nome_arquivo = f"{nome}_memorial_{ts}.md"
        caminho = OUTPUT_DIR / nome_arquivo
        caminho.write_text(conteudo, encoding="utf-8")

        elapsed = time.time() - start_time
        print(f"[RELATORIO] Markdown gerado com sucesso em {elapsed:.1f}s: {caminho}")

        return FileResponse(
            path=str(caminho),
            media_type="text/markdown",
            filename=nome_arquivo,
        )
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[RELATORIO] ERRO ao gerar Markdown apos {elapsed:.1f}s: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar relatorio Markdown: {str(e)}",
        )


@router.post(
    "/relatorios/pdf",
    summary="Gerar relatorio PDF via IA",
    description="Gera um relatorio PDF profissional usando IA, com base no memorial descritivo e dados de extracao.",
    response_class=FileResponse,
)
async def gerar_relatorio_pdf(req: RelatorioRequest):
    """Gera relatorio PDF via IA e retorna como arquivo."""
    start_time = time.time()
    print(f"\n[RELATORIO] Gerando PDF via IA - arquivo: {req.arquivo_original}")

    # Buscar contexto RAG
    normas_contexto = ""
    try:
        termos = []
        for a in (req.memorial_descritivo.get("ambientes") or [])[:5]:
            if a.get("nome"):
                termos.append(a["nome"])
        dg = req.memorial_descritivo.get("dados_gerais") or {}
        if dg.get("tipo_construcao"):
            termos.append(dg["tipo_construcao"])
        if termos:
            query = " ".join(termos)
            print(f"[RELATORIO] RAG: buscando normas (query: {query[:60]}...)")
            normas_contexto = buscar_normas_relevantes(query=query, k=5)
            print(f"[RELATORIO] RAG: {len(normas_contexto)} chars de normas")
    except Exception as rag_err:
        print(f"[RELATORIO] RAG indisponivel: {rag_err}")

    try:
        print(f"[RELATORIO] Enviando para IA (geracao de texto para PDF)...")
        texto_ia = gerar_relatorio_ia(
            tipo="pdf",
            dados_extracao=req.dados_extracao,
            memorial_descritivo=req.memorial_descritivo,
            normas_contexto=normas_contexto,
        )
        print(f"[RELATORIO] IA retornou {len(texto_ia)} chars, convertendo para PDF...")

        caminho = gerar_pdf_de_texto(texto_ia, req.arquivo_original)

        elapsed = time.time() - start_time
        print(f"[RELATORIO] PDF gerado com sucesso em {elapsed:.1f}s: {caminho}")

        return FileResponse(
            path=caminho,
            media_type="application/pdf",
            filename=Path(caminho).name,
        )
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[RELATORIO] ERRO ao gerar PDF apos {elapsed:.1f}s: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar relatorio PDF: {str(e)}",
        )
