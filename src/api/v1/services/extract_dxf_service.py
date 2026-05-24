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
# Prompt de IA (legacy — usado pelo endpoint /prompt)
# ---------------------------------------------------------------------------

def generate_ai_prompt_string(response: DXFExtractResponse) -> str:
    json_data = json.dumps(
        response.model_dump(), indent=2, ensure_ascii=False, default=str
    )

    return f"""Voce e um assistente especializado em analise de projetos arquitetonicos e de engenharia baseados em arquivos DXF.

OBJETIVO:
Gere um relatorio profissional e detalhado com base nos dados de extracao do arquivo DXF fornecido abaixo.

DADOS DO ARQUIVO DXF (JSON):
{json_data}

Gere agora um relatorio profissional, completo e bem estruturado baseado nesses dados."""


# ---------------------------------------------------------------------------
# Classificacao de disciplinas
# ---------------------------------------------------------------------------

def _classificar(layer: str, texto: str = "", nome_bloco: str = "") -> str:
    lookup = f"{layer} {texto} {nome_bloco}".upper()

    if any(kw in lookup for kw in ("ELE", "CIRCUITO", "QUADRO", "ILUMINACAO", "TOMADA", "ELETRO")):
        return "ELETRICO"
    if any(kw in lookup for kw in ("HIDRO", "AGUA", "ESGOTO", "SANIT", "PLUV", "DRENAGEM")):
        return "HIDROSSANITARIO"
    if any(kw in lookup for kw in ("VIGA", "PILAR", "LAJE", "ESTACA", "FUNDA", "ESTRUT", "S-", "STR-")):
        return "ESTRUTURAL"
    if any(kw in lookup for kw in ("ARQ", "ARQUITET", "PAREDE", "MURO", "FORRO", "PISO", "COBERTURA")):
        return "ARQUITETONICO"
    if "PORTA" in lookup or "PORT" in lookup:
        return "PORTA"
    if "JANELA" in lookup or "JAN" in lookup or "JNL" in lookup:
        return "JANELA"
    if any(kw in lookup for kw in ("SPDA", "PARA-RAIOS", "PARARAIOS")):
        return "ELETRICO"
    if any(kw in lookup for kw in ("PAISAG", "PLANT", "JARDIM")):
        return "PAISAGISMO"
    if any(kw in lookup for kw in ("MOBILI", "MOVEIS", "MOVEL")):
        return "MOBILIARIO"

    return "ARQUITETONICO"


# ---------------------------------------------------------------------------
# Parsing de circuito
# ---------------------------------------------------------------------------

def _parse_circuito(texto: str) -> dict[str, str]:
    dados: dict[str, str] = {}
    for campo in ["CIRC", "CABO", "CARGA"]:
        match = re.search(fr"{campo}:\s*([^,]+)", texto)
        if match:
            dados[campo.lower()] = match.group(1).strip()
    return dados


# ---------------------------------------------------------------------------
# Conversores de geometria
# ---------------------------------------------------------------------------

def _line_to_shape(entity) -> LineString | None:
    try:
        return LineString([
            (entity.dxf.start.x, entity.dxf.start.y),
            (entity.dxf.end.x, entity.dxf.end.y),
        ])
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
    try:
        center = entity.dxf.center
        radius = entity.dxf.radius
        points: list[tuple[float, float]] = []
        for i in range(num_segments):
            angle = 2 * math.pi * i / num_segments
            x = center.x + radius * math.cos(angle)
            y = center.y + radius * math.sin(angle)
            points.append((round(x, 4), round(y, 4)))
        points.append(points[0])
        return Polygon(points)
    except Exception:
        return None


def _ellipse_to_polygon(entity, num_segments: int = 36) -> Polygon | None:
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
    try:
        valor_texto = ""
        valor_medido = None
        ponto_definicao = (0.0, 0.0)
        ponto_texto = None

        if hasattr(entity.dxf, "text"):
            valor_texto = str(entity.dxf.text or "")
        try:
            if hasattr(entity, "text") and entity.text:
                valor_texto = str(entity.text)
        except Exception:
            pass

        if hasattr(entity.dxf, "measurement"):
            try:
                valor_medido = float(entity.dxf.measurement)
            except Exception:
                pass
        if valor_medido is None:
            try:
                valor_medido = float(entity.measurement())
            except Exception:
                pass

        if hasattr(entity.dxf, "defpoint"):
            dp = entity.dxf.defpoint
            ponto_definicao = (round(dp.x, 4), round(dp.y, 4))
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
        return {"tipo": "LEADER", "texto": texto, "vertices": vertices}
    except Exception:
        return None


def _extrair_mleader(entity, layer: str) -> dict | None:
    try:
        texto = ""
        try:
            if hasattr(entity, "text"):
                texto = str(entity.text or "")
        except Exception:
            pass
        vertices: list[tuple[float, float]] = []
        try:
            if hasattr(entity, "dogleg_points"):
                for pt in entity.dogleg_points:
                    vertices.append((round(pt.x, 4), round(pt.y, 4)))
        except Exception:
            pass
        return {"tipo": "MLEADER", "texto": texto, "vertices": vertices}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Extracao de geometria interna de blocos
# ---------------------------------------------------------------------------

def _extrair_geometria_bloco(doc, nome_bloco: str) -> list[GeometriaInternaItem]:
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
                    }
                elif entity_type == "LWPOLYLINE":
                    pontos = [(round(p[0], 4), round(p[1], 4)) for p in entity.get_points()]
                    dados = {"pontos": pontos, "fechada": entity.closed}
                elif entity_type == "CIRCLE":
                    dados = {
                        "centro": (round(entity.dxf.center.x, 4), round(entity.dxf.center.y, 4)),
                        "raio": round(entity.dxf.radius, 4),
                    }
                elif entity_type == "ARC":
                    dados = {
                        "centro": (round(entity.dxf.center.x, 4), round(entity.dxf.center.y, 4)),
                        "raio": round(entity.dxf.radius, 4),
                    }
                elif entity_type in {"TEXT", "MTEXT"}:
                    texto = entity.dxf.text if entity_type == "TEXT" else entity.text
                    dados = {"texto": str(texto)}
                else:
                    dados = {"tipo_original": entity_type}
            except Exception:
                dados = {"tipo_original": entity_type}

            geometria.append(GeometriaInternaItem(tipo=entity_type, layer=layer, dados=dados))
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
            try:
                os.remove(temp_path)
            except OSError:
                pass


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
            if entity_type == "LINE":
                shape = _line_to_shape(entity)
                if shape is None:
                    continue
                linhas.append(shape)
                if options.include_elements:
                    elementos.append(ElementItem(layer=layer, disciplina=_classificar(layer), tipo="LINE", comprimento=float(shape.length)))

            elif entity_type in {"LWPOLYLINE", "POLYLINE"}:
                shape = _polyline_to_shape(entity)
                if shape is None:
                    continue
                linhas.append(shape)
                if options.include_elements:
                    elementos.append(ElementItem(layer=layer, disciplina=_classificar(layer), tipo="POLYLINE", comprimento=float(shape.length)))

            elif entity_type == "ARC":
                shape = _arc_to_linestring(entity)
                if shape is not None:
                    linhas.append(shape)
                if options.include_elements:
                    elementos.append(ElementItem(layer=layer, disciplina=_classificar(layer), tipo="ARC", comprimento=float(shape.length) if shape else None))

            elif entity_type == "CIRCLE":
                polygon = _circle_to_polygon(entity)
                if polygon is not None:
                    linhas.append(polygon.exterior)
                if options.include_elements:
                    elementos.append(ElementItem(layer=layer, disciplina=_classificar(layer), tipo="CIRCLE", area=float(polygon.area) if polygon else None, comprimento=float(polygon.length) if polygon else None))

            elif entity_type == "ELLIPSE":
                polygon = _ellipse_to_polygon(entity)
                if polygon is not None:
                    linhas.append(polygon.exterior)
                if options.include_elements:
                    elementos.append(ElementItem(layer=layer, disciplina=_classificar(layer), tipo="ELLIPSE", area=float(polygon.area) if polygon else None, comprimento=float(polygon.length) if polygon else None))

            elif entity_type == "SPLINE":
                try:
                    pontos_controle = [(round(p[0], 4), round(p[1], 4)) for p in entity.control_points]
                    if len(pontos_controle) >= 2:
                        shape = LineString(pontos_controle)
                        linhas.append(shape)
                        if options.include_elements:
                            elementos.append(ElementItem(layer=layer, disciplina=_classificar(layer), tipo="SPLINE", comprimento=float(shape.length)))
                except Exception:
                    pass

            elif entity_type == "POINT":
                if options.include_elements:
                    elementos.append(ElementItem(layer=layer, disciplina=_classificar(layer), tipo="POINT"))

            elif entity_type == "HATCH":
                hatch_results = _extract_hatch_areas(entity)
                for hr in hatch_results:
                    if options.include_elements:
                        elementos.append(ElementItem(layer=layer, disciplina=_classificar(layer), tipo="AREA", area=hr["area"]))
                    hatches.append(HatchItem(layer=layer, disciplina=_classificar(layer), area=hr["area"], num_paths=hr["num_paths"], ponto_semente=hr.get("ponto_semente")))

            elif entity_type == "DIMENSION":
                dim_data = _extrair_dimension(entity, layer)
                if dim_data:
                    dimensions.append(DimensionItem(
                        layer=layer, disciplina=_classificar(layer),
                        valor_texto=dim_data["valor_texto"], valor_medido=dim_data["valor_medido"],
                        ponto_definicao=dim_data["ponto_definicao"], ponto_texto=dim_data.get("ponto_texto"),
                    ))

            elif entity_type == "LEADER":
                leader_data = _extrair_leader(entity, layer)
                if leader_data:
                    leaders.append(LeaderItem(
                        layer=layer, disciplina=_classificar(layer, leader_data.get("texto", "")),
                        tipo="LEADER", texto=leader_data.get("texto", ""), vertices=leader_data.get("vertices", []),
                    ))

            elif entity_type == "MLEADER":
                mleader_data = _extrair_mleader(entity, layer)
                if mleader_data:
                    leaders.append(LeaderItem(
                        layer=layer, disciplina=_classificar(layer, mleader_data.get("texto", "")),
                        tipo="MLEADER", texto=mleader_data.get("texto", ""), vertices=mleader_data.get("vertices", []),
                    ))

            elif entity_type == "INSERT" and options.include_blocks:
                nome = str(getattr(entity.dxf, "name", ""))
                attrs_text_parts: list[str] = []
                if entity.attribs:
                    for attr in entity.attribs:
                        attrs_text_parts.append(str(attr.dxf.text or ""))
                attrs = " ".join(attrs_text_parts)
                texto = f"{nome} {attrs}".strip()
                circuito = _parse_circuito(texto)
                geo_interna = _extrair_geometria_bloco(doc, nome)
                blocos.append(BlockItem(
                    layer=layer, disciplina=_classificar(layer, texto, nome),
                    bloco=nome, texto=texto,
                    circ=circuito.get("circ"), cabo=circuito.get("cabo"), carga=circuito.get("carga"),
                    geometria_interna=geo_interna,
                ))

            elif entity_type in {"TEXT", "MTEXT"} and options.include_texts:
                content_text = entity.dxf.text if entity_type == "TEXT" else entity.text
                textos.append(TextItem(layer=layer, disciplina=_classificar(layer, str(content_text)), texto=str(content_text)))

        except Exception:
            continue

    # --- Ambientes ---
    ambientes: list[EnvironmentItem] = []
    if options.include_environments:
        try:
            polygons = list(polygonize(linhas))
        except Exception:
            polygons = []
        for index, polygon in enumerate(polygons, start=1):
            if polygon.area >= options.min_environment_area:
                ambientes.append(EnvironmentItem(ambiente=f"Amb_{index}", area=float(polygon.area), perimetro=float(polygon.length)))

    # --- Resumo ---
    resumo: list[SummaryItem] = []
    if options.include_elements:
        grouped: defaultdict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: {"quantidade": 0, "total_comprimento": 0.0, "total_area": 0.0}
        )
        for item in elementos:
            key = (item.layer, item.tipo)
            grouped[key]["quantidade"] += 1
            if item.comprimento is not None:
                grouped[key]["total_comprimento"] += item.comprimento
            if item.area is not None:
                grouped[key]["total_area"] += item.area
        for (layer, tipo), values in sorted(grouped.items()):
            resumo.append(SummaryItem(
                layer=layer, tipo=tipo,
                quantidade=int(values["quantidade"]),
                total_comprimento=float(values["total_comprimento"]),
                total_area=float(values["total_area"]),
            ))

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
