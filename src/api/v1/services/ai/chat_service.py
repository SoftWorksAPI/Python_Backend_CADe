"""
Servico de chat IA para perguntas sobre projetos processados e normas tecnicas.

Cria um RAG temporario in-memory por pergunta contendo:
- Normas do RAG principal (ChromaDB persistente)
- Texto extraido dos reports do projeto

A busca semantica seleciona apenas os chunks mais relevantes.
"""
from __future__ import annotations

import json
from typing import Any

import chromadb

from src.api.v1.services.ai.client import chamar_openrouter
from src.api.v1.services.rag.vectorstore import get_vectorstore
from src.api.v1.services.ai.report_text_extractor import extrair_texto_report

SYSTEM_PROMPT_CHAT = """\
Voce e um assistente tecnico de engenharia civil integrado ao sistema CADe. \
Sua funcao e responder perguntas do usuario sobre um projeto especifico \
(processado a partir de uma planta baixa DXF), sobre normas tecnicas \
brasileiras de construcao civil e sobre os relatorios gerados para o projeto.

Regras:
1. Responda APENAS com base nos dados do projeto, normas e relatorios fornecidos.
2. NAO invente dados que nao estejam no contexto fornecido.
3. Se a informacao nao estiver disponivel, informe claramente que nao ha dados suficientes.
4. Use terminologia tecnica da engenharia civil brasileira.
5. Seja conciso e direto nas respostas.
6. Quando citar normas, indique o codigo (ex: NBR 5410) e o trecho relevante.
7. Quando citar dados de relatorios, indique o nome do relatorio.
8. Responda em portugues do Brasil.
9. Ao final da resposta, quando relevante, liste as fontes consultadas (normas e relatorios).
"""

MAX_JSON_CHARS = 6000
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_MSG_CHARS = 500
MAX_REPORT_CHARS = 4000
MAX_RAG_CHUNKS = 8
REPORT_CHUNK_SIZE = 600
REPORT_CHUNK_OVERLAP = 100


def _truncar_json(dados: dict[str, Any], limite: int) -> str:
    """Serializa um dict para JSON e trunca no limite de caracteres."""
    texto = json.dumps(dados, indent=2, ensure_ascii=False, default=str)
    if len(texto) > limite:
        return texto[:limite] + "\n... (truncado)"
    return texto


def _split_text(texto: str, chunk_size: int = 600, overlap: int = 100) -> list[str]:
    """Divide texto em chunks com overlap."""
    if not texto or not texto.strip():
        return []

    chunks = []
    start = 0
    while start < len(texto):
        end = start + chunk_size
        chunk = texto[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap

    return chunks


def _build_rag_query(pergunta: str, json_tratado: dict[str, Any]) -> str:
    """Monta uma query de busca RAG enriquecida com termos do projeto."""
    termos: list[str] = [pergunta]

    dados_gerais = json_tratado.get("dados_gerais", {})
    if dados_gerais.get("tipo_construcao"):
        termos.append(dados_gerais["tipo_construcao"])
    if dados_gerais.get("descricao_geral"):
        termos.append(dados_gerais["descricao_geral"][:200])

    ambientes = json_tratado.get("ambientes", [])
    for amb in ambientes[:5]:
        if amb.get("nome"):
            termos.append(amb["nome"])

    instalacoes = json_tratado.get("instalacoes", {})
    for tipo, valor in instalacoes.items():
        if isinstance(valor, str) and valor:
            termos.append(valor[:100])

    return " ".join(termos).strip()[:500]


def _formatar_historico(historico: list[dict[str, str]] | None) -> str:
    """Formata o historico de chat para injecao no prompt."""
    if not historico:
        return ""

    historico_limited = historico[-MAX_HISTORY_MESSAGES:]
    partes = []
    for msg in historico_limited:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if len(content) > MAX_HISTORY_MSG_CHARS:
            content = content[:MAX_HISTORY_MSG_CHARS] + "..."
        prefixo = "Usuario" if role == "user" else "Assistente"
        partes.append(f"{prefixo}: {content}")

    return "\n".join(partes)


def _extrair_textos_reports(reports: list[dict[str, str]] | None) -> str:
    """Extrai texto de todos os reports do projeto."""
    if not reports:
        return ""

    textos = []
    total_chars = 0

    for report in reports:
        if total_chars >= MAX_REPORT_CHARS:
            break

        title = report.get("title", "sem titulo")
        file_path = report.get("filePath", "")
        file_type = report.get("fileType", "")

        texto = extrair_texto_report(file_path, file_type, title)

        remaining = MAX_REPORT_CHARS - total_chars
        if len(texto) > remaining:
            texto = texto[:remaining] + "\n... (truncado)"

        textos.append(texto)
        total_chars += len(texto)

    return "\n\n---\n\n".join(textos)


def _buscar_chunks_normas(
    pergunta: str,
    json_tratado: dict[str, Any],
    k: int = 5,
) -> tuple[list[str], list[dict]]:
    """
    Busca chunks de normas do RAG principal.
    Retorna lista de documentos e metadados.
    """
    query = _build_rag_query(pergunta, json_tratado)

    try:
        collection = get_vectorstore()
        if collection.count() == 0:
            return [], []

        results = collection.query(
            query_texts=[query],
            n_results=min(k, collection.count()),
            include=["documents", "metadatas"],
        )

        if not results or not results["documents"] or not results["documents"][0]:
            return [], []

        docs = results["documents"][0]
        metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(docs)

        # Truncar cada chunk
        docs = [doc[:600] for doc in docs]

        return docs, metas
    except Exception:
        return [], []


def _criar_rag_temporario(
    normas_docs: list[str],
    normas_metas: list[dict],
    reports_texto: str,
) -> chromadb.Collection:
    """
    Cria collection ChromaDB in-memory com normas + reports.
    Usa nome unico para evitar conflito entre requisicoes.
    """
    import uuid
    client = chromadb.Client()  # in-memory
    collection_name = f"chat_temp_{uuid.uuid4().hex[:8]}"

    collection = client.create_collection(
        collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Adicionar chunks de normas
    for i, (doc, meta) in enumerate(zip(normas_docs, normas_metas)):
        meta_limpo = {k: str(v) for k, v in meta.items() if v is not None}
        meta_limpo["fonte"] = "norma"
        collection.add(
            ids=[f"norma_{i}"],
            documents=[doc],
            metadatas=[meta_limpo],
        )

    # Adicionar chunks de reports
    if reports_texto:
        report_chunks = _split_text(reports_texto, REPORT_CHUNK_SIZE, REPORT_CHUNK_OVERLAP)
        for i, chunk in enumerate(report_chunks):
            collection.add(
                ids=[f"report_{i}"],
                documents=[chunk],
                metadatas=[{"fonte": "report"}],
            )

    return collection


def _buscar_no_rag_temporario(
    collection: chromadb.Collection,
    query: str,
    k: int = 8,
) -> tuple[str, list[str], list[str]]:
    """
    Busca chunks relevantes no RAG temporario.
    Retorna contexto formatado, fontes de normas e fontes de reports.
    """
    if collection.count() == 0:
        return "", [], []

    results = collection.query(
        query_texts=[query],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas"],
    )

    if not results or not results["documents"] or not results["documents"][0]:
        return "", [], []

    partes = []
    fontes_normas = []
    fontes_reports = []

    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i] if results["metadatas"] else {}
        fonte = meta.get("fonte", "desconhecida")

        if fonte == "norma":
            codigo = meta.get("codigo", "N/A")
            categoria = meta.get("categoria", "")
            partes.append(f"[Norma: {codigo} | {categoria}]\n{doc}")
            if codigo not in fontes_normas:
                fontes_normas.append(codigo)
        else:
            partes.append(f"[Report do projeto]\n{doc}")
            if "report" not in fontes_reports:
                fontes_reports.append("report")

    contexto = "\n---\n".join(partes)
    return contexto, fontes_normas, fontes_reports


def _gerar_sugestoes(
    json_tratado: dict[str, Any],
    historico: list[dict[str, str]] | None = None,
) -> list[str]:
    """Gera sugestoes de perguntas baseadas no contexto do projeto."""
    sugestoes = []

    dados_gerais = json_tratado.get("dados_gerais", {})
    ambientes = json_tratado.get("ambientes", [])
    instalacoes = json_tratado.get("instalacoes", {})
    elementos = json_tratado.get("elementos_estruturais", {})

    if dados_gerais.get("tipo_construcao"):
        sugestoes.append("Qual o tipo de construcao deste projeto?")

    if ambientes:
        sugestoes.append("Quantos ambientes foram identificados e quais sao?")

    if elementos.get("vigas") or elementos.get("pilares"):
        sugestoes.append("Quais elementos estruturais foram encontrados?")

    if instalacoes.get("eletrica"):
        sugestoes.append("Como esta configurada a instalacao eletrica?")

    if instalacoes.get("hidraulica"):
        sugestoes.append("Quais instalacoes hidraulicas foram identificadas?")

    sugestoes.append("Quais normas tecnicas se aplicam a este projeto?")
    sugestoes.append("Existem inconsistencias no projeto?")

    return sugestoes[:5]


def _construir_prompt(
    pergunta: str,
    json_cru: dict[str, Any],
    json_tratado: dict[str, Any],
    historico: list[dict[str, str]] | None,
    contexto_rag: str,
) -> str:
    """Monta o prompt completo para o LLM."""
    json_tratado_str = _truncar_json(json_tratado, MAX_JSON_CHARS)
    json_cru_str = _truncar_json(json_cru, MAX_JSON_CHARS)
    historico_str = _formatar_historico(historico)

    partes = []

    partes.append(
        "================================================================\n"
        "DADOS DO PROJETO (Memorial Descritivo tratado pela IA):\n"
        "================================================================\n"
        f"{json_tratado_str}"
    )

    partes.append(
        "\n================================================================\n"
        "DADOS BRUTOS DA EXTRACAO DXF:\n"
        "================================================================\n"
        f"{json_cru_str}"
    )

    if contexto_rag:
        partes.append(
            "\n================================================================\n"
            "CONTEXTO (Normas e Relatorios relevantes):\n"
            "================================================================\n"
            f"{contexto_rag}"
        )

    if historico_str:
        partes.append(
            "\n================================================================\n"
            "HISTORICO DA CONVERSA:\n"
            "================================================================\n"
            f"{historico_str}"
        )

    partes.append(
        "\n================================================================\n"
        "PERGUNTA DO USUARIO:\n"
        "================================================================\n"
        f"{pergunta}"
    )

    return "\n".join(partes)


def responder_pergunta_chat(
    pergunta: str,
    json_cru: dict[str, Any],
    json_tratado: dict[str, Any],
    historico: list[dict[str, str]] | None = None,
    reports: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Responde uma pergunta do usuario sobre um projeto processado.

    Cria um RAG temporario in-memory com normas + reports,
    busca semanticamente os chunks mais relevantes,
    e envia o contexto ao LLM.
    """
    # 1. Extrair texto dos reports
    reports_texto = _extrair_textos_reports(reports)

    # 2. Buscar chunks de normas do RAG principal
    normas_docs, normas_metas = _buscar_chunks_normas(pergunta, json_tratado, k=5)

    # 3. Criar RAG temporario (normas + reports)
    rag_temp = _criar_rag_temporario(normas_docs, normas_metas, reports_texto)

    # 4. Buscar no RAG temporario
    contexto_rag, fontes_normas, fontes_reports = _buscar_no_rag_temporario(
        rag_temp, pergunta, k=MAX_RAG_CHUNKS
    )

    # 5. Montar prompt
    user_prompt = _construir_prompt(
        pergunta, json_cru, json_tratado, historico, contexto_rag
    )

    # 6. Chamar OpenRouter
    resposta = chamar_openrouter(
        system_prompt=SYSTEM_PROMPT_CHAT,
        user_prompt=user_prompt,
    )

    # 7. Gerar sugestoes
    sugestoes = _gerar_sugestoes(json_tratado, historico)

    # 8. Montar referencias
    referencias = []
    if fontes_normas:
        referencias.append({"tipo": "norma", "itens": fontes_normas})
    if reports:
        nomes_reports = [r.get("title", "") for r in reports[:5]]
        referencias.append({"tipo": "report", "itens": nomes_reports})

    return {
        "resposta": resposta,
        "sugestoes": sugestoes,
        "referencias": referencias,
    }
