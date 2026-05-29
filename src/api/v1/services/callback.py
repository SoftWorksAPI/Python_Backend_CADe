"""
Servico de callback para notificar o Node.js quando o processamento termina.
"""
from __future__ import annotations

import httpx

from src.config import INTERNAL_API_KEY
from src.logger import log


def enviar_callback(callback_url: str, dados: dict) -> bool:
    """
    Envia resultado para o Node.js via callback HTTP POST.

    Returns True se o callback foi enviado com sucesso, False caso contrario.
    """
    headers = {
        "x-api-key": INTERNAL_API_KEY or "cade-internal-key-2026",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(callback_url, json=dados, headers=headers)
            response.raise_for_status()
            log.info("CALLBACK", f"Enviado com sucesso para {callback_url} ({response.status_code})")
            return True
    except Exception as e:
        log.error("CALLBACK", f"Falha ao enviar para {callback_url}: {e}")
        return False
