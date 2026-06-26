"""
Pipeline de IA para geracao de Memorial Descritivo.

5 nos (etapas):
  1. Extracao deterministica (ezdxf)
  1.5. Busca RAG (ChromaDB)
  2. Analise via LLM (OpenRouter)
  3. Parse e validacao da resposta
  4. Montagem + geracao de relatorios
  5. Revisao do relatorio pela IA
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from src.api.v1.services.ai.client import chamar_openrouter
from src.logger import log
from src.api.v1.services.ai.prompts import (
    SYSTEM_PROMPT_AUDITOR,
    SYSTEM_PROMPT_RELATORIO_MD,
    SYSTEM_PROMPT_RELATORIO_PDF,
    build_relatorio_prompt,
    build_user_prompt,
)
from src.api.v1.schemas.dxf_schemas import DXFExtractRequest, DXFExtractResponse
from src.api.v1.services.extract_dxf_service import extract_dxf_from_upload
from src.api.v1.services.rag.retriever import buscar_normas_relevantes
from src.api.v1.services.structural_analysis import analisar_estrutural
from src.api.v1.services.report.pdf_generator import gerar_pdf_de_texto


# ---------------------------------------------------------------------------
# No 1 - Extracao deterministica
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
# No 1.5 - Construir query RAG
# ---------------------------------------------------------------------------

def _build_rag_query(dados: DXFExtractResponse) -> str:
    """
    Monta uma query de busca inteligente baseada nos dados extraidos do DXF.
    """
    termos: list[str] = []

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

    textos_unicos: list[str] = []
    seen = set()
    for t in dados.textos:
        texto = t.texto.strip()
        if len(texto) > 3 and texto not in seen:
            seen.add(texto)
            textos_unicos.append(texto)
        if len(textos_unicos) >= 10:
            break

    layers_unicos: list[str] = []
    seen_layers: set[str] = set()
    for el in dados.elementos:
        if el.layer not in seen_layers:
            seen_layers.add(el.layer)
            layers_unicos.append(el.layer)
        if len(layers_unicos) >= 5:
            break

    if disciplinas:
        termos.append(" ".join(sorted(disciplinas)))
    if textos_unicos:
        termos.append(" ".join(textos_unicos[:5]))
    if layers_unicos:
        termos.append(" ".join(layers_unicos[:3]))

    query = " ".join(termos).strip()

    if not query or len(query) < 10:
        query = f"normas tecnicas construcao civil {dados.arquivo}"

    return query[:500]


# ---------------------------------------------------------------------------
# No 2 - Analise via LLM
# ---------------------------------------------------------------------------

def _node_llm_analysis(
    dados_extracao: DXFExtractResponse,
    normas_contexto: str = "",
    dados_dict_override: dict[str, Any] | None = None,
) -> str:
    """Envia os dados extraidos ao LLM via OpenRouter."""
    dados_dict = dados_dict_override or dados_extracao.model_dump(mode="json")
    user_prompt = build_user_prompt(dados_dict, normas_contexto)

    return chamar_openrouter(
        system_prompt=SYSTEM_PROMPT_AUDITOR,
        user_prompt=user_prompt,
    )


# ---------------------------------------------------------------------------
# No 3 - Parse e validacao
# ---------------------------------------------------------------------------

def _node_parse_response(raw_text: str) -> dict[str, Any]:
    """Tenta parsear o JSON retornado pelo LLM com fallback."""
    if not raw_text or not raw_text.strip():
        log.error("PARSE", "Resposta vazia do LLM")
        return _build_fallback_memorial("LLM retornou resposta vazia")

    # Tentar 1: JSON puro
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Tentar 2: JSON dentro de bloco de codigo markdown
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Tentar 3: Primeiro objeto JSON encontrado
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Tentar 4: Limpar caracteres problematicos e tentar novamente
    cleaned = raw_text.strip()
    # Remover BOM e caracteres de controle
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned)
    # Tentar extrair JSON apos primeira { ate ultima }
    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(cleaned[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass

    # Tentar 5: JSON truncado - tentar fechar chaves pendentes
    if first_brace != -1:
        fragment = cleaned[first_brace:]
        # Contar chaves abertas vs fechadas
        open_braces = fragment.count('{') - fragment.count('}')
        open_brackets = fragment.count('[') - fragment.count(']')
        # Tentar fechar com chaves/colchetes pendentes
        if open_braces > 0 or open_brackets > 0:
            # Remover ultimo valor incompleto (ate a ultima virgula ou chave)
            last_comma = max(fragment.rfind(','), fragment.rfind(':'))
            if last_comma > len(fragment) - 200:  # So se o corte foi recente
                fragment = fragment[:last_comma]
            # Fechar estruturas pendentes
            fragment += ']' * open_brackets + '}' * open_braces
            try:
                result = json.loads(fragment)
                log.warn("PARSE", "JSON truncado foi recuperado com sucesso")
                return result
            except json.JSONDecodeError:
                pass

    # Fallback: retornar memorial basico com dados da resposta bruta
    log.warn("PARSE", f"Nao foi possivel parsear JSON. Resposta: {raw_text[:200]}...")
    return _build_fallback_memorial(f"Resposta do LLM nao e JSON valido: {raw_text[:500]}")


def _build_fallback_memorial(erro: str) -> dict[str, Any]:
    """Retorna um memorial descritivo basico quando o parse falha."""
    return {
        "dados_gerais": {
            "nome_obra": "Nao identificado",
            "descricao_geral": "Erro ao processar resposta da IA",
        },
        "ambientes": [],
        "elementos_estruturais": {},
        "instalacoes": {},
        "cotas_anotacoes": {},
        "observacoes_tecnicas": ["Erro no processamento da IA"],
        "inconsistencias_detectadas": [erro],
        "confianca_analise": "baixa",
    }


# ---------------------------------------------------------------------------
# No 4 - Geracao de relatorio por IA
# ---------------------------------------------------------------------------

def gerar_relatorio_ia(
    tipo: str,
    dados_extracao: dict[str, Any],
    memorial_descritivo: dict[str, Any],
    normas_contexto: str = "",
) -> str:
    """
    Gera o conteudo de um relatorio (MD ou PDF) usando a IA.

    Args:
        tipo: "md" para Markdown, "pdf" para texto puro (PDF)
        dados_extracao: dados brutos da extracao DXF
        memorial_descritivo: memorial tratado pela IA
        normas_contexto: contexto de normas do RAG

    Returns:
        Conteudo do relatorio gerado pela IA (texto)
    """
    if tipo == "md":
        system_prompt = SYSTEM_PROMPT_RELATORIO_MD
    else:
        system_prompt = SYSTEM_PROMPT_RELATORIO_PDF

    user_prompt = build_relatorio_prompt(
        tipo=tipo,
        dados_extracao=dados_extracao,
        memorial_descritivo=memorial_descritivo,
        normas_contexto=normas_contexto,
    )

    return chamar_openrouter(system_prompt=system_prompt, user_prompt=user_prompt)


def _node_assembly(
    memorial: dict[str, Any],
    dados_extracao: DXFExtractResponse,
    raw_llm_response: str,
    normas_contexto: str = "",
) -> dict[str, Any]:
    """Monta o resultado final e gera relatorios via IA."""
    dados_dict = dados_extracao.model_dump(mode="json")
    arquivo = dados_extracao.arquivo

    relatorio_md = None
    relatorio_pdf = None

    # Gerar Markdown via IA
    try:
        md_content = gerar_relatorio_ia("md", dados_dict, memorial, normas_contexto)
        output_dir = Path(__file__).parent.parent / "report" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_filename = f"{Path(arquivo).stem}_memorial_{ts}.md"
        md_path = output_dir / md_filename
        md_path.write_text(md_content, encoding="utf-8")
        relatorio_md = str(md_path)
    except Exception:
        pass

    # Gerar PDF via IA (texto -> PDF)
    try:
        pdf_content = gerar_relatorio_ia("pdf", dados_dict, memorial, normas_contexto)
        relatorio_pdf = gerar_pdf_de_texto(pdf_content, arquivo)
    except Exception:
        pass

    return {
        "sucesso": True,
        "memorial_descritivo": memorial,
        "dados_extracao": dados_dict,
        "confianca": memorial.get("confianca_analise", "media"),
        "num_inconsistencias": len(
            memorial.get("inconsistencias_detectadas", [])
        ),
        "relatorio_md": relatorio_md,
        "relatorio_pdf": relatorio_pdf,
    }


# ---------------------------------------------------------------------------
# No 5 - Revisao do relatorio pela IA
# ---------------------------------------------------------------------------

def _node_review(
    memorial: dict[str, Any],
    relatorio_md_path: str | None,
) -> dict[str, Any]:
    """
    Envia o relatorio gerado para o LLM revisar.
    Retorna o resultado da revisao.
    """
    if not relatorio_md_path:
        return {"revisado": False, "motivo": "Relatorio MD nao foi gerado."}

    try:
        from pathlib import Path
        conteudo_md = Path(relatorio_md_path).read_text(encoding="utf-8")
    except Exception as e:
        return {"revisado": False, "motivo": f"Erro ao ler relatorio: {e}"}

    # Verificar se ha JSON puro no documento
    json_patterns = [
        r'\{[^{}]*"dados_gerais"[^{}]*\}',
        r'\{[^{}]*"nome_obra"[^{}]*\}',
        r'\[[\s\S]*?\{[\s\S]*?"area_m2"[\s\S]*?\}[\s\S]*?\]',
    ]
    json_encontrado = []
    for pattern in json_patterns:
        matches = re.findall(pattern, conteudo_md)
        json_encontrado.extend(matches)

    if json_encontrado:
        return {
            "revisado": True,
            "status": "PROBLEMAS_ENCONTRADOS",
            "problemas": [f"JSON puro encontrado no documento ({len(json_encontrado)} ocorrencias)"],
            "sugestao": "Regenerar relatorio sem dados JSON crus.",
        }

    # Verificar se secoes obrigatorias existem
    secoes_obrigatorias = [
        "Dados Gerais",
        "Ambientes",
        "Elementos Estruturais",
        "Instalacoes",
        "Observacoes",
        "Inconsistencias",
    ]

    secoes_faltando = []
    for secao in secoes_obrigatorias:
        if secao.lower() not in conteudo_md.lower():
            secoes_faltando.append(secao)

    if secoes_faltando:
        return {
            "revisado": True,
            "status": "PROBLEMAS_ENCONTRADOS",
            "problemas": [f"Secoes faltando: {', '.join(secoes_faltando)}"],
            "sugestao": "Adicionar secoes faltantes ao relatorio.",
        }

    # Verificar se dados do memorial estao presentes
    dados_verificar = []
    dg = memorial.get("dados_gerais", {})
    if dg.get("nome_obra") and dg["nome_obra"] not in conteudo_md:
        dados_verificar.append(f"nome_obra '{dg['nome_obra']}' nao encontrado")
    if dg.get("localizacao") and dg["localizacao"] not in conteudo_md:
        dados_verificar.append(f"localizacao '{dg['localizacao']}' nao encontrada")

    ambientes = memorial.get("ambientes", [])
    for a in ambientes[:3]:
        nome = a.get("nome", "")
        if nome and nome not in conteudo_md:
            dados_verificar.append(f"ambiente '{nome}' nao encontrado")

    if dados_verificar:
        return {
            "revisado": True,
            "status": "DADOS_FALTANDO",
            "problemas": dados_verificar,
            "sugestao": "Verificar se todos os dados do memorial estao no relatorio.",
        }

    return {
        "revisado": True,
        "status": "CORRETO",
        "problemas": [],
        "sugestao": None,
    }


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Pipeline — Apenas analise (extracao + RAG + LLM + parse, sem relatorios)
# ---------------------------------------------------------------------------

def executar_analise_dxf(
    filename: str,
    content: bytes,
    options: DXFExtractRequest,
) -> dict[str, Any]:
    """
    Executa apenas a analise do DXF:
    Extracao -> RAG -> LLM -> Parse
    Retorna os JSONs (bruto + tratado) sem gerar relatórios.
    """
    start_time = time.time()
    log.separator("EXTRACT")
    log.info("EXTRACT", f"Inicio - arquivo: {filename}")

    try:
        # No 1: Extracao deterministica
        log.step("EXTRACT", "1", "Extraindo dados do DXF...")
        dados = _node_extraction(filename, content, options)
        log.success("EXTRACT", f"No 1 - Extracao concluida: {dados.total_entidades} entidades")

        if dados.total_entidades == 0:
            log.error("EXTRACT", "Nenhuma entidade encontrada no arquivo DXF")
            return {
                "sucesso": False,
                "erro": "Nenhuma entidade encontrada no arquivo DXF.",
                "memorial_descritivo": None,
                "dados_extracao": dados.model_dump(mode="json"),
            }

        # No 1.2: Analise Estrutural
        log.step("EXTRACT", "1.2", "Analisando elementos estruturais...")
        analise_estrutural = analisar_estrutural(dados)
        n_estruturais = analise_estrutural["resumo"]["total_elementos_estruturais"]
        vol_concreto = analise_estrutural["resumo"]["volume_total_concreto_m3"]
        log.success("EXTRACT", f"No 1.2 - Estrutural: {n_estruturais} elementos, {vol_concreto} m3 de concreto")

        # Montar dict com dados de extracao + analise estrutural
        dados_dict = dados.model_dump(mode="json")
        dados_dict["analise_estrutural"] = analise_estrutural

        # No 1.5: Buscar normas relevantes no RAG
        normas_contexto = ""
        try:
            query = _build_rag_query(dados)
            log.step("EXTRACT", "1.5", f"Buscando normas no RAG (query: {query[:80]})")
            normas_contexto = buscar_normas_relevantes(query=query, k=5)
            if normas_contexto:
                trechos = normas_contexto.split("\n\n---\n\n")
                log.success("EXTRACT", f"No 1.5 - RAG: {len(trechos)} trechos encontrados:")
                for i, trecho in enumerate(trechos, 1):
                    primeira_linha = trecho.split("\n")[0][:120]
                    log.info("EXTRACT", f"No 1.5 - RAG   [{i}] {primeira_linha}")
            else:
                log.warn("EXTRACT", "No 1.5 - RAG: nenhuma norma encontrada")
        except Exception as rag_err:
            log.warn("EXTRACT", f"No 1.5 - RAG indisponivel: {rag_err}")

        # No 2: Analise via LLM
        log.step("EXTRACT", "2", "Enviando para LLM (OpenRouter)...")
        raw_response = _node_llm_analysis(dados, normas_contexto, dados_dict_override=dados_dict)
        log.success("EXTRACT", f"No 2 - LLM analise concluida ({len(raw_response)} chars)")

        # No 3: Parse da resposta
        log.step("EXTRACT", "3", "Parseando resposta JSON...")
        memorial = _node_parse_response(raw_response)
        log.success("EXTRACT", f"No 3 - Parse concluido: confianca={memorial.get('confianca_analise', 'N/A')}")

        elapsed = time.time() - start_time
        log.success("EXTRACT", f"Concluido com sucesso em {elapsed:.1f}s")

        return {
            "sucesso": True,
            "memorial_descritivo": memorial,
            "dados_extracao": dados_dict,
            "confianca": memorial.get("confianca_analise", "media"),
            "num_inconsistencias": len(memorial.get("inconsistencias_detectadas", [])),
        }

    except Exception as e:
        elapsed = time.time() - start_time
        log.error("EXTRACT", f"Falha apos {elapsed:.1f}s: {str(e)}")
        return {
            "sucesso": False,
            "erro": str(e),
            "memorial_descritivo": None,
            "dados_extracao": None,
        }


# ---------------------------------------------------------------------------
# Pipeline completo (analise + relatorios + revisao) — LEGADO
# ---------------------------------------------------------------------------

def executar_pipeline_memorial(
    filename: str,
    content: bytes,
    options: DXFExtractRequest,
) -> dict[str, Any]:
    """
    Executa o pipeline completo:
    Extracao -> RAG -> LLM -> Parse -> Montagem -> Revisao
    """
    start_time = time.time()
    log.separator("PIPELINE")
    log.info("PIPELINE", f"Inicio - arquivo: {filename}")

    try:

        # No 1: Extracao deterministica
        log.step("PIPELINE", "1", "Extraindo dados do DXF...")
        dados = _node_extraction(filename, content, options)
        log.success("PIPELINE", f"No 1 - Extracao concluida: {dados.total_entidades} entidades")

        if dados.total_entidades == 0:
            return {
                "sucesso": False,
                "erro": "Nenhuma entidade encontrada no arquivo DXF.",
                "memorial_descritivo": None,
                "dados_extracao": dados.model_dump(mode="json"),
            }

        # No 1.2: Analise Estrutural
        log.step("PIPELINE", "1.2", "Analisando elementos estruturais...")
        analise_estrutural = analisar_estrutural(dados)
        n_estruturais = analise_estrutural["resumo"]["total_elementos_estruturais"]
        vol_concreto = analise_estrutural["resumo"]["volume_total_concreto_m3"]
        log.success("PIPELINE", f"No 1.2 - Estrutural: {n_estruturais} elementos, {vol_concreto} m3 de concreto")

        # Montar dict com dados de extracao + analise estrutural
        dados_dict = dados.model_dump(mode="json")
        dados_dict["analise_estrutural"] = analise_estrutural

        # No 1.5: Buscar normas relevantes no RAG
        normas_contexto = ""
        try:
            query = _build_rag_query(dados)
            log.step("PIPELINE", "1.5", f"Buscando normas no RAG (query: {query[:80]}...)")
            normas_contexto = buscar_normas_relevantes(query=query, k=5)
            log.success("PIPELINE", f"No 1.5 - RAG: {len(normas_contexto)} chars de normas encontradas")
        except Exception as rag_err:
            log.warn("PIPELINE", f"No 1.5 - RAG indisponivel: {rag_err}")

        # No 2: Analise via LLM
        log.step("PIPELINE", "2", "Enviando para LLM (OpenRouter)...")
        raw_response = _node_llm_analysis(dados, normas_contexto, dados_dict_override=dados_dict)
        log.success("PIPELINE", f"No 2 - LLM analise concluida ({len(raw_response)} chars)")

        # No 3: Parse da resposta
        log.step("PIPELINE", "3", "Parseando resposta JSON...")
        memorial = _node_parse_response(raw_response)
        log.success("PIPELINE", f"No 3 - Parse concluido: confianca={memorial.get('confianca_analise', 'N/A')}")

        # No 4: Montagem + relatorios (via IA)
        log.step("PIPELINE", "4", "Gerando relatorios MD e PDF via IA...")
        resultado = _node_assembly(memorial, dados, raw_response, normas_contexto)
        log.success("PIPELINE", f"No 4 - MD gerado: {resultado.get('relatorio_md', 'falhou')}")
        log.success("PIPELINE", f"No 4 - PDF gerado: {resultado.get('relatorio_pdf', 'falhou')}")

        # No 5: Revisao do relatorio (max 3 tentativas)
        MAX_TENTATIVAS = 3
        revisao = None
        dados_dict = resultado.get("dados_extracao", {})
        # Incluir analise estrutural no dict final
        dados_dict["analise_estrutural"] = analise_estrutural

        for tentativa in range(MAX_TENTATIVAS):
            log.step("PIPELINE", "5", f"Revisao tentativa {tentativa + 1}/{MAX_TENTATIVAS}...")
            revisao = _node_review(memorial, resultado.get("relatorio_md"))
            log.info("PIPELINE", f"No 5 - Revisao: {revisao.get('status', 'N/A')}")

            if revisao.get("status") == "CORRETO":
                break

            # Se nao eh a ultima tentativa, regenerar
            if tentativa < MAX_TENTATIVAS - 1:
                try:
                    # Deletar arquivos antigos antes de regenerar
                    antigo_md = resultado.get("relatorio_md")
                    antigo_pdf = resultado.get("relatorio_pdf")
                    if antigo_md:
                        Path(antigo_md).unlink(missing_ok=True)
                    if antigo_pdf:
                        Path(antigo_pdf).unlink(missing_ok=True)
                except Exception:
                    pass

                try:
                    resultado = _node_assembly(memorial, dados, raw_response, normas_contexto)
                except Exception:
                    break
            else:
                # Ultima tentativa — marcar como parcial
                revisao["status"] = "PARCIAL"

        revisao["tentativas"] = tentativa + 1
        resultado["revisao"] = revisao
        resultado["analise_estrutural"] = analise_estrutural

        elapsed = time.time() - start_time
        log.success("PIPELINE", f"Concluido com sucesso em {elapsed:.1f}s")
        return resultado

    except Exception as e:
        elapsed = time.time() - start_time
        log.error("PIPELINE", f"Falha apos {elapsed:.1f}s: {str(e)}")
        return {
            "sucesso": False,
            "erro": str(e),
            "memorial_descritivo": None,
            "dados_extracao": None,
        }
