"""
Modulo de busca de normas relevantes para o pipeline de IA.
"""
from __future__ import annotations

from src.api.v1.services.rag.vectorstore import buscar_chunks


def buscar_normas_relevantes(query: str, k: int = 5) -> str:
    """
    Busca normas tecnicas relevantes no ChromaDB e retorna
    o contexto formatado para injecao no prompt do LLM.

    Args:
        query: texto de busca (ex: "NBR 5410 aterramento eletrico")
        k: numero de chunks a retornar

    Returns:
        String formatada com os trechos relevantes, ou string vazia
        se nao houver dados no ChromaDB.
    """
    chunks = buscar_chunks(query, k=k)

    if not chunks:
        return ""

    partes = []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        codigo = meta.get("codigo", "N/A")
        categoria = meta.get("categoria", "")
        texto = chunk.get("texto", "")

        parte = f"[Norma: {codigo}"
        if categoria:
            parte += f" | Categoria: {categoria}"
        parte += f"]\n{texto}"
        partes.append(parte)

    return "\n\n---\n\n".join(partes)
