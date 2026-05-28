"""
Rota de chat IA para perguntas sobre projetos processados.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.v1.dependencies import verify_api_key
from src.api.v1.services.ai.chat_service import responder_pergunta_chat


class ChatMessage(BaseModel):
    role: str  # "user" ou "assistant"
    content: str


class ChatRequest(BaseModel):
    pergunta: str
    json_cru: dict[str, Any]
    json_tratado: dict[str, Any]
    historico: list[ChatMessage] | None = None


class ChatResponse(BaseModel):
    resposta: str


router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chat sobre projeto e normas tecnicas",
    description=(
        "Recebe uma pergunta e os dados do projeto (JSON cru e tratado), "
        "consulta normas via RAG e retorna uma resposta da IA."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def chat_endpoint(req: ChatRequest) -> ChatResponse:
    historico_dicts = None
    if req.historico:
        historico_dicts = [msg.model_dump() for msg in req.historico]

    resposta = responder_pergunta_chat(
        pergunta=req.pergunta,
        json_cru=req.json_cru,
        json_tratado=req.json_tratado,
        historico=historico_dicts,
    )

    return ChatResponse(resposta=resposta)
