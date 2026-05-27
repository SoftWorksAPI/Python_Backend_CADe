"""
Dependency para verificar x-api-key em endpoints internos.
"""
from fastapi import Header, HTTPException, status

from src.config import INTERNAL_API_KEY


async def verify_api_key(x_api_key: str = Header(...)):
    """Verifica o header x-api-key contra a chave interna configurada."""
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave de API invalida",
        )
