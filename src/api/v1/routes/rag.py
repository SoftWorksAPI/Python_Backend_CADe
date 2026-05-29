"""
Rotas para gerenciamento do RAG de normas tecnicas.
"""
import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.v1.dependencies import verify_api_key
from src.api.v1.services.rag.ingestion import sincronizar_normas
from src.api.v1.services.rag.vectorstore import status_vectorstore, limpar_vectorstore


class SyncResponse(BaseModel):
    ok: bool
    mensagem: str | None = None
    normas_sincronizadas: int | None = None
    total_chunks: int | None = None
    normas: list[str] | None = None
    erros: list[str] | None = None
    erro: str | None = None


router = APIRouter()


@router.post(
    "/rag/sync",
    response_model=SyncResponse,
    summary="Sincroniza normas ativas do Node.js para o ChromaDB",
    description=(
        "Busca as normas ativas (ativo=true) do Backend Node.js, "
        "baixa os PDFs, extrai o texto, gera embeddings e indexa no ChromaDB."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def rag_sync() -> SyncResponse:
    resultado = await asyncio.to_thread(sincronizar_normas)
    return SyncResponse(**resultado)


@router.get(
    "/rag/health",
    summary="Status do ChromaDB",
    description="Retorna o status do banco vetorial: total de chunks, normas indexadas.",
    dependencies=[Depends(verify_api_key)],
)
async def rag_health():
    return await asyncio.to_thread(status_vectorstore)


@router.delete(
    "/rag/clear",
    summary="Limpa todo o ChromaDB",
    description="Remove todos os chunks indexados. Use com cuidado.",
    dependencies=[Depends(verify_api_key)],
)
async def rag_clear():
    return await asyncio.to_thread(limpar_vectorstore)
