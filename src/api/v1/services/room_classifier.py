"""
Classificador de ambientes por proximidade de texto.

Classifica poligonos de ambientes detectados em categorias
(sanitario, cozinha, dormitorio, etc.) usando textos proximos
extraidos do DXF.

Inspirado no Blueprint (apps/projetos/ai/cad/classifier.py).
"""
from __future__ import annotations

from typing import Any

from shapely.geometry import Point, Polygon


# ---------------------------------------------------------------------------
# Mapeamento de categorias por keywords
# ---------------------------------------------------------------------------

_CATEGORIA_KEYWORDS: dict[str, list[str]] = {
    "sanitario": [
        "banheiro", "banheir", "wc", "lavabo", "sanitario", "sanitária",
        "toilete", "lavatorio", "bathroom", "restroom",
    ],
    "cozinha": [
        "cozinha", "copa", "kitchen", "area de servico", "lavanderia",
        "service",
    ],
    "dormitorio": [
        "quarto", "dormitorio", "suite", "bedroom", "sleep", "dormir",
        "quarto de", "apartamento",
    ],
    "estar": [
        "sala", "living", "estar", "varanda", "varand", "sala de estar",
        "sala de visita", "living room", "hall",
    ],
    "garagem": [
        "garagem", "estacionamento", "garage", "parking", "vaga",
    ],
    "comercial": [
        "escritorio", "departamento", "comercial", "loja", "office",
        "recepcao", "reception", "administra", "admin",
    ],
    "industrial": [
        "deposito", "almoxarifado", "warehouse", "storage", "industrial",
        "oficina", "workshop",
    ],
    "educacao": [
        "sala de aula", "classroom", "escola", "school", "biblioteca",
        "library", "laboratorio", "lab",
    ],
    "saude": [
        "hospital", "clinica", "consultorio", "farmacia", "pharmacy",
        "enfermaria", "health",
    ],
    "circulacao": [
        "circulacao", "circulação", "corredor", "hall", "lobby",
        "escada", "elevator", "elevador", "passagem",
    ],
}


def classificar_ambientes(
    ambientes: list[dict[str, Any]],
    textos: list[dict[str, Any]],
    max_dist: float = 5.0,
) -> list[dict[str, Any]]:
    """
    Classifica ambientes por categoria usando proximidade de texto.

    Para cada ambiente, busca o texto mais proximo e mapeia para uma categoria.

    Args:
        ambientes: lista de ambientes com 'ambiente' e 'area' (posicao do centroide)
        textos: lista de textos com 'texto', 'layer', e posicao (x, y se disponivel)
        max_dist: distancia maxima para buscar texto (metros)

    Returns:
        Lista de ambientes com campo 'categoria' adicionado
    """
    if not ambientes:
        return ambientes

    # Extrair posicoes dos textos (se disponivel)
    textos_com_posicao = []
    for t in textos:
        texto = t.get("texto", "").strip()
        if len(texto) < 2:
            continue
        # Tentar extrair posicao do texto (pode nao ter)
        pos = t.get("posicao") or t.get("ponto")
        if pos and len(pos) >= 2:
            textos_com_posicao.append({
                "texto": texto,
                "x": float(pos[0]),
                "y": float(pos[1]),
            })

    ambientes_classificados = []
    for amb in ambientes:
        amb_copy = dict(amb)
        nome = amb_copy.get("ambiente", "")

        # Mapear categoria pelo nome do ambiente
        categoria = _mapear_categoria(nome)

        # Se nao conseguiu pelo nome, buscar texto proximo
        if categoria == "outro" and textos_com_posicao:
            # Usar posicao do ambiente se disponivel
            centroide = amb_copy.get("centroide") or amb_copy.get("posicao")
            if centroide and len(centroide) >= 2:
                texto_proximo = _buscar_texto_proximo(
                    (float(centroide[0]), float(centroide[1])),
                    textos_com_posicao,
                    max_dist,
                )
                if texto_proximo:
                    categoria = _mapear_categoria(texto_proximo)

        amb_copy["categoria"] = categoria
        ambientes_classificados.append(amb_copy)

    return ambientes_classificados


def _mapear_categoria(nome: str) -> str:
    """
    Mapeia nome do ambiente para categoria via keywords.
    Retorna 'outro' se nao encontrar correspondencia.
    """
    nome_lower = nome.lower().strip()

    for categoria, keywords in _CATEGORIA_KEYWORDS.items():
        for kw in keywords:
            if kw in nome_lower:
                return categoria

    return "outro"


def _buscar_texto_proximo(
    centroide: tuple[float, float],
    textos: list[dict[str, Any]],
    max_dist: float,
) -> str | None:
    """
    Busca o texto mais proximo de um centroide dentro de max_dist.
    Retorna o texto encontrado ou None.
    """
    best_text = None
    best_dist = max_dist

    cx, cy = centroide

    for t in textos:
        dx = t["x"] - cx
        dy = t["y"] - cy
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_text = t["texto"]

    return best_text
