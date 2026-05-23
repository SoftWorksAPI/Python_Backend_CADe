"""
Prompts especializados para o pipeline de IA do CADe.

O agente atua como um engenheiro civil auditor, cruzando os dados
extraidos do DXF para produzir um Memorial Descritivo estruturado.
"""
from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT_AUDITOR = """\
Voce e um engenheiro civil senior especializado em laudos e memoriais \
tecnicos de construcao civil. Sua funcao e atuar como AUDITOR: receber \
dados brutos extraidos de uma planta baixa em formato DXF (AutoCAD) e \
produzir um Memorial Descritivo completo, tecnico e formatado.

Regras:
1. Analise TODOS os dados fornecidos: ambientes, camadas (layers), \
entidades geometricas, textos de legenda, cotas (dimensions) e \
anotacoes (leaders).
2. IDENTIFIQUE inconsistencias (ex: ambiente sem nome, parede sem \
porta de acesso, comodo com area incompativel, elementos estruturais \
ausentes).
3. NAO invente dados que nao estejam na extracao. Se uma informacao \
nao estiver disponivel, registre como "nao identificado na planta".
4. Retorne APENAS um JSON valido, sem markdown, sem blocos de codigo, \
sem texto extra antes ou depois do JSON.
5. Utilize terminologia tecnica da engenharia civil brasileira (NBRs).
"""


def build_user_prompt(dados_extracao: dict[str, Any]) -> str:
    """
    Monta o prompt do usuario com os dados da extracao DXF.

    Args:
        dados_extracao: dict serializado do DXFExtractResponse

    Returns:
        String formatada com os dados para o LLM
    """

    # Resumo por camada
    resumo_str = ""
    for r in dados_extracao.get("resumo", []):
        resumo_str += (
            f"  - Layer: {r['layer']} | Tipo: {r['tipo']} | "
            f"Qtd: {r['quantidade']} | "
            f"Comp: {r.get('total_comprimento', 0):.2f} | "
            f"Area: {r.get('total_area', 0):.2f}\n"
        )

    # Ambientes
    ambientes_str = ""
    for a in dados_extracao.get("ambientes", []):
        ambientes_str += (
            f"  - {a['ambiente']}: {a['area']:.2f} m2 | "
            f"Perimetro: {a['perimetro']:.2f} m\n"
        )

    # Blocos
    blocos_str = ""
    for b in dados_extracao.get("blocos", []):
        geo = b.get("geometria_interna", [])
        geo_info = f" | {len(geo)} entidades internas" if geo else ""
        blocos_str += (
            f"  - [{b['layer']}] {b['bloco']}: "
            f"{b['texto']}{geo_info}\n"
        )

    # Dimensions
    dims_str = ""
    for d in dados_extracao.get("dimensions", []):
        medido = f" | Medido: {d['valor_medido']}" if d.get("valor_medido") else ""
        dims_str += (
            f"  - [{d['layer']}] {d['valor_texto']}{medido}\n"
        )

    # Leaders
    leaders_str = ""
    for l in dados_extracao.get("leaders", []):
        leaders_str += f"  - [{l['layer']}] {l['tipo']}: {l['texto']}\n"

    # Textos
    textos_str = ""
    for t in dados_extracao.get("textos", []):
        textos_str += f"  - [{t['layer']}] ({t['disciplina']}): {t['texto']}\n"

    prompt = f"""Com base nos dados extraidos da planta baixa DXF abaixo, \
gere o Memorial Descritivo completo da obra.

================================================================
METADADOS:
================================================================
Arquivo: {dados_extracao.get('arquivo', 'N/A')}
Total de entidades: {dados_extracao.get('total_entidades', 0)}

================================================================
RESUMO POR CAMADA:
================================================================
{resumo_str if resumo_str else '  Nenhum resumo disponivel.'}

================================================================
AMBIENTES IDENTIFICADOS:
================================================================
{ambientes_str if ambientes_str else '  Nenhum ambiente identificado.'}

================================================================
BLOCOS/SIMBOLOS:
================================================================
{blocos_str if blocos_str else '  Nenhum bloco encontrado.'}

================================================================
COTAS (DIMENSIONS):
================================================================
{dims_str if dims_str else '  Nenhuma cota encontrada.'}

================================================================
ANOTACOES (LEADERS):
================================================================
{leaders_str if leaders_str else '  Nenhuma anotacao encontrada.'}

================================================================
TEXTOS DO DESENHO:
================================================================
{textos_str if textos_str else '  Nenhum texto encontrado.'}

Gere o Memorial Descritivo no formato JSON abaixo:
{{
    "dados_gerais": {{
        "nome_obra": "...",
        "localizacao": "...",
        "tipo_construcao": "...",
        "padrao_acabamento": "...",
        "descricao_geral": "..."
    }},
    "ambientes": [{{
        "nome": "...",
        "area_m2": 0.0,
        "perimetro_m": 0.0,
        "descricao": "...",
        "elementos_identificados": ["..."],
        "observacoes": "..."
    }}],
    "elementos_estruturais": {{
        "fundacoes": "...",
        "pilares": "...",
        "vigas": "...",
        "lajes": "...",
        "paredes": "...",
        "esquadrias": "..."
    }},
    "instalacoes": {{
        "hidrossanitario": "...",
        "eletrica": "..."
    }},
    "cotas_anotacoes": {{
        "cotas_encontradas": [...],
        "anotacoes_encontradas": [...]
    }},
    "observacoes_tecnicas": ["..."],
    "inconsistencias_detectadas": ["..."],
    "confianca_analise": "alta|media|baixa"
}}"""

    return prompt
