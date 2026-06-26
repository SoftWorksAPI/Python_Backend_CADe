"""
Extrator de texto de reports para uso no chat RAG.

Suporta: PDF (pypdf), XLSX (openpyxl), TXT/MD (leitura direta),
DOCX (python-docx). Outros formatos retornam apenas nome e tipo.
"""
from __future__ import annotations

import os
from typing import Any

from src.logger import log


def extrair_texto_report(file_path: str, file_type: str, title: str = "") -> str:
    """
    Extrai texto de um arquivo de report.

    Args:
        file_path: caminho do arquivo no disco
        file_type: tipo do arquivo (pdf, xlsx, txt, md, docx, json)
        title: titulo do report

    Returns:
        Texto extraido ou descricao do arquivo se nao conseguir extrair
    """
    if not file_path:
        log.warn("REPORT_EXTRACT", f"Caminho vazio para report: {title}")
        return f"[Report: {title or 'sem titulo'} ({file_type}) - caminho vazio]"

    exists = os.path.exists(file_path)
    log.info("REPORT_EXTRACT", f"Report: {title} | file_type: {file_type} | file_path: {file_path} | exists: {exists}")

    if not exists:
        return f"[Report: {title or 'sem titulo'} ({file_type}) - arquivo nao encontrado]"

    file_type = file_type.lower().strip()

    try:
        if file_type == "pdf":
            return _extrair_pdf(file_path, title)
        elif file_type in ("xlsx", "xls"):
            return _extrair_xlsx(file_path, title)
        elif file_type in ("txt", "md"):
            return _extrair_texto(file_path, title)
        elif file_type == "docx":
            return _extrair_docx(file_path, title)
        elif file_type == "json":
            return _extrair_json(file_path, title)
        else:
            return f"[Report: {title or 'sem titulo'} ({file_type}) - formato nao suportado para extracao]"
    except Exception as e:
        return f"[Report: {title or 'sem titulo'} ({file_type}) - erro na extracao: {str(e)[:100]}]"


def _extrair_pdf(file_path: str, title: str) -> str:
    """Extrai texto de PDF usando pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return f"[Report PDF: {title} - pypdf nao instalado]"

    reader = PdfReader(file_path)
    textos = []
    for i, page in enumerate(reader.pages[:20]):  # max 20 paginas
        text = page.extract_text()
        if text:
            textos.append(text.strip())

    if not textos:
        return f"[Report PDF: {title} - nenhuma texto extraido]"

    texto_completo = "\n\n".join(textos)
    # Limitar a 8000 chars
    if len(texto_completo) > 8000:
        texto_completo = texto_completo[:8000] + "\n... (truncado)"

    return f"[Report PDF: {title}]\n{texto_completo}"


def _extrair_xlsx(file_path: str, title: str) -> str:
    """Extrai dados de XLSX usando openpyxl."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return f"[Report XLSX: {title} - openpyxl nao instalado]"

    wb = load_workbook(file_path, read_only=True, data_only=True)
    textos = []

    for sheet_name in wb.sheetnames[:10]:  # max 10 sheets
        ws = wb[sheet_name]
        linhas = []
        for row in ws.iter_rows(max_row=50, values_only=True):  # max 50 linhas
            valores = [str(c) if c is not None else "" for c in row]
            linha = " | ".join(valores).strip()
            if linha:
                linhas.append(linha)

        if linhas:
            textos.append(f"[Sheet: {sheet_name}]\n" + "\n".join(linhas))

    wb.close()

    if not textos:
        return f"[Report XLSX: {title} - planilha vazia]"

    texto_completo = "\n\n".join(textos)
    if len(texto_completo) > 8000:
        texto_completo = texto_completo[:8000] + "\n... (truncado)"

    return f"[Report XLSX: {title}]\n{texto_completo}"


def _extrair_texto(file_path: str, title: str) -> str:
    """Extrai texto de arquivos TXT/MD."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        texto = f.read()

    if len(texto) > 8000:
        texto = texto[:8000] + "\n... (truncado)"

    tipo = "MD" if file_path.endswith(".md") else "TXT"
    return f"[Report {tipo}: {title}]\n{texto}"


def _extrair_docx(file_path: str, title: str) -> str:
    """Extrai texto de DOCX usando python-docx."""
    try:
        from docx import Document
    except ImportError:
        return f"[Report DOCX: {title} - python-docx nao instalado]"

    doc = Document(file_path)
    textos = []
    for para in doc.paragraphs[:100]:  # max 100 paragrafos
        text = para.text.strip()
        if text:
            textos.append(text)

    if not textos:
        return f"[Report DOCX: {title} - documento vazio]"

    texto_completo = "\n".join(textos)
    if len(texto_completo) > 8000:
        texto_completo = texto_completo[:8000] + "\n... (truncado)"

    return f"[Report DOCX: {title}]\n{texto_completo}"


def _extrair_json(file_path: str, title: str) -> str:
    """Extrai dados de JSON (memorial descritivo)."""
    import json

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    texto = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if len(texto) > 6000:
        texto = texto[:6000] + "\n... (truncado)"

    return f"[Report JSON: {title}]\n{texto}"
