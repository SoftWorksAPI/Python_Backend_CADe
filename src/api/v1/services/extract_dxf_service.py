from __future__ import annotations

from google import genai
import json
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
from src.config import GEMINI_API_KEY


class DXFExtractionError(Exception):
    """Raised when the uploaded DXF cannot be processed."""


def _generate_ai_prompt_string(response: DXFExtractResponse) -> str:
    """
    Gera um prompt completo como uma string única contendo instruções e JSON.
    
    Args:
        response: A resposta da extração DXF
        
    Returns:
        String contendo o prompt completo formatado
    """
    
    json_data = json.dumps(
        response.model_dump(),
        indent=2,
        ensure_ascii=False,
        default=str
    )
    
    prompt_string = f"""Você é um assistente especializado em análise de projetos arquitetônicos e de engenharia baseados em arquivos DXF.

OBJETIVO:
Gere um relatório profissional e detalhado com base nos dados de extração do arquivo DXF fornecido abaixo.

O relatório DEVE conter as seguintes seções:
1. RESUMO EXECUTIVO: Visão geral do projeto, arquivo analisado e quantidade total de entidades
2. ANÁLISE DE ELEMENTOS: Detalhamento de linhas, polylines e áreas por disciplina (ESTRUTURAL, ELETRICO, HIDROSSANITARIO, PORTA, JANELA, ARQUITETONICO)
3. ANÁLISE DE BLOCOS: Identificação de blocos/símbolos, circuitos, cabos e cargas especificadas
4. ANÁLISE DE TEXTOS: Textos encontrados no desenho, organizados por disciplina e layer
5. ANÁLISE DE AMBIENTES: Áreas e perímetros dos ambientes identificados, com análise de funcionalidade
6. RECOMENDAÇÕES: Sugestões baseadas nos dados encontrados, alertando sobre inconsistências

INSTRUÇÕES DE FORMATAÇÃO:
- Use Markdown com seções bem hierarquizadas
- Crie tabelas para dados tabulares quando apropriado
- Use linguagem profissional adequada para stakeholders
- Destaque alertas sobre possíveis inconsistências nos dados
- Inclua análises quantitativas e insights valiosos

CONTEXTO DE DISCIPLINAS:
- ESTRUTURAL: Pilares, vigas, elementos de estrutura
- ELETRICO: Circuitos, fiação, componentes elétricos
- HIDROSSANITARIO: Tubulações, peças de água e esgoto
- PORTA: Elementos de acesso
- JANELA: Aberturas e vãos
- ARQUITETONICO: Elementos gerais de arquitetura

DADOS DO ARQUIVO DXF (JSON):
{json_data}

Gere agora um relatório profissional, completo e bem estruturado baseado nesses dados."""

    return prompt_string


async def generate_ai_report(prompt: str) -> str:
    """
    Gera um relatório usando IA com base no prompt fornecido.
    
    Esta função aciona uma chamada à API de IA com o prompt completo
    contendo instruções e dados extraídos do DXF, retornando um relatório
    profissional e estruturado.
    
    Args:
        prompt: String contendo o prompt completo com instruções, contexto e dados JSON
        
    Returns:
        String contendo a resposta da IA com o relatório gerado em Markdown
        
    Raises:
        Exception: Se houver erro na chamada à API da IA
    """
    client = genai.Client(api_key=GEMINI_API_KEY)

    response = client.models.generate_content(
        model="gemini-3-flash-preview", contents=prompt
    )
    print(response.text)

    return response.text


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
