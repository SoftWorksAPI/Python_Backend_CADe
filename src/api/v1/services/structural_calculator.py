"""
Calculadora estrutural detalhada com deducoes de aberturas.

Calcula volumes de concreto para paredes, vigas, pilares, lajes
e fundacoes, deduzindo aberturas (portas/janelas) das paredes.

Inspirado no Echo (app/backend/src/modules/drill.py).
"""
from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Configuracao de dimensoes padrao (metros)
# ---------------------------------------------------------------------------

CONFIG_ESTRUTURAL: dict[str, dict[str, float]] = {
    "paredes": {
        "altura_padrao": 2.80,
        "espessura_padrao": 0.15,
    },
    "vigas": {
        "base_padrao": 0.15,
        "altura_padrao": 0.40,
    },
    "pilares": {
        "largura_padrao": 0.20,
        "profundidade_padrao": 0.20,
        "altura_padrao": 3.00,
    },
    "lajes": {
        "espessura_padrao": 0.12,
    },
    "fundacoes": {
        "espessura_padrao": 0.30,
    },
}


# ---------------------------------------------------------------------------
# Calculo de area de poligono (Shoelace formula)
# ---------------------------------------------------------------------------

def calcular_area_poligono(vertices: list[tuple[float, float]]) -> float:
    """
    Calcula a area de um poligono usando a formula de Gauss (Shoelace).
    """
    n = len(vertices)
    if n < 3:
        return 0.0

    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += vertices[i][0] * vertices[j][1]
        area -= vertices[j][0] * vertices[i][1]

    return abs(area) / 2.0


# ---------------------------------------------------------------------------
# Comprimento de segmento
# ---------------------------------------------------------------------------

def comprimento_segmento(
    inicio: tuple[float, float],
    fim: tuple[float, float],
) -> float:
    """Calcula o comprimento de um segmento."""
    dx = fim[0] - inicio[0]
    dy = fim[1] - inicio[1]
    return math.hypot(dx, dy)


# ---------------------------------------------------------------------------
# Volume de parede com deducoes
# ---------------------------------------------------------------------------

def calcular_volume_parede(
    comprimento: float,
    altura: float | None = None,
    espessura: float | None = None,
    aberturas: list[dict[str, Any]] | None = None,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Calcula o volume de uma parede deduzindo aberturas.

    Args:
        comprimento: comprimento da parede (metros)
        altura: altura da parede (usa padrao se None)
        espessura: espessura da parede (usa padrao se None)
        aberturas: lista de aberturas vinculadas com area
        config: configuracao de dimensoes

    Returns:
        Dict com volume_bruto, area_aberturas, volume_liquido
    """
    cfg = config or CONFIG_ESTRUTURAL["paredes"]
    h = altura or cfg.get("altura_padrao", 2.80)
    e = espessura or cfg.get("espessura_padrao", 0.15)

    # Volume bruto
    area_bruta = comprimento * h
    volume_bruto = area_bruta * e

    # Deducao de aberturas
    area_aberturas = 0.0
    if aberturas:
        for ab in aberturas:
            area = ab.get("area", 0.0)
            area_aberturas += area

    volume_aberturas = area_aberturas * e
    volume_liquido = max(0.0, volume_bruto - volume_aberturas)

    return {
        "comprimento": round(comprimento, 2),
        "altura": round(h, 2),
        "espessura": round(e, 2),
        "area_bruta": round(area_bruta, 2),
        "area_aberturas": round(area_aberturas, 2),
        "area_liquida": round(area_bruta - area_aberturas, 2),
        "volume_bruto": round(volume_bruto, 3),
        "volume_aberturas": round(volume_aberturas, 3),
        "volume_liquido": round(volume_liquido, 3),
        "num_aberturas": len(aberturas) if aberturas else 0,
    }


# ---------------------------------------------------------------------------
# Volume de viga
# ---------------------------------------------------------------------------

def calcular_volume_viga(
    comprimento: float,
    base: float | None = None,
    altura: float | None = None,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Calcula o volume de uma viga.
    """
    cfg = config or CONFIG_ESTRUTURAL["vigas"]
    b = base or cfg.get("base_padrao", 0.15)
    h = altura or cfg.get("altura_padrao", 0.40)

    volume = comprimento * b * h

    return {
        "comprimento": round(comprimento, 2),
        "base": round(b, 2),
        "altura": round(h, 2),
        "secao_transversal": round(b * h, 4),
        "volume": round(volume, 3),
    }


# ---------------------------------------------------------------------------
# Volume de pilar
# ---------------------------------------------------------------------------

def calcular_volume_pilar(
    largura: float | None = None,
    profundidade: float | None = None,
    altura: float | None = None,
    quantidade: int = 1,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Calcula o volume de um ou mais pilares.
    """
    cfg = config or CONFIG_ESTRUTURAL["pilares"]
    l = largura or cfg.get("largura_padrao", 0.20)
    p = profundidade or cfg.get("profundidade_padrao", 0.20)
    h = altura or cfg.get("altura_padrao", 3.00)

    volume_unitario = l * p * h
    volume_total = volume_unitario * quantidade

    return {
        "largura": round(l, 2),
        "profundidade": round(p, 2),
        "altura": round(h, 2),
        "quantidade": quantidade,
        "volume_unitario": round(volume_unitario, 3),
        "volume_total": round(volume_total, 3),
    }


# ---------------------------------------------------------------------------
# Volume de laje
# ---------------------------------------------------------------------------

def calcular_volume_laje(
    area: float,
    espessura: float | None = None,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Calcula o volume de uma laje.
    """
    cfg = config or CONFIG_ESTRUTURAL["lajes"]
    e = espessura or cfg.get("espessura_padrao", 0.12)

    volume = area * e

    return {
        "area": round(area, 2),
        "espessura": round(e, 2),
        "volume": round(volume, 3),
    }


# ---------------------------------------------------------------------------
# Volume de fundacao
# ---------------------------------------------------------------------------

def calcular_volume_fundacao(
    area: float,
    espessura: float | None = None,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Calcula o volume de uma fundacao (sapata/baldrame).
    """
    cfg = config or CONFIG_ESTRUTURAL["fundacoes"]
    e = espessura or cfg.get("espessura_padrao", 0.30)

    volume = area * e

    return {
        "area": round(area, 2),
        "espessura": round(e, 2),
        "volume": round(volume, 3),
    }


# ---------------------------------------------------------------------------
# Pipeline completo de calculo estrutural
# ---------------------------------------------------------------------------

def calcular_volumes_estruturais(
    elementos: list[dict[str, Any]],
    blocos: list[dict[str, Any]],
    aberturas_vinculadas: list[dict[str, Any]] | None = None,
    config: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """
    Calcula volumes estruturais completos com deducoes.

    Args:
        elementos: elementos geometricos extraidos
        blocos: blocos extraidos (INSERT)
        aberturas_vinculadas: aberturas ja vinculadas a paredes
        config: configuracao de dimensoes

    Returns:
        Dict com volumes por tipo estrutural
    """
    cfg = config or CONFIG_ESTRUTURAL

    # Classificar elementos por tipo estrutural
    paredes = []
    vigas = []
    pilares = []
    lajes = []
    fundacoes = []

    for e in elementos:
        layer_upper = e.get("layer", "").upper()
        disciplina = e.get("disciplina", "").upper()

        if disciplina != "ESTRUTURAL":
            # Verificar tambem por keywords na layer
            if not any(kw in layer_upper for kw in ["PAREDE", "VIGA", "PILAR", "LAJE", "FUNDA", "ESTACA", "SAPATA"]):
                continue

        if "PAREDE" in layer_upper or "PAREDE" in disciplina:
            paredes.append(e)
        elif "VIGA" in layer_upper or "VIGA" in disciplina:
            vigas.append(e)
        elif "PILAR" in layer_upper or "PILAR" in disciplina or "COLUNA" in layer_upper:
            pilares.append(e)
        elif "LAJE" in layer_upper or "LAJE" in disciplina:
            lajes.append(e)
        elif any(kw in layer_upper for kw in ["FUNDA", "SAPATA", "BALDAME", "ESTACA"]):
            fundacoes.append(e)

    # Mapear aberturas por layer de parede
    aberturas_por_parede: dict[str, list[dict[str, Any]]] = {}
    if aberturas_vinculadas:
        for ab in aberturas_vinculadas:
            parede_layer = ab.get("parede_vinculada")
            if parede_layer:
                if parede_layer not in aberturas_por_parede:
                    aberturas_por_parede[parede_layer] = []
                # Calcular area da abertura
                area = ab.get("area") or 0.80 * 2.10  # padrao porta
                aberturas_por_parede[parede_layer].append({"area": area})

    # Calcular volumes
    resultado = {
        "paredes": [],
        "vigas": [],
        "pilares": [],
        "lajes": [],
        "fundacoes": [],
        "resumo": {
            "volume_total_concreto_m3": 0.0,
            "volume_paredes_m3": 0.0,
            "volume_vigas_m3": 0.0,
            "volume_pilares_m3": 0.0,
            "volume_lajes_m3": 0.0,
            "volume_fundacoes_m3": 0.0,
        },
    }

    # Paredes
    for p in paredes:
        inicio = p.get("inicio") or p.get("start")
        fim = p.get("fim") or p.get("end")
        if inicio and fim:
            comp = comprimento_segmento(
                (float(inicio[0]), float(inicio[1])),
                (float(fim[0]), float(fim[1])),
            )
            aberturas = aberturas_por_parede.get(p.get("layer", ""), [])
            vol = calcular_volume_parede(comp, aberturas=aberturas, config=cfg.get("paredes"))
            resultado["paredes"].append(vol)
            resultado["resumo"]["volume_paredes_m3"] += vol["volume_liquido"]

    # Vigas
    for v in vigas:
        inicio = v.get("inicio") or v.get("start")
        fim = v.get("fim") or v.get("end")
        if inicio and fim:
            comp = comprimento_segmento(
                (float(inicio[0]), float(inicio[1])),
                (float(fim[0]), float(fim[1])),
            )
            vol = calcular_volume_viga(comp, config=cfg.get("vigas"))
            resultado["vigas"].append(vol)
            resultado["resumo"]["volume_vigas_m3"] += vol["volume"]

    # Pilares (contar blocos de pilar)
    num_pilares = len(pilares)
    if num_pilares > 0:
        vol = calcular_volume_pilar(quantidade=num_pilares, config=cfg.get("pilares"))
        resultado["pilares"].append(vol)
        resultado["resumo"]["volume_pilares_m3"] += vol["volume_total"]

    # Lajes (usar area dos elementos)
    for l in lajes:
        area = l.get("area", 0.0)
        if area > 0:
            vol = calcular_volume_laje(area, config=cfg.get("lajes"))
            resultado["lajes"].append(vol)
            resultado["resumo"]["volume_lajes_m3"] += vol["volume"]

    # Fundacoes
    for f in fundacoes:
        area = f.get("area", 0.0)
        if area > 0:
            vol = calcular_volume_fundacao(area, config=cfg.get("fundacoes"))
            resultado["fundacoes"].append(vol)
            resultado["resumo"]["volume_fundacoes_m3"] += vol["volume"]

    # Total
    resultado["resumo"]["volume_total_concreto_m3"] = round(
        resultado["resumo"]["volume_paredes_m3"] +
        resultado["resumo"]["volume_vigas_m3"] +
        resultado["resumo"]["volume_pilares_m3"] +
        resultado["resumo"]["volume_lajes_m3"] +
        resultado["resumo"]["volume_fundacoes_m3"],
        3,
    )

    # Arredondar resumo
    for key in resultado["resumo"]:
        resultado["resumo"][key] = round(resultado["resumo"][key], 3)

    return resultado
