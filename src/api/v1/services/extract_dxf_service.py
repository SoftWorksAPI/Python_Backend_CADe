from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from tempfile import NamedTemporaryFile

import ezdxf
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import polygonize

from src.api.v1.schemas.dxf_schemas import (
    BlockItem,
    DimensionItem,
    DXFExtractRequest,
    DXFExtractResponse,
    ElementItem,
    EnvironmentItem,
    GeometriaInternaItem,
    HatchItem,
    LeaderItem,
    SummaryItem,
    TextItem,
)


class DXFExtractionError(Exception):
    """Raised when the uploaded DXF cannot be processed."""


# ---------------------------------------------------------------------------
# Prompt de IA
# ---------------------------------------------------------------------------

def _generate_ai_prompt_string(response: DXFExtractResponse) -> str:
    """
    Gera um prompt completo como uma string unica contendo instrucoes e JSON.

    Args:
        response: A resposta da extracao DXF

    Returns:
        String contendo o prompt completo formatado
    """

    json_data = json.dumps(
        response.model_dump(),
        indent=2,
        ensure_ascii=False,
        default=str
    )

    prompt_string = f"""Voce e um assistente especializado em analise de projetos arquitetonicos e de engenharia baseados em arquivos DXF.

OBJETIVO:
Gere um relatorio profissional e detalhado com base nos dados de extracao do arquivo DXF fornecido abaixo.

O relatorio DEVE conter as seguintes secoes:
1. RESUMO EXECUTIVO: Visao geral do projeto, arquivo analisado e quantidade total de entidades
2. ANALISE DE ELEMENTOS: Detalhamento de linhas, polylines, circulos, arcos, splines e areas por disciplina (ESTRUTURAL, ELETRICO, HIDROSSANITARIO, PORTA, JANELA, ARQUITETONICO)
3. ANALISE DE BLOCOS: Identificacao de blocos/simbolos, circuitos, cabos, cargas e geometria interna
4. ANALISE DE TEXTOS: Textos encontrados no desenho, organizados por disciplina e layer
5. ANALISE DE COTAS (DIMENSIONS): Valores de cotas encontrados, organizados por disciplina
6. ANALISE DE ANOTACOES (LEADERS): Textos de anotacao e lideres tecnicos encontrados
7. ANALISE DE HATCHES: Hachuras identificadas com areas e pontos semente
8. ANALISE DE AMBIENTES: Areas e perimetros dos ambientes identificados, com analise de funcionalidade
9. RECOMENDACOES: Sugestoes baseadas nos dados encontrados, alertando sobre inconsistencias

INSTRUCOES DE FORMATACAO:
- Use Markdown com secoes bem hierarquizadas
- Crie tabelas para dados tabulares quando apropriado
- Use linguagem profissional adequada para stakeholders
- Destaque alertas sobre possiveis inconsistencias nos dados
- Inclua analises quantitativas e insights valiosos

CONTEXTO DE DISCIPLINAS:
- ESTRUTURAL: Pilares, vigas, elementos de estrutura
- ELETRICO: Circuitos, fiacao, componentes eletricos
- HIDROSSANITARIO: Tubulacoes, pecas de agua e esgoto
- PORTA: Elementos de acesso
- JANELA: Aberturas e vaos
- ARQUITETONICO: Elementos gerais de arquitetura

DADOS DO ARQUIVO DXF (JSON):
{json_data}

Gere agora um relatorio profissional, completo e bem estruturado baseado nesses dados."""

    return prompt_string


# ---------------------------------------------------------------------------
# Classificacao de disciplinas
# ---------------------------------------------------------------------------

def _classificar(layer: str, texto: str = "", nome_bloco: str = "") -> str:
    """
    Classifica uma entidade em uma disciplina com base no layer, texto e nome do bloco.
    """
    lookup = f"{layer} {texto} {nome_bloco}".upper()

    # Eletrico
    if any(kw in lookup for kw in ("ELE", "CIRCUITO", "QUADRO", "ILUMINACAO", "TOMADA", "ELETRO")):
        return "ELETRICO"

    # Hidrossanitario
    if any(kw in lookup for kw in ("HIDRO", "AGUA", "ESGOTO", "SANIT", "PLUV", "DRENAGEM")):
        return "HIDROSSANITARIO"

    # Estrutural
    if any(kw in lookup for kw in ("VIGA", "PILAR", "LAJE", "ESTACA", "FUNDA", "ESTRUT", "S-", "STR-")):
        return "ESTRUTURAL"

    # Arquitetonico — antes de porta/janela para captar sublayers
    if any(kw in lookup for kw in ("ARQ", "ARQUITET", "PAREDE", "MURO", "FORRO", "PISO", "COBERTURA")):
        return "ARQUITETONICO"

    # Porta
    if "PORTA" in lookup or "PORT" in lookup:
        return "PORTA"

    # Janela
    if "JANELA" in lookup or "JAN" in lookup or "JNL" in lookup:
        return "JANELA"

    # SPDA / Protecao
    if any(kw in lookup for kw in ("SPDA", "PARA-RAIOS", "PARARAIOS")):
        return "ELETRICO"

    # Paisagismo
    if any(kw in lookup for kw in ("PAISAG", "PLANT", "JARDIM")):
        return "PAISAGISMO"

    # Mobiliario
    if any(kw in lookup for kw in ("MOBILI", "MOVEIS", "MOVEL")):
        return "MOBILIARIO"

    return "ARQUITETONICO"


# ---------------------------------------------------------------------------
# Parsing de circuito em atributos de bloco
# ---------------------------------------------------------------------------

def _parse_circuito(texto: str) -> dict[str, str]:
    dados: dict[str, str] = {}

    for campo in ["CIRC", "CABO", "CARGA"]:
        match = re.search(fr"{campo}:\s*([^,]+)", texto)
        if match:
            dados[campo.lower()] = match.group(1).strip()

    return dados


# ---------------------------------------------------------------------------
# Conversores de geometria para Shapely
# ---------------------------------------------------------------------------

def _line_to_shape(entity) -> LineString | None:
    try:
        return LineString(
            [
                (entity.dxf.start.x, entity.dxf.start.y),
                (entity.dxf.end.x, entity.dxf.end.y),
            ]
        )
    except Exception:
        return None


def _polyline_to_shape(entity) -> LineString | None:
    points: list[tuple[float, float]] = []

    try:
        points = [(point[0], point[1]) for point in entity.get_points()]
    except Exception:
        try:
            for vertex in entity.vertices:
                location = vertex.dxf.location
                points.append((location.x, location.y))
        except Exception:
            return None

    if len(points) < 2:
        return None

    return LineString(points)


def _arc_to_linestring(entity, num_segments: int = 32) -> LineString | None:
    """Converte um ARC em LineString aproximado por segmentos."""
    try:
        center = entity.dxf.center
        radius = entity.dxf.radius
        start_angle = math.radians(entity.dxf.start_angle)
        end_angle = math.radians(entity.dxf.end_angle)

        if end_angle <= start_angle:
            end_angle += 2 * math.pi

        points: list[tuple[float, float]] = []
        for i in range(num_segments + 1):
            angle = start_angle + (end_angle - start_angle) * i / num_segments
            x = center.x + radius * math.cos(angle)
            y = center.y + radius * math.sin(angle)
            points.append((round(x, 4), round(y, 4)))

        return LineString(points)
    except Exception:
        return None


def _circle_to_polygon(entity, num_segments: int = 36) -> Polygon | None:
    """Converte um CIRCLE em Polygon aproximado."""
    try:
        center = entity.dxf.center
        radius = entity.dxf.radius

        points: list[tuple[float, float]] = []
        for i in range(num_segments):
            angle = 2 * math.pi * i / num_segments
            x = center.x + radius * math.cos(angle)
            y = center.y + radius * math.sin(angle)
            points.append((round(x, 4), round(y, 4)))

        points.append(points[0])  # fechar o poligono
        return Polygon(points)
    except Exception:
        return None


def _ellipse_to_polygon(entity, num_segments: int = 36) -> Polygon | None:
    """Converte um ELLIPSE em Polygon aproximado."""
    try:
        center = entity.dxf.center
        major_axis = entity.dxf.major_axis
        ratio = entity.dxf.ratio

        a = math.sqrt(major_axis.x ** 2 + major_axis.y ** 2)
        b = a * ratio
        rotation = math.atan2(major_axis.y, major_axis.x)

        points: list[tuple[float, float]] = []
        for i in range(num_segments):
            angle = 2 * math.pi * i / num_segments
            x_local = a * math.cos(angle)
            y_local = b * math.sin(angle)
            x = center.x + x_local * math.cos(rotation) - y_local * math.sin(rotation)
            y = center.y + x_local * math.sin(rotation) + y_local * math.cos(rotation)
            points.append((round(x, 4), round(y, 4)))

        points.append(points[0])
        return Polygon(points)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Extracao de HATCH
# ---------------------------------------------------------------------------

def _extract_hatch_areas(entity) -> list[dict]:
    """Extrai areas de HATCH com ponto semente e num_paths."""
    results: list[dict] = []

    for path in entity.paths:
        points: list[tuple[float, float]] = []

        if hasattr(path, "vertices"):
            points = [(vertex[0], vertex[1]) for vertex in path.vertices]

        if len(points) < 3:
            continue

        polygon = Polygon(points)

        if polygon.is_valid and polygon.area > 0:
            results.append({
                "area": float(polygon.area),
                "ponto_semente": None,
                "num_paths": len(entity.paths),
            })

    # Adicionar ponto semente se disponivel
    seed_points = []
    try:
        for path in entity.paths:
            if hasattr(path, "seed_point") and path.seed_point:
                seed_points.append((round(path.seed_point[0], 4), round(path.seed_point[1], 4)))
    except Exception:
        pass

    if results and seed_points:
        for i, r in enumerate(results):
            if i < len(seed_points):
                r["ponto_semente"] = seed_points[i]

    return results


# ---------------------------------------------------------------------------
# Extracao de DIMENSION
# ---------------------------------------------------------------------------

def _extrair_dimension(entity, layer: str) -> dict | None:
    """Extrai dados de uma entidade DIMENSION."""
    try:
        valor_texto = ""
        valor_medido = None
        ponto_definicao = (0.0, 0.0)
        ponto_texto = None

        # Valor do texto da dimensao
        if hasattr(entity.dxf, "text"):
            valor_texto = str(entity.dxf.text or "")

        # Texto override (se o usuario alterou)
        try:
            if hasattr(entity, "text") and entity.text:
                valor_texto = str(entity.text)
        except Exception:
            pass

        # Valor numerico medido
        if hasattr(entity.dxf, "measurement"):
            try:
                valor_medido = float(entity.dxf.measurement)
            except Exception:
                pass

        # Se nao tem measurement, tentar via o metodo measurement()
        if valor_medido is None:
            try:
                valor_medido = float(entity.measurement())
            except Exception:
                pass

        # Ponto de definicao (defpoint)
        if hasattr(entity.dxf, "defpoint"):
            dp = entity.dxf.defpoint
            ponto_definicao = (round(dp.x, 4), round(dp.y, 4))

        # Ponto do texto (defpoint2 ou text_midpoint)
        if hasattr(entity.dxf, "defpoint2"):
            dp2 = entity.dxf.defpoint2
            ponto_texto = (round(dp2.x, 4), round(dp2.y, 4))
        elif hasattr(entity.dxf, "text_midpoint"):
            tm = entity.dxf.text_midpoint
            ponto_texto = (round(tm.x, 4), round(tm.y, 4))

        return {
            "valor_texto": valor_texto,
            "valor_medido": valor_medido,
            "ponto_definicao": ponto_definicao,
            "ponto_texto": ponto_texto,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Extracao de LEADER / MLEADER
# ---------------------------------------------------------------------------

def _extrair_leader(entity, layer: str) -> dict | None:
    """Extrai dados de uma entidade LEADER."""
    try:
        vertices: list[tuple[float, float]] = []
        if hasattr(entity, "vertices"):
            for v in entity.vertices:
                vertices.append((round(v.x, 4), round(v.y, 4)))

        texto = ""
        if hasattr(entity, "annotation") and entity.annotation:
            try:
                texto = str(entity.annotation.dxf.text or "")
            except Exception:
                pass

        return {
            "tipo": "LEADER",
            "texto": texto,
            "vertices": vertices,
        }
    except Exception:
        return None


def _extrair_mleader(entity, layer: str) -> dict | None:
    """Extrai dados de uma entidade MLEADER."""
    try:
        texto = ""
        try:
            if hasattr(entity, "text"):
                texto = str(entity.text or "")
            elif hasattr(entity, "context_data"):
                texto = str(getattr(entity.context_data, "text", "") or "")
        except Exception:
            pass

        vertices: list[tuple[float, float]] = []
        try:
            if hasattr(entity, "leader_line"):
                for line in entity.leader_line:
                    for pt in line.vertices:
                        vertices.append((round(pt.x, 4), round(pt.y, 4)))
        except Exception:
            pass

        # Fallback: tentar pegar vertices do dogleg
        if not vertices:
            try:
                if hasattr(entity, "dogleg_points"):
                    for pt in entity.dogleg_points:
                        vertices.append((round(pt.x, 4), round(pt.y, 4)))
            except Exception:
                pass

        return {
            "tipo": "MLEADER",
            "texto": texto,
            "vertices": vertices,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Extracao de geometria interna de blocos
# ---------------------------------------------------------------------------

def _extrair_geometria_bloco(doc, nome_bloco: str) -> list[GeometriaInternaItem]:
    """Extrai a geometria interna das entidades dentro de um bloco definido."""
    geometria: list[GeometriaInternaItem] = []

    try:
        block = doc.blocks.get(nome_bloco)
        if block is None:
            return geometria

        for entity in block:
            entity_type = entity.dxftype()
            layer = str(getattr(entity.dxf, "layer", "0"))
            dados: dict = {}

            try:
                if entity_type == "LINE":
                    dados = {
                        "inicio": (round(entity.dxf.start.x, 4), round(entity.dxf.start.y, 4)),
                        "fim": (round(entity.dxf.end.x, 4), round(entity.dxf.end.y, 4)),
                        "comprimento": round(entity.dxf.start.distance(entity.dxf.end), 4),
                    }
                elif entity_type == "LWPOLYLINE":
                    pontos = [(round(p[0], 4), round(p[1], 4)) for p in entity.get_points()]
                    dados = {"pontos": pontos, "fechada": entity.closed, "num_pontos": len(pontos)}
                elif entity_type == "POLYLINE":
                    pontos = [(round(v.dxf.location.x, 4), round(v.dxf.location.y, 4)) for v in entity.vertices]
                    dados = {"pontos": pontos, "fechada": bool(entity.dxf.flags & 1), "num_pontos": len(pontos)}
                elif entity_type == "CIRCLE":
                    dados = {
                        "centro": (round(entity.dxf.center.x, 4), round(entity.dxf.center.y, 4)),
                        "raio": round(entity.dxf.radius, 4),
                    }
                elif entity_type == "ARC":
                    dados = {
                        "centro": (round(entity.dxf.center.x, 4), round(entity.dxf.center.y, 4)),
                        "raio": round(entity.dxf.radius, 4),
                        "angulo_inicio": round(entity.dxf.start_angle, 4),
                        "angulo_fim": round(entity.dxf.end_angle, 4),
                    }
                elif entity_type in {"TEXT", "MTEXT"}:
                    texto = entity.dxf.text if entity_type == "TEXT" else entity.text
                    dados = {"texto": str(texto)}
                elif entity_type == "INSERT":
                    dados = {"nome_bloco": str(entity.dxf.name)}
                else:
                    dados = {"tipo_original": entity_type}
            except Exception:
                dados = {"tipo_original": entity_type, "erro": "falha na extracao"}

            geometria.append(
                GeometriaInternaItem(
                    tipo=entity_type,
                    layer=layer,
                    dados=dados,
                )
            )
    except Exception:
        pass

    return geometria


# ---------------------------------------------------------------------------
# Leitura do arquivo DXF
# ---------------------------------------------------------------------------

def _read_dxf_from_bytes(content: bytes):
    temp_path = ""

    try:
        with NamedTemporaryFile(delete=False, suffix=".dxf") as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        return ezdxf.readfile(temp_path)
    except Exception as exc:
        raise DXFExtractionError("Nao foi possivel ler o arquivo DXF enviado.") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


# ---------------------------------------------------------------------------
# Funcao principal de extracao
# ---------------------------------------------------------------------------

def extract_dxf_from_upload(
    filename: str,
    content: bytes,
    options: DXFExtractRequest,
) -> DXFExtractResponse:
    if not content:
        raise DXFExtractionError("O arquivo enviado esta vazio.")

    doc = _read_dxf_from_bytes(content)
    modelspace = doc.modelspace()

    total_entidades = 0
    linhas: list[LineString] = []
    elementos: list[ElementItem] = []
    blocos: list[BlockItem] = []
    textos: list[TextItem] = []
    dimensions: list[DimensionItem] = []
    leaders: list[LeaderItem] = []
    hatches: list[HatchItem] = []

    for entity in modelspace:
        total_entidades += 1

        layer = str(getattr(entity.dxf, "layer", "0"))
        entity_type = entity.dxftype()

        try:
            # --- LINE ---
            if entity_type == "LINE":
                shape = _line_to_shape(entity)
                if shape is None:
                    continue

                linhas.append(shape)

                if options.include_elements:
                    elementos.append(
                        ElementItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            tipo="LINE",
                            comprimento=float(shape.length),
                        )
                    )

            # --- LWPOLYLINE / POLYLINE ---
            elif entity_type in {"LWPOLYLINE", "POLYLINE"}:
                shape = _polyline_to_shape(entity)
                if shape is None:
                    continue

                linhas.append(shape)

                if options.include_elements:
                    elementos.append(
                        ElementItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            tipo="POLYLINE",
                            comprimento=float(shape.length),
                        )
                    )

            # --- ARC ---
            elif entity_type == "ARC":
                shape = _arc_to_linestring(entity)
                if shape is not None:
                    linhas.append(shape)

                if options.include_elements:
                    elementos.append(
                        ElementItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            tipo="ARC",
                            comprimento=float(shape.length) if shape else None,
                        )
                    )

            # --- CIRCLE ---
            elif entity_type == "CIRCLE":
                polygon = _circle_to_polygon(entity)
                if polygon is not None:
                    linhas.append(polygon.exterior)

                if options.include_elements:
                    elementos.append(
                        ElementItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            tipo="CIRCLE",
                            area=float(polygon.area) if polygon else None,
                            comprimento=float(polygon.length) if polygon else None,
                        )
                    )

            # --- ELLIPSE ---
            elif entity_type == "ELLIPSE":
                polygon = _ellipse_to_polygon(entity)
                if polygon is not None:
                    linhas.append(polygon.exterior)

                if options.include_elements:
                    elementos.append(
                        ElementItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            tipo="ELLIPSE",
                            area=float(polygon.area) if polygon else None,
                            comprimento=float(polygon.length) if polygon else None,
                        )
                    )

            # --- SPLINE ---
            elif entity_type == "SPLINE":
                try:
                    pontos_controle = [(round(p[0], 4), round(p[1], 4)) for p in entity.control_points]
                    if len(pontos_controle) >= 2:
                        shape = LineString(pontos_controle)
                        linhas.append(shape)

                        if options.include_elements:
                            elementos.append(
                                ElementItem(
                                    layer=layer,
                                    disciplina=_classificar(layer),
                                    tipo="SPLINE",
                                    comprimento=float(shape.length),
                                )
                            )
                except Exception:
                    pass

            # --- POINT ---
            elif entity_type == "POINT":
                if options.include_elements:
                    try:
                        pos = (round(entity.dxf.location.x, 4), round(entity.dxf.location.y, 4))
                        elementos.append(
                            ElementItem(
                                layer=layer,
                                disciplina=_classificar(layer),
                                tipo="POINT",
                            )
                        )
                    except Exception:
                        pass

            # --- HATCH ---
            elif entity_type == "HATCH":
                hatch_results = _extract_hatch_areas(entity)

                for hr in hatch_results:
                    if options.include_elements:
                        elementos.append(
                            ElementItem(
                                layer=layer,
                                disciplina=_classificar(layer),
                                tipo="AREA",
                                area=hr["area"],
                            )
                        )

                    hatches.append(
                        HatchItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            area=hr["area"],
                            num_paths=hr["num_paths"],
                            ponto_semente=hr.get("ponto_semente"),
                        )
                    )

            # --- DIMENSION ---
            elif entity_type == "DIMENSION":
                dim_data = _extrair_dimension(entity, layer)
                if dim_data:
                    dimensions.append(
                        DimensionItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            valor_texto=dim_data["valor_texto"],
                            valor_medido=dim_data["valor_medido"],
                            ponto_definicao=dim_data["ponto_definicao"],
                            ponto_texto=dim_data.get("ponto_texto"),
                        )
                    )

            # --- LEADER ---
            elif entity_type == "LEADER":
                leader_data = _extrair_leader(entity, layer)
                if leader_data:
                    leaders.append(
                        LeaderItem(
                            layer=layer,
                            disciplina=_classificar(layer, leader_data.get("texto", "")),
                            tipo="LEADER",
                            texto=leader_data.get("texto", ""),
                            vertices=leader_data.get("vertices", []),
                        )
                    )

            # --- MLEADER ---
            elif entity_type == "MLEADER":
                mleader_data = _extrair_mleader(entity, layer)
                if mleader_data:
                    leaders.append(
                        LeaderItem(
                            layer=layer,
                            disciplina=_classificar(layer, mleader_data.get("texto", "")),
                            tipo="MLEADER",
                            texto=mleader_data.get("texto", ""),
                            vertices=mleader_data.get("vertices", []),
                        )
                    )

            # --- INSERT (blocos) ---
            elif entity_type == "INSERT" and options.include_blocks:
                nome = str(getattr(entity.dxf, "name", ""))

                # Coletar atributos (ATTRIB) do bloco
                attrs_text_parts: list[str] = []
                attrib_values: dict[str, str] = {}

                if entity.attribs:
                    for attr in entity.attribs:
                        attr_text = str(attr.dxf.text or "")
                        attr_tag = str(attr.dxf.tag or "")
                        attrs_text_parts.append(attr_text)
                        if attr_tag:
                            attrib_values[attr_tag] = attr_text

                attrs = " ".join(attrs_text_parts)
                texto = f"{nome} {attrs}".strip()
                circuito = _parse_circuito(texto)

                # Geometria interna do bloco
                geo_interna = _extrair_geometria_bloco(doc, nome)

                blocos.append(
                    BlockItem(
                        layer=layer,
                        disciplina=_classificar(layer, texto, nome),
                        bloco=nome,
                        texto=texto,
                        circ=circuito.get("circ"),
                        cabo=circuito.get("cabo"),
                        carga=circuito.get("carga"),
                        geometria_interna=geo_interna,
                    )
                )

            # --- TEXT / MTEXT ---
            elif entity_type in {"TEXT", "MTEXT"} and options.include_texts:
                content_text = entity.dxf.text if entity_type == "TEXT" else entity.text

                textos.append(
                    TextItem(
                        layer=layer,
                        disciplina=_classificar(layer, str(content_text)),
                        texto=str(content_text),
                    )
                )

        except Exception:
            # Keeps extraction resilient to malformed entities.
            continue

    # --- Deteccao de ambientes ---
    ambientes: list[EnvironmentItem] = []

    if options.include_environments:
        try:
            polygons = list(polygonize(linhas))
        except Exception:
            polygons = []

        for index, polygon in enumerate(polygons, start=1):
            if polygon.area >= options.min_environment_area:
                ambientes.append(
                    EnvironmentItem(
                        ambiente=f"Amb_{index}",
                        area=float(polygon.area),
                        perimetro=float(polygon.length),
                    )
                )

    # --- Resumo ---
    resumo: list[SummaryItem] = []

    if options.include_elements:
        grouped: defaultdict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: {
                "quantidade": 0,
                "total_comprimento": 0.0,
                "total_area": 0.0,
            }
        )

        for item in elementos:
            key = (item.layer, item.tipo)
            grouped[key]["quantidade"] += 1

            if item.comprimento is not None:
                grouped[key]["total_comprimento"] += item.comprimento

            if item.area is not None:
                grouped[key]["total_area"] += item.area

        for (layer, tipo), values in sorted(grouped.items()):
            resumo.append(
                SummaryItem(
                    layer=layer,
                    tipo=tipo,
                    quantidade=int(values["quantidade"]),
                    total_comprimento=float(values["total_comprimento"]),
                    total_area=float(values["total_area"]),
                )
            )

    return DXFExtractResponse(
        arquivo=filename,
        total_entidades=total_entidades,
        resumo=resumo,
        elementos=elementos if options.include_elements else [],
        blocos=blocos if options.include_blocks else [],
        textos=textos if options.include_texts else [],
        ambientes=ambientes if options.include_environments else [],
        dimensions=dimensions,
        leaders=leaders,
        hatches=hatches,
    )
