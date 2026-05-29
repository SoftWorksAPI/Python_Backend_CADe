"""
Rotas para geracao de relatorios por IA (PDF, Markdown e XLSX).

Recebem memorial_descritivo e dados_extracao como JSON no body
e geram relatorios usando a IA (OpenRouter) com auxilio de RAG.
Retornam JSON com { report: base64, review: markdown }.
"""
from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.v1.services.ai.client import chamar_openrouter
from src.logger import log
from src.api.v1.services.ai.pipeline import gerar_relatorio_ia
from src.api.v1.services.ai.prompts import (
    SYSTEM_PROMPT_REVISAO_RELATORIO,
    build_revisao_prompt,
)
from src.api.v1.services.report.pdf_generator import gerar_pdf_de_texto
from src.api.v1.services.report.xlsx_generator import gerar_relatorio_xlsx
from src.api.v1.services.rag.retriever import buscar_normas_relevantes
from src.api.v1.services.callback import enviar_callback

router = APIRouter()

OUTPUT_DIR = Path(__file__).parent.parent / "services" / "report" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _deletar_arquivo(caminho: str):
    """Deleta um arquivo apos envio (usado como background task)."""
    try:
        Path(caminho).unlink(missing_ok=True)
        log.info("RELATORIO", f"Arquivo temporario deletado: {caminho}")
    except Exception as e:
        log.warn("RELATORIO", f"Nao foi possivel deletar {caminho}: {e}")


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
        log.warn("RELATORIO", "RAG: nenhuma norma encontrada")
        return

    trechos = normas_contexto.split("\n\n---\n\n")
    log.success("RELATORIO", f"RAG: {len(trechos)} trechos de normas encontrados:")
    for i, trecho in enumerate(trechos, 1):
        # Mostrar apenas a primeira linha de cada trecho (cabecalho)
        primeira_linha = trecho.split("\n")[0][:120]
        log.info("RELATORIO", f"RAG   [{i}] {primeira_linha}")


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


def _gerar_revisao_ia(
    memorial_descritivo: dict[str, Any],
    tipo_relatorio: str,
    conteudo_relatorio: str,
) -> str:
    """Gera uma revisao tecnica do relatorio via IA."""
    try:
        prompt = build_revisao_prompt(
            memorial_descritivo=memorial_descritivo,
            tipo_relatorio=tipo_relatorio,
            conteudo_relatorio=conteudo_relatorio,
        )
        revisao = chamar_openrouter(SYSTEM_PROMPT_REVISAO_RELATORIO, prompt)
        log.success("REVISAO", f"Revisao gerada ({len(revisao)} chars)")
        return revisao
    except Exception as e:
        log.warn("REVISAO", f"Falha ao gerar revisao: {e}")
        return f"## Revisao indisponivel\n\nErro ao gerar revisao: {str(e)}"


def _build_json_response(caminho: str, revisao: str, media_type: str) -> JSONResponse:
    """Monta JSONResponse com arquivo em base64 + revisao."""
    file_bytes = Path(caminho).read_bytes()
    report_b64 = base64.b64encode(file_bytes).decode("utf-8")

    return JSONResponse(
        content={
            "report": report_b64,
            "review": revisao,
        },
        media_type="application/json",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _gerar_markdown_sync(req: RelatorioRequest, background_tasks: BackgroundTasks):
    """Corpo sync da geracao de Markdown (RAG + LLM + arquivo + revisao)."""
    start_time = time.time()
    log.separator("RELATORIO")
    log.info("RELATORIO", f"Gerando Markdown via IA - arquivo: {req.arquivo_original}")

    normas_contexto = ""
    try:
        query = _build_relatorio_rag_query(req.memorial_descritivo, req.dados_extracao)
        log.info("RELATORIO", f"RAG: buscando normas (query: {query[:100]})")
        normas_contexto = buscar_normas_relevantes(query=query, k=5)
        _log_rag_resultados(normas_contexto)
    except Exception as rag_err:
        log.warn("RELATORIO", f"RAG indisponivel: {rag_err}")

    try:
        log.info("RELATORIO", "Enviando para IA (geracao de MD)...")
        conteudo = gerar_relatorio_ia(
            tipo="md",
            dados_extracao=req.dados_extracao,
            memorial_descritivo=req.memorial_descritivo,
            normas_contexto=normas_contexto,
        )

        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = Path(req.arquivo_original).stem
        nome_arquivo = f"{nome}_memorial_{ts}.md"
        caminho = OUTPUT_DIR / nome_arquivo
        caminho.write_text(conteudo, encoding="utf-8")

        revisao = _gerar_revisao_ia(req.memorial_descritivo, "Markdown", conteudo)

        background_tasks.add_task(_deletar_arquivo, str(caminho))

        elapsed = time.time() - start_time
        log.success("RELATORIO", f"Markdown gerado com sucesso em {elapsed:.1f}s: {caminho}")

        return _build_json_response(str(caminho), revisao, "text/markdown")
    except Exception as e:
        elapsed = time.time() - start_time
        log.error("RELATORIO", f"Erro ao gerar Markdown apos {elapsed:.1f}s: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar relatorio Markdown: {str(e)}",
        )


@router.post(
    "/relatorios/markdown",
    summary="Gerar relatorio Markdown via IA",
    description="Gera um relatorio Markdown completo usando IA, com base no memorial descritivo e dados de extracao.",
)
async def gerar_relatorio_markdown(req: RelatorioRequest, background_tasks: BackgroundTasks, callback_url: str | None = Header(None, alias="X-Callback-URL"), report_id: int | None = Header(None, alias="X-Report-ID")):
    """Gera relatorio Markdown via IA e retorna JSON com report (base64) + review."""
    if callback_url:
        def _bg():
            try:
                resp = _gerar_markdown_sync(req, background_tasks)
                body = resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)
                import json
                data = json.loads(body) if isinstance(body, str) else body
                enviar_callback(callback_url, {"report_id": report_id, "sucesso": True, "report_base64": data.get("report"), "review": data.get("review")})
            except Exception as e:
                enviar_callback(callback_url, {"report_id": report_id, "sucesso": False, "erro": str(e)})
        asyncio.create_task(asyncio.to_thread(_bg))
        return {"status": "gerando", "report_id": report_id}
    return await asyncio.to_thread(_gerar_markdown_sync, req, background_tasks)


def _gerar_pdf_sync(req: RelatorioRequest, background_tasks: BackgroundTasks):
    """Corpo sync da geracao de PDF (RAG + LLM + PDF + revisao)."""
    start_time = time.time()
    log.separator("RELATORIO")
    log.info("RELATORIO", f"Gerando PDF via IA - arquivo: {req.arquivo_original}")

    normas_contexto = ""
    try:
        query = _build_relatorio_rag_query(req.memorial_descritivo, req.dados_extracao)
        log.info("RELATORIO", f"RAG: buscando normas (query: {query[:100]})")
        normas_contexto = buscar_normas_relevantes(query=query, k=5)
        _log_rag_resultados(normas_contexto)
    except Exception as rag_err:
        log.warn("RELATORIO", f"RAG indisponivel: {rag_err}")

    try:
        log.info("RELATORIO", "Enviando para IA (geracao de texto para PDF)...")
        texto_ia = gerar_relatorio_ia(
            tipo="pdf",
            dados_extracao=req.dados_extracao,
            memorial_descritivo=req.memorial_descritivo,
            normas_contexto=normas_contexto,
        )
        log.info("RELATORIO", f"IA retornou {len(texto_ia)} chars, convertendo para PDF...")

        caminho = gerar_pdf_de_texto(texto_ia, req.arquivo_original)

        revisao = _gerar_revisao_ia(req.memorial_descritivo, "PDF", texto_ia)

        background_tasks.add_task(_deletar_arquivo, str(caminho))

        elapsed = time.time() - start_time
        log.success("RELATORIO", f"PDF gerado com sucesso em {elapsed:.1f}s: {caminho}")

        return _build_json_response(caminho, revisao, "application/pdf")
    except Exception as e:
        elapsed = time.time() - start_time
        log.error("RELATORIO", f"Erro ao gerar PDF apos {elapsed:.1f}s: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar relatorio PDF: {str(e)}",
        )


@router.post(
    "/relatorios/pdf",
    summary="Gerar relatorio PDF via IA",
    description="Gera um relatorio PDF profissional usando IA, com base no memorial descritivo e dados de extracao.",
)
async def gerar_relatorio_pdf(req: RelatorioRequest, background_tasks: BackgroundTasks, callback_url: str | None = Header(None, alias="X-Callback-URL"), report_id: int | None = Header(None, alias="X-Report-ID")):
    """Gera relatorio PDF via IA e retorna JSON com report (base64) + review."""
    if callback_url:
        def _bg():
            try:
                resp = _gerar_pdf_sync(req, background_tasks)
                body = resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)
                import json
                data = json.loads(body) if isinstance(body, str) else body
                enviar_callback(callback_url, {"report_id": report_id, "sucesso": True, "report_base64": data.get("report"), "review": data.get("review")})
            except Exception as e:
                enviar_callback(callback_url, {"report_id": report_id, "sucesso": False, "erro": str(e)})
        asyncio.create_task(asyncio.to_thread(_bg))
        return {"status": "gerando", "report_id": report_id}
    return await asyncio.to_thread(_gerar_pdf_sync, req, background_tasks)


def _gerar_xlsx_sync(req: RelatorioRequest, background_tasks: BackgroundTasks):
    """Corpo sync da geracao de XLSX (RAG + LLM + XLSX + revisao)."""
    start_time = time.time()
    log.separator("RELATORIO")
    log.info("RELATORIO", f"Gerando XLSX via IA - arquivo: {req.arquivo_original}")

    normas_contexto = ""
    try:
        query = _build_relatorio_rag_query(req.memorial_descritivo, req.dados_extracao)
        log.info("RELATORIO", f"RAG: buscando normas (query: {query[:100]})")
        normas_contexto = buscar_normas_relevantes(query=query, k=5)
        _log_rag_resultados(normas_contexto)
    except Exception as rag_err:
        log.warn("RELATORIO", f"RAG indisponivel: {rag_err}")

    try:
        log.info("RELATORIO", "Enviando para IA (geracao de XLSX)...")
        caminho, revisao = gerar_relatorio_xlsx(
            memorial_descritivo=req.memorial_descritivo,
            dados_extracao=req.dados_extracao,
            arquivo_original=req.arquivo_original,
            normas_contexto=normas_contexto,
        )

        background_tasks.add_task(_deletar_arquivo, str(caminho))

        elapsed = time.time() - start_time
        log.success("RELATORIO", f"XLSX gerado com sucesso em {elapsed:.1f}s: {caminho}")

        return _build_json_response(caminho, revisao, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        elapsed = time.time() - start_time
        log.error("RELATORIO", f"Erro ao gerar XLSX apos {elapsed:.1f}s: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar relatorio XLSX: {str(e)}",
        )


@router.post(
    "/relatorios/xlsx",
    summary="Gerar relatorio XLSX via IA",
    description="Gera um relatorio XLSX (memorial descritivo com 15 abas) usando IA, com base no memorial descritivo e dados de extracao.",
)
async def gerar_relatorio_xlsx_endpoint(req: RelatorioRequest, background_tasks: BackgroundTasks, callback_url: str | None = Header(None, alias="X-Callback-URL"), report_id: int | None = Header(None, alias="X-Report-ID")):
    """Gera relatorio XLSX via IA e retorna JSON com report (base64) + review."""
    if callback_url:
        def _bg():
            try:
                resp = _gerar_xlsx_sync(req, background_tasks)
                body = resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)
                import json
                data = json.loads(body) if isinstance(body, str) else body
                enviar_callback(callback_url, {"report_id": report_id, "sucesso": True, "report_base64": data.get("report"), "review": data.get("review")})
            except Exception as e:
                enviar_callback(callback_url, {"report_id": report_id, "sucesso": False, "erro": str(e)})
        asyncio.create_task(asyncio.to_thread(_bg))
        return {"status": "gerando", "report_id": report_id}
    return await asyncio.to_thread(_gerar_xlsx_sync, req, background_tasks)
