"""
Cliente HTTP para OpenRouter (API compatível com OpenAI).
Usa httpx sincrono — a chamada é feita dentro do pipeline.
"""
from __future__ import annotations

import httpx

from src.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_TEMPERATURE

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def chamar_openrouter(system_prompt: str, user_prompt: str) -> str:
    """
    Envia uma requisição ao OpenRouter e retorna o texto da resposta.

    Args:
        system_prompt: Instrução de sistema (papel do agente)
        user_prompt: Prompt do usuário com os dados

    Returns:
        Texto da resposta do LLM

    Raises:
        ValueError: Se a API key não estiver configurada
        httpx.HTTPStatusError: Se a API retornar erro
    """
    if not OPENROUTER_API_KEY:
        raise ValueError(
            "OPENROUTER_API_KEY não configurada. "
            "Adicione sua chave no arquivo .env"
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/CADe",
        "X-Title": "CADe - Memorial Descritivo",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "temperature": OPENROUTER_TEMPERATURE,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(OPENROUTER_URL, json=payload, headers=headers)
        response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"]
