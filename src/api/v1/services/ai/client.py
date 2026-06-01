"""
Cliente HTTP para chamadas de IA (OpenRouter, Ollama, ou qualquer provider OpenAI-compativel).
"""
from __future__ import annotations

import httpx

from src.api.v1.services.ai.config_fetcher import fetch_ai_config
from src.logger import log


def chamar_ia(system_prompt: str, user_prompt: str) -> str:
    """
    Envia uma requisicao ao provider de IA configurado e retorna o texto da resposta.
    Suporta OpenRouter, Ollama e qualquer API compativel com OpenAI.
    """
    config = fetch_ai_config()

    api_key = config["api_key"]
    base_url = config["base_url"]
    model = config["model"]
    provider = config["provider"]

    headers = {"Content-Type": "application/json"}

    # OpenRouter precisa de headers extras
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/CADe"
        headers["X-Title"] = "CADe - Memorial Descritivo"

    # Authorization: Ollama nao precisa por padrao
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider != "ollama":
        raise ValueError(
            "API key nao configurada. "
            "Adicione sua chave no painel admin ou no arquivo .env"
        )

    payload = {
        "model": model,
        "temperature": 0,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    # Ollama em CPU pode demorar mais que OpenRouter na nuvem
    timeout = 600.0 if provider == "ollama" else 180.0

    with httpx.Client(timeout=timeout) as client:
        response = client.post(base_url, json=payload, headers=headers)
        response.raise_for_status()

    # Ollama pode retornar NDJSON (streaming) mesmo com stream:false
    # Pegar apenas a primeira linha JSON valida
    import json
    text = response.text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Multiplas linhas — pegar a ultima linha com "choices" (resposta final)
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    if "choices" in data:
                        break
                except json.JSONDecodeError:
                    continue
        else:
            raise ValueError(f"Resposta invalida do provider: {text[:200]}")

    # Verificar se a resposta foi truncada
    choice = data["choices"][0]
    finish_reason = choice.get("finish_reason", "")
    if finish_reason == "length":
        log.warn("IA", "Resposta truncada por limite de tokens (max_tokens muito baixo)")

    content = choice["message"]["content"]
    if not content or not content.strip():
        raise ValueError(f"Provider '{provider}' retornou resposta vazia")

    return content


def chamar_openrouter(system_prompt: str, user_prompt: str) -> str:
    """
    Compatibilidade: redireciona para chamar_ia().
    Mantido para nao quebrar imports existentes (pipeline, chat, relatorios).
    """
    return chamar_ia(system_prompt, user_prompt)
