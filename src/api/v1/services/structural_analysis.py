"""
Servico de analise estrutural de arquivos DXF.

Filtra elementos classificados como ESTRUTURAL, subclassifica por tipo
(pilar, viga, laje, estaca, fundacao), calcula metricas e estima volumes
com secoes tipicas.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.api.v1.schemas.dxf_schemas import DXFExtractResponse


# ---------------------------------------------------------------------------
# Secoes tipicas para estimativa de volume (referencia: Blueprint)
# ---------------------------------------------------------------------------

SECOES_TIPICAS: dict[str, dict[str, float]] = {
    "pilar": {"area_secao": 0.04, "pe_direito": 3.0},    # 20x20cm x 3m
    "viga": {"secao_transversal": 0.06},                   # 15x40cm = 0.06m2
    "estaca": {"area_secao": 0.0707, "profundidade": 10.0},  # D=30cm x 10m
    "laje": {"espessura": 0.12},                            # 12cm
    "fundacao": {"espessura": 0.30},                        # 30cm
    "parede_estrutural": {"espessura": 0.15},               # 15cm
}

TODOS_OS_TIPOS = list(SECOES_TIPICAS.keys())


# ---------------------------------------------------------------------------
# Classificacao de subcategoria estrutural
# ---------------------------------------------------------------------------

# Mapeamento keyword -> tipo estrutural (busca em uppercase)
_KEYWORD_MAP: list[tuple[str, str]] = [
    ("PILAR", "pilar"),
    ("COLUNA", "pilar"),
    ("VIGA", "viga"),
    ("LAJE", "laje"),
    ("ESTACA", "estaca"),
    ("FUNDA", "fundacao"),
    ("SAPATA", "fundacao"),
    ("BALDAME", "fundacao"),
    ("PAREDE ESTRUTURAL", "parede_estrutural"),
    ("PAREDE PORTANTE", "parede_estrutural"),
]


def classificar_elemento_estrutural(layer: str, tipo: str = "") -> str:
    """
    Subclassifica um elemento ESTRUTURAL em pilar, viga, laje, estaca,
    fundacao, parede_estrutural ou outro.

    Args:
        layer: nome da layer do elemento
        tipo: tipo da entidade (LINE, INSERT, etc.)

    Returns:
        Subcategoria estrutural
    """
    lookup = layer.upper()
    for keyword, categoria in _KEYWORD_MAP:
        if keyword in lookup:
            return categoria
    return "outro"


# ---------------------------------------------------------------------------
# Analise estrutural principal
# ---------------------------------------------------------------------------

def analisar_estrutural(dados: DXFExtractResponse) -> dict[str, Any]:
    """
    Analisa elementos estruturais de uma extracao DXF.

    Filtra elementos com disciplina ESTRUTURAL, subclassifica por tipo,
    calcula metricas (quantidade, comprimento, area) e estima volumes
    com secoes tipicas.

    Args:
        dados: resultado da extracao DXF

    Returns:
        Dict com elementos, resumo e textos_estruturais
    """
    # Acumuladores por tipo
    acumuladores: dict[str, dict[str, float]] = defaultdict(lambda: {
        "quantidade": 0,
        "comprimento_total": 0.0,
        "area_total": 0.0,
    })

    textos_estruturais: list[str] = []

    # 1. Filtrar e classificar elementos geometricos
    for elem in dados.elementos:
        if elem.disciplina != "ESTRUTURAL":
            continue
        subtipo = classificar_elemento_estrutural(elem.layer, elem.tipo)
        acc = acumuladores[subtipo]
        acc["quantidade"] += 1
        if elem.comprimento:
            acc["comprimento_total"] += elem.comprimento
        if elem.area:
            acc["area_total"] += elem.area

    # 2. Filtrar e classificar blocos
    for bloco in dados.blocos:
        if bloco.disciplina != "ESTRUTURAL":
            continue
        subtipo = classificar_elemento_estrutural(bloco.layer, bloco.bloco)
        acumuladores[subtipo]["quantidade"] += 1

    # 3. Filtrar textos estruturais
    for texto in dados.textos:
        if texto.disciplina == "ESTRUTURAL":
            textos_estruturais.append(texto.texto)

    # 4. Filtrar hatches estruturais (areas de laje, fundacao)
    for hatch in dados.hatches:
        if hatch.disciplina != "ESTRUTURAL":
            continue
        subtipo = classificar_elemento_estrutural(hatch.layer)
        if subtipo in ("laje", "fundacao", "parede_estrutural"):
            acumuladores[subtipo]["area_total"] += hatch.area

    # 5. Calcular volumes estimados
    elementos_resultado: list[dict[str, Any]] = []
    for tipo in TODOS_OS_TIPOS:
        acc = acumuladores.get(tipo)
        if not acc or acc["quantidade"] == 0:
            continue

        volume = _estimar_volume(tipo, acc)
        elementos_resultado.append({
            "tipo": tipo,
            "quantidade": acc["quantidade"],
            "comprimento_total": round(acc["comprimento_total"], 2),
            "area_total": round(acc["area_total"], 2),
            "volume_estimado": round(volume, 2) if volume is not None else None,
        })

    # 6. Incluir "outro" se houver
    acc_outro = acumuladores.get("outro")
    if acc_outro and acc_outro["quantidade"] > 0:
        elementos_resultado.append({
            "tipo": "outro",
            "quantidade": acc_outro["quantidade"],
            "comprimento_total": round(acc_outro["comprimento_total"], 2),
            "area_total": round(acc_outro["area_total"], 2),
            "volume_estimado": None,
        })

    # 7. Montar resumo
    total_elementos = sum(e["quantidade"] for e in elementos_resultado)
    volume_total = sum(
        e["volume_estimado"]
        for e in elementos_resultado
        if e.get("volume_estimado") is not None
    )
    tipos_encontrados = [e["tipo"] for e in elementos_resultado if e["tipo"] != "outro"]
    tipos_ausentes = [t for t in TODOS_OS_TIPOS if t not in tipos_encontrados]

    resumo = {
        "total_elementos_estruturais": total_elementos,
        "volume_total_concreto_m3": round(volume_total, 2),
        "tipos_encontrados": tipos_encontrados,
        "tipos_ausentes": tipos_ausentes,
    }

    return {
        "elementos": elementos_resultado,
        "resumo": resumo,
        "textos_estruturais": textos_estruturais,
    }


def _estimar_volume(tipo: str, acc: dict[str, float]) -> float | None:
    """
    Estima o volume de concreto de um tipo estrutural usando secoes tipicas.
    """
    secao = SECOES_TIPICAS.get(tipo)
    if not secao:
        return None

    if tipo == "pilar":
        # Volume = area_secao x pe_direito x quantidade
        return secao["area_secao"] * secao["pe_direito"] * acc["quantidade"]

    if tipo == "viga":
        # Volume = secao_transversal x comprimento_total
        return secao["secao_transversal"] * acc["comprimento_total"]

    if tipo == "estaca":
        # Volume = area_secao x profundidade x quantidade
        return secao["area_secao"] * secao["profundidade"] * acc["quantidade"]

    if tipo == "laje":
        # Volume = area_total x espessura
        return acc["area_total"] * secao["espessura"]

    if tipo == "fundacao":
        # Volume = area_total x espessura
        return acc["area_total"] * secao["espessura"]

    if tipo == "parede_estrutural":
        # Volume = comprimento_total x pe_direito x espessura
        pe_direito = 3.0  # padrao
        return acc["comprimento_total"] * pe_direito * secao["espessura"]

    return None
