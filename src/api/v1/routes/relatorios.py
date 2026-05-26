"""
Rotas para geracao de relatorios por IA (PDF e Markdown).

Recebem memorial_descritivo e dados_extracao como JSON no body
e geram relatorios usando a IA (OpenRouter) com auxilio de RAG.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.api.v1.services.ai.pipeline import gerar_relatorio_ia
from src.api.v1.services.report.pdf_generator import gerar_pdf_de_texto
from src.api.v1.services.report.xlsx_generator import gerar_relatorio_xlsx
from src.api.v1.services.rag.retriever import buscar_normas_relevantes

router = APIRouter()

OUTPUT_DIR = Path(__file__).parent.parent / "services" / "report" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _deletar_arquivo(caminho: str):
    """Deleta um arquivo apos envio (usado como background task)."""
    try:
        Path(caminho).unlink(missing_ok=True)
        print(f"[RELATORIO] Arquivo temporario deletado: {caminho}")
    except Exception as e:
        print(f"[RELATORIO] Aviso: nao foi possivel deletar {caminho}: {e}")


def _build_relatorio_rag_query(
    memorial_descritivo: dict[str, Any],
    dados_extracao: dict[str, Any],
) -> str:
    """Monta uma query RAG rica a partir do memorial + dados de extracao."""
    termos: list[str] = []

    # Ambientes
    for a in (memorial_descritivo.get("ambientes") or [])[:5]:
        if a.get("nome"):
            termos.append(a["nome"])

    # Dados gerais
    dg = memorial_descritivo.get("dados_gerais") or {}
    if dg.get("tipo_construcao"):
        termos.append(dg["tipo_construcao"])
    desc = dg.get("descricao_geral", "")
    if desc:
        termos.append(" ".join(desc.split()[:10]))

    # Observacoes tecnicas (até 3)
    for obs in (memorial_descritivo.get("observacoes_tecnicas") or [])[:3]:
        if obs:
            termos.append(" ".join(obs.split()[:8]))

    # Inconsistencias (até 3)
    for inc in (memorial_descritivo.get("inconsistencias_detectadas") or [])[:3]:
        if inc:
            termos.append(" ".join(inc.split()[:8]))

    # Elementos estruturais (chaves com valor)
    elem = memorial_descritivo.get("elementos_estruturais") or {}
    for chave, valor in elem.items():
        if valor and str(valor) not in ("", "nao identificado na planta"):
            termos.append(chave)

    # Instalacoes (chaves)
    inst = memorial_descritivo.get("instalacoes") or {}
    for chave in inst.keys():
        termos.append(chave)

    # Textos do DXF (até 5)
    for txt in (dados_extracao.get("textos") or [])[:5]:
        texto = txt.get("texto", "").strip()
        if len(texto) > 3:
            termos.append(texto)

    # Disciplinas do DXF
    disciplinas = set()
    for el in (dados_extracao.get("elementos") or []):
        if el.get("disciplina") and el["disciplina"] != "ARQUITETONICO":
            disciplinas.add(el["disciplina"].lower())
    if disciplinas:
        termos.append(" ".join(sorted(disciplinas)))

    query = " ".join(termos).strip()
    return query[:500] if query else "normas tecnicas construcao civil"


def _log_rag_resultados(normas_contexto: str):
    """Loga os resultados do RAG encontrados."""
    if not normas_contexto:
        print(f"[RELATORIO] RAG: nenhuma norma encontrada")
        return

    trechos = normas_contexto.split("\n\n---\n\n")
    print(f"[RELATORIO] RAG: {len(trechos)} trechos de normas encontrados:")
    for i, trecho in enumerate(trechos, 1):
        # Mostrar apenas a primeira linha de cada trecho (cabecalho)
        primeira_linha = trecho.split("\n")[0][:120]
        print(f"[RELATORIO] RAG   [{i}] {primeira_linha}")


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
async def gerar_relatorio_markdown(req: RelatorioRequest, background_tasks: BackgroundTasks):
    """Gera relatorio Markdown via IA e retorna como arquivo."""
    start_time = time.time()
    print(f"\n[RELATORIO] Gerando Markdown via IA - arquivo: {req.arquivo_original}")

    # Buscar contexto RAG com query rica
    normas_contexto = ""
    try:
        query = _build_relatorio_rag_query(req.memorial_descritivo, req.dados_extracao)
        print(f"[RELATORIO] RAG: buscando normas (query: {query[:100]})")
        normas_contexto = buscar_normas_relevantes(query=query, k=5)
        _log_rag_resultados(normas_contexto)
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

        # Deletar apos envio
        background_tasks.add_task(_deletar_arquivo, str(caminho))

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
async def gerar_relatorio_pdf(req: RelatorioRequest, background_tasks: BackgroundTasks):
    """Gera relatorio PDF via IA e retorna como arquivo."""
    start_time = time.time()
    print(f"\n[RELATORIO] Gerando PDF via IA - arquivo: {req.arquivo_original}")

    # Buscar contexto RAG com query rica
    normas_contexto = ""
    try:
        query = _build_relatorio_rag_query(req.memorial_descritivo, req.dados_extracao)
        print(f"[RELATORIO] RAG: buscando normas (query: {query[:100]})")
        normas_contexto = buscar_normas_relevantes(query=query, k=5)
        _log_rag_resultados(normas_contexto)
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

        # Deletar apos envio
        background_tasks.add_task(_deletar_arquivo, str(caminho))

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


@router.post(
    "/relatorios/xlsx",
    summary="Gerar relatorio XLSX via IA",
    description="Gera um relatorio XLSX (memorial descritivo com 15 abas) usando IA, com base no memorial descritivo e dados de extracao.",
    response_class=FileResponse,
)
async def gerar_relatorio_xlsx_endpoint(req: RelatorioRequest, background_tasks: BackgroundTasks):
    """Gera relatorio XLSX via IA e retorna como arquivo."""
    start_time = time.time()
    print(f"\n[RELATORIO] Gerando XLSX via IA - arquivo: {req.arquivo_original}")

    # Buscar contexto RAG com query rica
    normas_contexto = ""
    try:
        query = _build_relatorio_rag_query(req.memorial_descritivo, req.dados_extracao)
        print(f"[RELATORIO] RAG: buscando normas (query: {query[:100]})")
        normas_contexto = buscar_normas_relevantes(query=query, k=5)
        _log_rag_resultados(normas_contexto)
    except Exception as rag_err:
        print(f"[RELATORIO] RAG indisponivel: {rag_err}")

    try:
        print(f"[RELATORIO] Enviando para IA (geracao de XLSX)...")
        caminho = gerar_relatorio_xlsx(
            memorial_descritivo=req.memorial_descritivo,
            dados_extracao=req.dados_extracao,
            arquivo_original=req.arquivo_original,
            normas_contexto=normas_contexto,
        )

        # Deletar apos envio
        background_tasks.add_task(_deletar_arquivo, str(caminho))

        elapsed = time.time() - start_time
        print(f"[RELATORIO] XLSX gerado com sucesso em {elapsed:.1f}s: {caminho}")

        return FileResponse(
            path=caminho,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=Path(caminho).name,
        )
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[RELATORIO] ERRO ao gerar XLSX apos {elapsed:.1f}s: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar relatorio XLSX: {str(e)}",
        )
