"""
Vinculacao espacial de aberturas a paredes.

Vincula blocos INSERT (portas/janelas) a segmentos de parede
por proximidade usando distancia ponto-segmento com tolerancia de 5mm.

Inspirado no Echo (app/backend/src/modules/drill.py).
"""
from __future__ import annotations

import math
from typing import Any


TOLERANCIA_PADRAO = 0.005  # 5mm


def distancia_ponto_segmento(
    ponto: tuple[float, float],
    seg_inicio: tuple[float, float],
    seg_fim: tuple[float, float],
) -> float:
    """
    Calcula a distancia minima de um ponto a um segmento de reta.
    Usa projecao vetorial com clamp para [0, 1].
    """
    px, py = ponto
    ax, ay = seg_inicio
    bx, by = seg_fim

    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq < 1e-12:
        # Segmento degenerado (ponto)
        return math.hypot(px - ax, py - ay)

    # Parametro t da projecao
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))

    # Ponto projetado
    proj_x = ax + t * dx
    proj_y = ay + t * dy

    return math.hypot(px - proj_x, py - proj_y)


def vincular_aberturas_paredes(
    blocos: list[dict[str, Any]],
    elementos: list[dict[str, Any]],
    tolerancia: float = TOLERANCIA_PADRAO,
) -> list[dict[str, Any]]:
    """
    Vincula aberturas (portas/janelas) a paredes por proximidade.

    Para cada bloco INSERT (porta/janela), calcula a distancia
    a todos os segmentos de parede. Se a distancia <= tolerancia,
    vincula a abertura a parede.

    Args:
        blocos: lista de blocos com 'bloco', 'layer', 'ponto_insercao'
        elementos: lista de elementos geometricos com 'layer', 'tipo', 'disciplina'
        tolerancia: distancia maxima para vinculacao (default 5mm)

    Returns:
        Lista de aberturas vinculadas com 'parede_vinculada' e 'distancia'
    """
    # Filtrar aberturas (portas/janelas)
    aberturas = []
    for b in blocos:
        layer_upper = b.get("layer", "").upper()
        bloco_upper = b.get("bloco", "").upper()
        disciplina = b.get("disciplina", "").upper()

        # Identificar aberturas por layer, bloco ou disciplina
        is_abertura = (
            "PORTA" in layer_upper or "JANELA" in layer_upper or
            "PORTA" in bloco_upper or "JANELA" in bloco_upper or
            "PORTA" in disciplina or "JANELA" in disciplina or
            "ESQUADRIA" in layer_upper or "ESQUADRIA" in disciplina
        )

        if is_abertura:
            ponto = b.get("ponto_insercao")
            if ponto and len(ponto) >= 2:
                aberturas.append({
                    **b,
                    "_ponto": (float(ponto[0]), float(ponto[1])),
                })

    # Filtrar paredes (LINE/LWPOLYLINE em layers de parede)
    paredes = []
    for e in elementos:
        layer_upper = e.get("layer", "").upper()
        tipo = e.get("tipo", "").upper()
        disciplina = e.get("disciplina", "").upper()

        is_parede = (
            "PAREDE" in layer_upper or "PAREDE" in disciplina or
            ("ALVENARIA" in layer_upper and "LIN" in tipo)
        )

        if is_parede:
            # Extrair segmentos (inicio/fim) se disponivel
            inicio = e.get("inicio") or e.get("start")
            fim = e.get("fim") or e.get("end")
            if inicio and fim and len(inicio) >= 2 and len(fim) >= 2:
                paredes.append({
                    **e,
                    "_inicio": (float(inicio[0]), float(inicio[1])),
                    "_fim": (float(fim[0]), float(fim[1])),
                })

    # Vincular aberturas a paredes
    vinculadas = []
    for abertura in aberturas:
        ponto = abertura["_ponto"]
        best_parede = None
        best_dist = tolerancia

        for parede in paredes:
            dist = distancia_ponto_segmento(
                ponto,
                parede["_inicio"],
                parede["_fim"],
            )
            if dist < best_dist:
                best_dist = dist
                best_parede = parede

        vinculacao = {
            "bloco": abertura.get("bloco", ""),
            "layer": abertura.get("layer", ""),
            "ponto_insercao": list(ponto),
            "parede_vinculada": best_parede.get("layer", "") if best_parede else None,
            "distancia": round(best_dist, 4) if best_parede else None,
            "vinculado": best_parede is not None,
        }
        vinculadas.append(vinculacao)

    return vinculadas


def calcular_area_abertura(
    bloco: dict[str, Any],
    altura_padrao: float = 2.10,
    espessura_padrao: float = 0.15,
) -> float:
    """
    Calcula a area de uma abertura (porta/janela) para deducao.
    Usa dimensoes do bloco se disponivel, senao usa padroes.
    """
    largura = bloco.get("largura") or bloco.get("width") or 0.80
    altura = bloco.get("altura") or bloco.get("height") or altura_padrao

    return float(largura) * float(altura)
