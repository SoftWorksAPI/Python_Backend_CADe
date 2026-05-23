"""
Pipeline de IA para geracao de Memorial Descritivo.

4 nos (etapas):
  1. Extracao deterministica (ezdxf)
  2. Analise via LLM (OpenRouter)
  3. Parse e validacao da resposta
  4. Montagem do resultado final
"""
from __future__ import annotations

import json
import re
from typing import Any

from src.api.v1.services.ai.client import chamar_openrouter
from src.api.v1.services.ai.prompts import SYSTEM_PROMPT_AUDITOR, build_user_prompt
from src.api.v1.schemas.dxf_schemas import DXFExtractRequest, DXFExtractResponse
from src.api.v1.services.extract_dxf_service import extract_dxf_from_upload
from src.api.v1.services.rag.retriever import buscar_normas_relevantes


def _node_extraction(
    filename: str,
    content: bytes,
    options: DXFExtractRequest,
) -> DXFExtractResponse:
    """No 1: Extrai dados brutos do DXF usando ezdxf (sem IA)."""
    return extract_dxf_from_upload(
        filename=filename,
        content=content,
        options=options,
    )


def _build_rag_query(dados: DXFExtractResponse) -> str:
    """
    Monta uma query de busca inteligente baseada nos dados extraidos do DXF.
    Coleta textos, disciplinas e nomes de layers para buscar normas relevantes.
    """
    termos: list[str] = []

    # Disciplinas detectadas
    disciplinas = set()
    for el in dados.elementos:
        if el.disciplina and el.disciplina != "ARQUITETONICO":
            disciplinas.add(el.disciplina.lower())
    for blk in dados.blocos:
        if blk.disciplina and blk.disciplina != "ARQUITETONICO":
            disciplinas.add(blk.disciplina.lower())
    for txt in dados.textos:
        if txt.disciplina and txt.disciplina != "ARQUITETONICO":
            disciplinas.add(txt.disciplina.lower())

    # Textos do desenho (primeiros 10, limpos)
    textos_unicos: list[str] = []
    seen = set()
    for t in dados.textos:
        texto = t.texto.strip()
        if len(texto) > 3 and texto not in seen:
            seen.add(texto)
            textos_unicos.append(texto)
        if len(textos_unicos) >= 10:
            break

    # Layers unicos (primeiros 5)
    layers_unicos: list[str] = []
    seen_layers: set[str] = set()
    for el in dados.elementos:
        if el.layer not in seen_layers:
            seen_layers.add(el.layer)
            layers_unicos.append(el.layer)
        if len(layers_unicos) >= 5:
            break

    # Montar query
    if disciplinas:
        termos.append(" ".join(sorted(disciplinas)))
    if textos_unicos:
        termos.append(" ".join(textos_unicos[:5]))
    if layers_unicos:
        termos.append(" ".join(layers_unicos[:3]))

    query = " ".join(termos).strip()

    # Fallback se nao extraiu nada relevante
    if not query or len(query) < 10:
        query = f"normas tecnicas construcao civil {dados.arquivo}"

    return query[:500]  # Limitar tamanho da query


def _node_llm_analysis(
    dados_extracao: DXFExtractResponse,
    normas_contexto: str = "",
) -> str:
    """No 2: Envia os dados extraidos ao LLM via OpenRouter."""
    dados_dict = dados_extracao.model_dump(mode="json")
    user_prompt = build_user_prompt(dados_dict, normas_contexto)

    return chamar_openrouter(
        system_prompt=SYSTEM_PROMPT_AUDITOR,
        user_prompt=user_prompt,
    )


def _node_parse_response(raw_text: str) -> dict[str, Any]:
    """No 3: Tenta parsear o JSON retornado pelo LLM com fallback."""
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {
        "dados_gerais": {
            "nome_obra": "Nao identificado",
            "descricao_geral": raw_text,
        },
        "ambientes": [],
        "elementos_estruturais": {},
        "instalacoes": {},
        "observacoes_tecnicas": [],
        "inconsistencias_detectadas": [
            "Nao foi possivel parsear a resposta do LLM como JSON."
        ],
        "confianca_analise": "baixa",
        "resposta_bruta_llm": raw_text,
    }


def _node_assembly(
    memorial: dict[str, Any],
    dados_extracao: DXFExtractResponse,
    raw_llm_response: str,
) -> dict[str, Any]:
    """No 4: Monta o resultado final com metadados."""
    return {
        "sucesso": True,
        "memorial_descritivo": memorial,
        "dados_extracao": dados_extracao.model_dump(mode="json"),
        "confianca": memorial.get("confianca_analise", "media"),
        "num_inconsistencias": len(
            memorial.get("inconsistencias_detectadas", [])
        ),
    }


def executar_pipeline_memorial(
    filename: str,
    content: bytes,
    options: DXFExtractRequest,
) -> dict[str, Any]:
    """
    Executa o pipeline completo: Extracao -> RAG -> LLM -> Parse -> Montagem.
    """
    try:
        # No 1: Extracao deterministica
        dados = _node_extraction(filename, content, options)

        if dados.total_entidades == 0:
            return {
                "sucesso": False,
                "erro": "Nenhuma entidade encontrada no arquivo DXF.",
                "memorial_descritivo": None,
                "dados_extracao": dados.model_dump(mode="json"),
            }

        # No 1.5: Buscar normas relevantes no RAG baseado nos dados extraidos
        normas_contexto = ""
        try:
            query = _build_rag_query(dados)
            normas_contexto = buscar_normas_relevantes(query=query, k=5)
        except Exception:
            pass  # RAG opcional

        # No 2: Analise via LLM com contexto de normas
        raw_response = _node_llm_analysis(dados, normas_contexto)

        # No 3: Parse da resposta
        memorial = _node_parse_response(raw_response)

        # No 4: Montagem do resultado
        return _node_assembly(memorial, dados, raw_response)

    except Exception as e:
        return {
            "sucesso": False,
            "erro": str(e),
            "memorial_descritivo": None,
            "dados_extracao": None,
        }
