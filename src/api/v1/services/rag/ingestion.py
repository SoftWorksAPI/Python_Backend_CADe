"""
Modulo de ingestao de normas: baixa arquivos do Node.js e indexa no ChromaDB.
Suporta: PDF, DOCX, XLSX.
"""
from __future__ import annotations

import os
import re
import tempfile

import httpx
from pypdf import PdfReader

from src.config import NODE_BACKEND_URL
from src.api.v1.services.rag.vectorstore import get_vectorstore


# ---------------------------------------------------------------------------
# Text splitting
# ---------------------------------------------------------------------------

def _split_text(text: str, chunk_size: int = 1200, chunk_overlap: int = 300) -> list[str]:
    """Divide texto em chunks com overlap."""
    if not text or not text.strip():
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if end < len(text):
            last_period = chunk.rfind(".")
            last_newline = chunk.rfind("\n")
            break_point = max(last_period, last_newline)
            if break_point > chunk_size // 2:
                chunk = chunk[:break_point + 1]
                end = start + break_point + 1

        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)

        start = end - chunk_overlap
        if start <= 0 and end >= len(text):
            break
        start = max(start, 0)

    return chunks


def _clean_text(text: str) -> str:
    """Limpa texto extraido de documentos."""
    text = re.sub(r"[^\x00-\x7F\u00C0-\u00FF]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    linhas = text.splitlines()
    linhas_limpas = []
    for linha in linhas:
        l = linha.strip()
        if not l:
            continue
        if re.fullmatch(r"[\W_]+", l):
            continue
        if len(l) <= 2:
            continue
        linhas_limpas.append(l)
    return "\n".join(linhas_limpas).strip()


# ---------------------------------------------------------------------------
# Extracao de texto por formato
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(file_path: str) -> str:
    """Extrai texto de um arquivo PDF."""
    reader = PdfReader(file_path)
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)
    return "\n\n".join(text_parts)


def _extract_text_from_docx(file_path: str) -> str:
    """Extrai texto de um arquivo DOCX."""
    from docx import Document
    doc = Document(file_path)
    text_parts = []
    for paragraph in doc.paragraphs:
        if paragraph.text and paragraph.text.strip():
            text_parts.append(paragraph.text.strip())
    # Tambem extrair texto de tabelas
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                text_parts.append(row_text)
    return "\n\n".join(text_parts)


def _extract_text_from_xlsx(file_path: str) -> str:
    """Extrai texto de um arquivo Excel."""
    from openpyxl import load_workbook
    wb = load_workbook(file_path, read_only=True, data_only=True)
    text_parts = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        text_parts.append(f"[Planilha: {sheet_name}]")
        for row in ws.iter_rows(values_only=True):
            row_text = " | ".join(str(cell) for cell in row if cell is not None)
            if row_text and row_text.strip():
                text_parts.append(row_text.strip())
    wb.close()
    return "\n\n".join(text_parts)


def _extract_text(file_path: str, file_type: str) -> str:
    """
    Extrai texto de um arquivo baseado na extensao.
    Suporta: pdf, docx, xlsx, xls
    """
    ext = file_type.lower().strip(".")

    if ext == "pdf":
        return _extract_text_from_pdf(file_path)
    elif ext == "docx":
        return _extract_text_from_docx(file_path)
    elif ext in ("xlsx", "xls"):
        return _extract_text_from_xlsx(file_path)
    else:
        raise ValueError(f"Formato nao suportado: .{ext} (apenas PDF, DOCX, XLSX)")


# ---------------------------------------------------------------------------
# Download de arquivos do Node.js
# ---------------------------------------------------------------------------

def _buscar_normas_ativas() -> list[dict]:
    """Busca normas ativas do Backend Node.js."""
    url = f"{NODE_BACKEND_URL}/norm-files/internal/ativas"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()

    data = response.json()
    return data.get("normas", [])


def _baixar_arquivo(url_path: str, destino: str) -> str:
    """Baixa um arquivo do Node.js e salva no destino."""
    full_url = f"{NODE_BACKEND_URL}{url_path}"

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(full_url)
        response.raise_for_status()

    with open(destino, "wb") as f:
        f.write(response.content)

    return destino


# ---------------------------------------------------------------------------
# Ingestao principal
# ---------------------------------------------------------------------------

def sincronizar_normas() -> dict:
    """
    Sincroniza normas ativas do Node.js para o ChromaDB.

    Fluxo:
        1. Busca normas ativas no Node.js
        2. Limpa a colecao atual no ChromaDB
        3. Para cada norma: baixa arquivo -> extrai texto -> limpa -> split -> indexa
        4. Retorna resumo da operacao
    """
    try:
        normas = _buscar_normas_ativas()
    except httpx.ConnectError:
        return {
            "ok": False,
            "erro": "Nao foi possivel conectar ao Backend Node.js. Verifique se esta rodando.",
            "normas_sincronizadas": 0,
            "total_chunks": 0,
        }
    except Exception as exc:
        return {
            "ok": False,
            "erro": f"Erro ao buscar normas: {str(exc)}",
            "normas_sincronizadas": 0,
            "total_chunks": 0,
        }

    if not normas:
        return {
            "ok": True,
            "mensagem": "Nenhuma norma ativa encontrada no Node.js.",
            "normas_sincronizadas": 0,
            "total_chunks": 0,
        }

    # Limpar colecao existente
    try:
        collection = get_vectorstore()
        existing = collection.get()
        if existing and existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    collection = get_vectorstore()
    total_chunks = 0
    normas_indexadas = []
    erros = []

    for norma in normas:
        norma_id = norma.get("id") or 0
        title = norma.get("title") or "Sem titulo"
        description = norma.get("description") or ""
        category = norma.get("category") or ""
        file_path = norma.get("filePath") or ""
        original_name = norma.get("originalName") or ""
        file_type = norma.get("fileType") or ""

        # Detectar extensao do arquivo
        if not file_type:
            file_type = original_name.rsplit(".", 1)[-1] if "." in original_name else "pdf"

        ext = file_type.lower().strip(".")

        # Pular formatos nao suportados
        if ext == "doc":
            erros.append(f"Norma '{title}': formato .doc nao suportado (apenas .docx). Converta para .docx e reenvie.")
            continue

        try:
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp_path = tmp.name

            _baixar_arquivo(file_path, tmp_path)

            # Extrair texto conforme formato
            raw_text = _extract_text(tmp_path, ext)
            clean = _clean_text(raw_text)

            # Limpar temp
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

            if not clean.strip():
                erros.append(f"Norma '{title}': texto vazio apos limpeza.")
                continue

            # Split em chunks
            chunks = _split_text(clean, chunk_size=1200, chunk_overlap=300)

            if not chunks:
                erros.append(f"Norma '{title}': nenhum chunk gerado.")
                continue

            # Normalizar codigo
            codigo = re.sub(r"[^A-Z0-9]", "", title.upper().strip()) or "SEM_CODIGO"

            # Indexar no ChromaDB em lotes
            LOTE = 200
            for i in range(0, len(chunks), LOTE):
                lote = chunks[i:i + LOTE]
                ids = [f"{codigo}_{i + j}" for j in range(len(lote))]
                metadatas = [
                    {
                        "norma_id": str(norma_id),
                        "codigo": str(title),
                        "codigo_normalizado": str(codigo),
                        "categoria": str(category),
                        "descricao": str(description) if description else "",
                        "arquivo": str(original_name),
                        "tipo_arquivo": str(ext),
                        "chunk_index_global": i + j,
                    }
                    for j in range(len(lote))
                ]

                collection.add(
                    ids=ids,
                    documents=lote,
                    metadatas=metadatas,
                )

            total_chunks += len(chunks)
            normas_indexadas.append(title)

        except Exception as exc:
            erros.append(f"Norma '{title}': {str(exc)}")

    return {
        "ok": True,
        "mensagem": f"Sincronizacao concluida. {len(normas_indexadas)} normas indexadas.",
        "normas_sincronizadas": len(normas_indexadas),
        "total_chunks": total_chunks,
        "normas": normas_indexadas,
        "erros": erros if erros else None,
    }
