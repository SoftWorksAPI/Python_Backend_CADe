"""
Configuracao e inicializacao do ChromaDB para armazenamento vetorial de normas.
"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

import chromadb

from src.config import CHROMA_PERSIST_PATH

COLLECTION_NAME = "normas_tecnicas"
_persist_path = Path(CHROMA_PERSIST_PATH).resolve()

_client: chromadb.ClientAPI | None = None
_client_lock = threading.Lock()


def _get_client() -> chromadb.ClientAPI:
    """Retorna cliente ChromaDB persistente (singleton)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _persist_path.mkdir(parents=True, exist_ok=True)
                _client = chromadb.PersistentClient(path=str(_persist_path))
    return _client


def get_vectorstore():
    """Retorna a colecao do ChromaDB."""
    client = _get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def buscar_chunks(query: str, k: int = 5) -> list[dict]:
    """
    Busca por similaridade no ChromaDB.
    Retorna os k chunks mais relevantes.
    """
    collection = get_vectorstore()
    if collection.count() == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    if results and results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            chunks.append({
                "texto": doc[:600],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distancia": results["distances"][0][i] if results["distances"] else None,
            })

    return chunks


def limpar_vectorstore() -> dict:
    """Remove todos os dados do ChromaDB."""
    global _client
    if _persist_path.exists():
        shutil.rmtree(_persist_path)
    _client = None
    return {"ok": True, "mensagem": "ChromaDB limpo com sucesso."}


def status_vectorstore() -> dict:
    """Retorna status do ChromaDB."""
    try:
        collection = get_vectorstore()
        count = collection.count()

        normas = set()
        if count > 0:
            result = collection.get(include=["metadatas"])
            for meta in (result.get("metadatas") or []):
                if meta and meta.get("codigo"):
                    normas.add(meta["codigo"])

        return {
            "status": "online",
            "total_chunks": count,
            "normas_indexadas": sorted(normas),
            "caminho": str(_persist_path),
        }
    except Exception as exc:
        return {
            "status": "erro",
            "total_chunks": 0,
            "normas_indexadas": [],
            "erro": str(exc),
            "caminho": str(_persist_path),
        }
