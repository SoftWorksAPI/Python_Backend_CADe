"""
Servico de chat IA para perguntas sobre projetos processados e normas tecnicas.
"""
from __future__ import annotations

import json
from typing import Any

from src.api.v1.services.ai.client import chamar_openrouter
from src.api.v1.services.rag.retriever import buscar_normas_relevantes

SYSTEM_PROMPT_CHAT = """\
Voce e um assistente tecnico de engenharia civil integrado ao sistema CADe. \
Sua funcao e responder perguntas do usuario sobre um projeto especifico \
(processado a partir de uma planta baixa DXF) e sobre normas tecnicas \
brasileiras de construcao civil.

Regras:
1. Responda APENAS com base nos dados do projeto e nas normas fornecidas.
2. NAO invente dados que nao estejam no contexto fornecido.
3. Se a informacao nao estiver disponivel nos dados do projeto nem nas \
normas, informe claramente que nao ha dados suficientes.
4. Use terminologia tecnica da engenharia civil brasileira.
5. Seja conciso e direto nas respostas.
6. Quando citar normas, indique o codigo (ex: NBR 5410) e o trecho relevante.
7. Responda em portugues do Brasil.
"""

MAX_JSON_CHARS = 6000
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_MSG_CHARS = 500


def _truncar_json(dados: dict[str, Any], limite: int) -> str:
    """Serializa um dict para JSON e trunca no limite de caracteres."""
    texto = json.dumps(dados, indent=2, ensure_ascii=False, default=str)
    if len(texto) > limite:
        return texto[:limite] + "\n... (truncado)"
    return texto


def _build_rag_query(pergunta: str, json_tratado: dict[str, Any]) -> str:
    """
    Monta uma query de busca RAG enriquecida com termos do projeto.
    Combina a pergunta do usuario com dados do memorial tratado.
    """
    termos: list[str] = [pergunta]

    # Extrair dados gerais do memorial
    dados_gerais = json_tratado.get("dados_gerais", {})
    if dados_gerais.get("tipo_construcao"):
        termos.append(dados_gerais["tipo_construcao"])
    if dados_gerais.get("descricao_geral"):
        termos.append(dados_gerais["descricao_geral"][:200])

    # Extrair nomes de ambientes
    ambientes = json_tratado.get("ambientes", [])
    for amb in ambientes[:5]:
        if amb.get("nome"):
            termos.append(amb["nome"])

    # Extrair instalacoes
    instalacoes = json_tratado.get("instalacoes", {})
    for tipo, valor in instalacoes.items():
        if isinstance(valor, str) and valor:
            termos.append(valor[:100])

    query = " ".join(termos).strip()
    return query[:500]


def _formatar_historico(historico: list[dict[str, str]] | None) -> str:
    """Formata o historico de chat para injecao no prompt."""
    if not historico:
        return ""

    # Limitar a ultimas N mensagens
    historico_limited = historico[-MAX_HISTORY_MESSAGES:]

    partes = []
    for msg in historico_limited:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Truncar mensagem longa
        if len(content) > MAX_HISTORY_MSG_CHARS:
            content = content[:MAX_HISTORY_MSG_CHARS] + "..."
        prefixo = "Usuario" if role == "user" else "Assistente"
        partes.append(f"{prefixo}: {content}")

    return "\n".join(partes)


def responder_pergunta_chat(
    pergunta: str,
    json_cru: dict[str, Any],
    json_tratado: dict[str, Any],
    historico: list[dict[str, str]] | None = None,
) -> str:
    """
    Responde uma pergunta do usuario sobre um projeto processado.

    Args:
        pergunta: pergunta do usuario em linguagem natural
        json_cru: dados brutos da extracao DXF
        json_tratado: memorial descritivo tratado pela IA
        historico: historico de mensagens [{role, content}]

    Returns:
        Resposta da IA em texto
    """
    # 1. Buscar normas relevantes via RAG
    normas_contexto = ""
    try:
        query = _build_rag_query(pergunta, json_tratado)
        normas_contexto = buscar_normas_relevantes(query=query, k=5)
    except Exception:
        pass  # RAG opcional, continua sem normas

    # 2. Montar contexto do projeto (truncado)
    json_tratado_str = _truncar_json(json_tratado, MAX_JSON_CHARS)
    json_cru_str = _truncar_json(json_cru, MAX_JSON_CHARS)

    # 3. Formatar historico
    historico_str = _formatar_historico(historico)

    # 4. Montar user prompt
    partes_prompt = []

    partes_prompt.append(
        "================================================================\n"
        "DADOS DO PROJETO (Memorial Descritivo tratado pela IA):\n"
        "================================================================\n"
        f"{json_tratado_str}"
    )

    partes_prompt.append(
        "\n================================================================\n"
        "DADOS BRUTOS DA EXTRACAO DXF:\n"
        "================================================================\n"
        f"{json_cru_str}"
    )

    if normas_contexto:
        partes_prompt.append(
            "\n================================================================\n"
            "NORMAS TECNICAS RELEVANTES:\n"
            "================================================================\n"
            f"{normas_contexto}"
        )

    if historico_str:
        partes_prompt.append(
            "\n================================================================\n"
            "HISTORICO DA CONVERSA:\n"
            "================================================================\n"
            f"{historico_str}"
        )

    partes_prompt.append(
        "\n================================================================\n"
        "PERGUNTA DO USUARIO:\n"
        "================================================================\n"
        f"{pergunta}"
    )

    user_prompt = "\n".join(partes_prompt)

    # 5. Chamar OpenRouter
    resposta = chamar_openrouter(
        system_prompt=SYSTEM_PROMPT_CHAT,
        user_prompt=user_prompt,
    )

    return resposta
