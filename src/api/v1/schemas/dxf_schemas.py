from __future__ import annotations

from typing import Annotated, Any

from fastapi import Form
from pydantic import BaseModel, Field


class DXFExtractRequest(BaseModel):
    min_environment_area: float = Field(default=1.0, ge=0)
    include_elements: bool = True
    include_blocks: bool = True
    include_texts: bool = True
    include_environments: bool = True

    @classmethod
    def as_form(
        cls,
        min_environment_area: Annotated[float, Form(ge=0)] = 1.0,
        include_elements: Annotated[bool, Form()] = True,
        include_blocks: Annotated[bool, Form()] = True,
        include_texts: Annotated[bool, Form()] = True,
        include_environments: Annotated[bool, Form()] = True,
    ) -> "DXFExtractRequest":
        return cls(
            min_environment_area=min_environment_area,
            include_elements=include_elements,
            include_blocks=include_blocks,
            include_texts=include_texts,
            include_environments=include_environments,
        )


class SummaryItem(BaseModel):
    layer: str
    tipo: str
    quantidade: int
    total_comprimento: float = 0.0
    total_area: float = 0.0


class ElementItem(BaseModel):
    layer: str
    disciplina: str
    tipo: str
    comprimento: float | None = None
    area: float | None = None


class GeometriaInternaItem(BaseModel):
    tipo: str
    layer: str
    dados: dict[str, Any] = Field(default_factory=dict)


class BlockItem(BaseModel):
    layer: str
    disciplina: str
    bloco: str
    texto: str
    circ: str | None = None
    cabo: str | None = None
    carga: str | None = None
    geometria_interna: list[GeometriaInternaItem] = Field(default_factory=list)


class TextItem(BaseModel):
    layer: str
    disciplina: str
    texto: str


class EnvironmentItem(BaseModel):
    ambiente: str
    area: float
    perimetro: float


class DimensionItem(BaseModel):
    layer: str
    disciplina: str
    valor_texto: str
    valor_medido: float | None = None
    ponto_definicao: tuple[float, float]
    ponto_texto: tuple[float, float] | None = None


class LeaderItem(BaseModel):
    layer: str
    disciplina: str
    tipo: str
    texto: str
    vertices: list[tuple[float, float]]


class HatchItem(BaseModel):
    layer: str
    disciplina: str
    area: float
    num_paths: int
    ponto_semente: tuple[float, float] | None = None


class DXFExtractResponse(BaseModel):
    arquivo: str
    total_entidades: int
    resumo: list[SummaryItem] = Field(default_factory=list)
    elementos: list[ElementItem] = Field(default_factory=list)
    blocos: list[BlockItem] = Field(default_factory=list)
    textos: list[TextItem] = Field(default_factory=list)
    ambientes: list[EnvironmentItem] = Field(default_factory=list)
    dimensions: list[DimensionItem] = Field(default_factory=list)
    leaders: list[LeaderItem] = Field(default_factory=list)
    hatches: list[HatchItem] = Field(default_factory=list)
