"""
Rotas para configuracao de IA (interno).

Permite ao Node backend enviar configuracao atualizada para o Python,
e consultar a configuracao em memoria.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.v1.dependencies import verify_api_key
from src.api.v1.services.ai.config_fetcher import (
    fetch_ai_config,
    update_config_locally,
)
from src.api.v1.services.ai.client import chamar_ia

router = APIRouter()


class AIConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    apiKey: str | None = None
    baseUrl: str | None = None


class AIConfigResponse(BaseModel):
    provider: str
    model: str
    apiKey: str
    baseUrl: str


@router.get(
    "/ai/config",
    response_model=AIConfigResponse,
    summary="Retorna configuracao de IA em memoria",
    dependencies=[Depends(verify_api_key)],
)
async def get_ai_config():
    """Retorna a configuracao de IA atualmente em memoria no Python."""
    config = fetch_ai_config()
    return AIConfigResponse(
        provider=config["provider"],
        model=config["model"],
        apiKey=config["api_key"],
        baseUrl=config["base_url"],
    )


@router.put(
    "/ai/config",
    response_model=AIConfigResponse,
    summary="Atualiza configuracao de IA em memoria",
    dependencies=[Depends(verify_api_key)],
)
async def update_ai_config(body: AIConfigUpdate):
    """Atualiza a configuracao de IA em memoria. Chamado pelo Node quando admin altera config."""
    update_config_locally({
        "provider": body.provider,
        "model": body.model,
        "apiKey": body.apiKey,
        "baseUrl": body.baseUrl,
    })

    config = fetch_ai_config(force_refresh=True)
    return AIConfigResponse(
        provider=config["provider"],
        model=config["model"],
        apiKey=config["api_key"],
        baseUrl=config["base_url"],
    )


@router.post(
    "/ai/test",
    summary="Testa conexao com o provider de IA configurado",
    dependencies=[Depends(verify_api_key)],
)
async def test_ai_connection():
    """Envia um prompt simples para testar se o provider de IA esta respondendo."""
    try:
        resposta = await asyncio.to_thread(
            chamar_ia,
            system_prompt="Responda com uma unica palavra.",
            user_prompt="Diga 'online' se voce esta funcionando.",
        )
        config = fetch_ai_config()
        return {
            "status": "online",
            "provider": config["provider"],
            "modelo": config["model"],
            "resposta": resposta.strip(),
        }
    except ValueError as exc:
        config = fetch_ai_config()
        return {
            "status": "erro_config",
            "provider": config["provider"],
            "modelo": config["model"],
            "resposta": None,
            "erro": str(exc),
        }
    except Exception as exc:
        config = fetch_ai_config()
        return {
            "status": "erro_conexao",
            "provider": config["provider"],
            "modelo": config["model"],
            "resposta": None,
            "erro": str(exc),
        }
