from __future__ import annotations

import os
import re
from collections import defaultdict
from tempfile import NamedTemporaryFile

import ezdxf
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize

from src.api.v1.schemas.dxf_schemas import (
    BlockItem,
    DXFExtractRequest,
    DXFExtractResponse,
    ElementItem,
    EnvironmentItem,
    SummaryItem,
    TextItem,
)


class DXFExtractionError(Exception):
    """Raised when the uploaded DXF cannot be processed."""


def _classificar(layer: str, texto: str = "") -> str:
    lookup = f"{layer} {texto}".upper()

    if "ELE" in lookup or "CIRCUITO" in lookup:
        return "ELETRICO"
    if "HIDRO" in lookup or "AGUA" in lookup:
        return "HIDROSSANITARIO"
    if "VIGA" in lookup or "PILAR" in lookup:
        return "ESTRUTURAL"
    if "PORTA" in lookup:
        return "PORTA"
    if "JANELA" in lookup:
        return "JANELA"

    return "ARQUITETONICO"


def _parse_circuito(texto: str) -> dict[str, str]:
    dados: dict[str, str] = {}

    for campo in ["CIRC", "CABO", "CARGA"]:
        match = re.search(fr"{campo}:\s*([^,]+)", texto)
        if match:
            dados[campo.lower()] = match.group(1).strip()

    return dados


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


def _extract_hatch_areas(entity) -> list[float]:
    areas: list[float] = []

    for path in entity.paths:
        points: list[tuple[float, float]] = []

        if hasattr(path, "vertices"):
            points = [(vertex[0], vertex[1]) for vertex in path.vertices]

        if len(points) < 3:
            continue

        polygon = Polygon(points)

        if polygon.is_valid and polygon.area > 0:
            areas.append(float(polygon.area))

    return areas


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
                    elementos.append(
                        ElementItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            tipo="LINE",
                            comprimento=float(shape.length),
                        )
                    )

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

            elif entity_type == "HATCH" and options.include_elements:
                for area in _extract_hatch_areas(entity):
                    elementos.append(
                        ElementItem(
                            layer=layer,
                            disciplina=_classificar(layer),
                            tipo="AREA",
                            area=area,
                        )
                    )

            elif entity_type == "INSERT" and options.include_blocks:
                nome = str(getattr(entity.dxf, "name", ""))
                attrs = ""

                if entity.attribs:
                    attrs = " ".join(str(attr.dxf.text) for attr in entity.attribs)

                texto = f"{nome} {attrs}".strip()
                circuito = _parse_circuito(texto)

                blocos.append(
                    BlockItem(
                        layer=layer,
                        disciplina=_classificar(layer, texto),
                        bloco=nome,
                        texto=texto,
                        circ=circuito.get("circ"),
                        cabo=circuito.get("cabo"),
                        carga=circuito.get("carga"),
                    )
                )

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
    )
