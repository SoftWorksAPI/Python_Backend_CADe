"""
Pipeline de IA para geracao de Memorial Descritivo.

Implementa uma arquitetura de 4 nos (etapas) inspirada no Blueprint:
  1. Extracao deterministica (ezdxf)
  2. Analise via LLM (Gemini)
  3. Parse e validacao da resposta
  4. Montagem do resultado final

Cada etapa e uma funcao pura que recebe e retorna dados,
facilitando testes e manutencao.
"""
from __future__ import annotations

import json
import re
from typing import Any

from src.config import OPENROUTER_MODEL, OPENROUTER_TEMPERATURE
from src.api.v1.services.ai.client import chamar_openrouter
from src.api.v1.services.ai.prompts import SYSTEM_PROMPT_AUDITOR, build_user_prompt
from src.api.v1.schemas.dxf_schemas import DXFExtractRequest, DXFExtractResponse
from src.api.v1.services.extract_dxf_service import extract_dxf_from_upload


# ---------------------------------------------------------------------------
# No 1 — Extracao deterministica
# ---------------------------------------------------------------------------

def _node_extraction(
    filename: str,
    content: bytes,
    options: DXFExtractRequest,
) -> DXFExtractResponse:
    """Extrai dados brutos do DXF usando ezdxf (sem IA)."""
    return extract_dxf_from_upload(
        filename=filename,
        content=content,
        options=options,
    )


# ---------------------------------------------------------------------------
# No 2 — Analise via LLM
# ---------------------------------------------------------------------------

def _node_llm_analysis(
    dados_extracao: DXFExtractResponse,
) -> str:
    """Envia os dados extraidos ao LLM via OpenRouter com prompt de auditor."""
    dados_dict = dados_extracao.model_dump(mode="json")
    user_prompt = build_user_prompt(dados_dict)

    return chamar_openrouter(
        system_prompt=SYSTEM_PROMPT_AUDITOR,
        user_prompt=user_prompt,
    )


# ---------------------------------------------------------------------------
# No 3 — Parse e validacao da resposta
# ---------------------------------------------------------------------------

def _node_parse_response(raw_text: str) -> dict[str, Any]:
    """
    Tenta parsear o JSON retornado pelo LLM.
    Faz fallback com regex se o LLM envolver o JSON em markdown.
    """
    # Tentar parse direto
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Fallback: extrair JSON de blocos markdown ```json ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fallback: tentar encontrar { ... } no texto
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Se nada funcionar, retorna dict com a resposta bruta
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


# ---------------------------------------------------------------------------
# No 4 — Montagem do resultado final
# ---------------------------------------------------------------------------

def _node_assembly(
    memorial: dict[str, Any],
    dados_extracao: DXFExtractResponse,
    raw_llm_response: str,
) -> dict[str, Any]:
    """Monta o resultado final com metadados e dados brutos."""
    return {
        "sucesso": True,
        "memorial_descritivo": memorial,
        "dados_extracao": dados_extracao.model_dump(mode="json"),
        "confianca": memorial.get("confianca_analise", "media"),
        "num_inconsistencias": len(
            memorial.get("inconsistencias_detectadas", [])
        ),
    }


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def executar_pipeline_memorial(
    filename: str,
    content: bytes,
    options: DXFExtractRequest,
) -> dict[str, Any]:
    """
    Executa o pipeline completo de geracao do Memorial Descritivo.

    Fluxo:
        Extracao -> LLM -> Parse -> Montagem

    Retorna:
        dict com sucesso, memorial_descritivo, dados_extracao, confianca
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

        # No 2: Analise via LLM
        raw_response = _node_llm_analysis(dados)

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
