"""
Busca a configuracao de IA do Node backend com cache em memoria.

Fallback para variaveis de ambiente (.env) se o Node nao estiver disponivel.
"""
from __future__ import annotations

import time

import httpx

from src.config import (
    NODE_BACKEND_URL,
    INTERNAL_API_KEY,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)
from src.logger import log

CACHE_TTL = 30  # segundos

_cache: dict = {
    "config": None,
    "expires_at": 0.0,
}


def _env_fallback() -> dict:
    """Retorna config baseada em variaveis de ambiente (.env)."""
    return {
        "provider": "openrouter",
        "model": OPENROUTER_MODEL,
        "api_key": OPENROUTER_API_KEY or "",
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
    }


def fetch_ai_config(force_refresh: bool = False) -> dict:
    """
    Busca configuracao de IA.

    1. Retorna do cache se ainda valido (a menos que force_refresh).
    2. Tenta buscar do Node backend.
    3. Fallback para .env em caso de erro.
    """
    now = time.time()
    if not force_refresh and _cache["config"] is not None and now < _cache["expires_at"]:
        return _cache["config"]

    try:
        url = f"{NODE_BACKEND_URL}/system/ai-config/internal"
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                url,
                headers={"x-api-key": INTERNAL_API_KEY},
            )
            resp.raise_for_status()

        data = resp.json()
        config = {
            "provider": data.get("provider", "openrouter"),
            "model": data.get("model", OPENROUTER_MODEL),
            "api_key": data.get("apiKey", ""),
            "base_url": data.get("baseUrl", "https://openrouter.ai/api/v1/chat/completions"),
        }

        _cache["config"] = config
        _cache["expires_at"] = now + CACHE_TTL
        return config

    except Exception as e:
        log.warn("AI_CONFIG", f"Falha ao buscar config do Node: {e}. Usando fallback .env")
        config = _env_fallback()
        _cache["config"] = config
        _cache["expires_at"] = now + CACHE_TTL
        return config


def update_config_locally(settings: dict) -> None:
    """
    Atualiza a config em memoria localmente (sem ir ao Node).
    Usado quando o Node envia uma atualizacao via PUT /v1/ai/config.
    """
    current = _cache["config"] or _env_fallback()

    key_map = {
        "provider": "provider",
        "model": "model",
        "apiKey": "api_key",
        "baseUrl": "base_url",
    }

    for key, value in settings.items():
        if value is None:
            continue
        internal_key = key_map.get(key)
        if internal_key:
            current[internal_key] = value

    _cache["config"] = current
    log.info("AI_CONFIG", f"Config atualizada localmente: provider={current['provider']}, model={current['model']}")


def invalidate_cache() -> None:
    """Forca recarga da config na proxima chamada."""
    _cache["expires_at"] = 0.0
