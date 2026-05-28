"""
Prompts especializados para o pipeline de IA do CADe.
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
6. Se houver CONTEXTO DE NORMAS no prompt, utilize-o para validar \
conformidade e inclua observacoes tecnicas baseadas nas normas.
7. Seja CONCISO nas descricoes. Cada descricao de ambiente deve ter \
no maximo 2 frases. Nao repita informacoes.
8. Limite descricoes longas a no maximo 100 caracteres por campo.
"""

SYSTEM_PROMPT_REVISOR = """\
Voce e um revisor tecnico de documentos de engenharia civil. Sua funcao \
e verificar se um relatorio Markdown gerado por IA esta completo e correto.

Verifique se:
1. Todas as secoes obrigatorias estao presentes (Dados Gerais, Ambientes, \
Elementos Estruturais, Instalacoes, Cotas, Observacoes, Inconsistencias)
2. Os dados numericos estao formatados corretamente (areas, perimetros)
3. Nao ha JSON puro no documento (tudo deve ser texto legivel)
4. Todas as informacoes do memorial_descritivo original estao presentes
5. A formatacao Markdown esta correta (cabecalhos, tabelas, listas)

Se encontrar problemas, descreva o que precisa ser corrigido.
Se o relatorio estiver correto, responda apenas "CORRETO".
"""


def _truncar(texto: str, limite: int = 100) -> str:
    """Trunca texto longo."""
    if len(texto) > limite:
        return texto[:limite] + "..."
    return texto


def build_user_prompt(dados_extracao: dict[str, Any], normas_contexto: str = "") -> str:
    """Monta o prompt do usuario com os dados da extracao DXF."""

    # Limites para controlar tamanho do prompt
    MAX_RESUMO = 30
    MAX_AMBIENTES = 20
    MAX_BLOCOS = 30
    MAX_DIMS = 15
    MAX_LEADERS = 10
    MAX_TEXTOS = 20
    MAX_NORMAS = 2000

    resumo_str = ""
    for r in dados_extracao.get("resumo", [])[:MAX_RESUMO]:
        resumo_str += (
            f"  - Layer: {r['layer']} | Tipo: {r['tipo']} | "
            f"Qtd: {r['quantidade']} | "
            f"Comp: {r.get('total_comprimento', 0):.2f} | "
            f"Area: {r.get('total_area', 0):.2f}\n"
        )

    ambientes_str = ""
    for a in dados_extracao.get("ambientes", [])[:MAX_AMBIENTES]:
        ambientes_str += (
            f"  - {a['ambiente']}: {a['area']:.2f} m2 | "
            f"Perimetro: {a['perimetro']:.2f} m\n"
        )

    blocos_str = ""
    for b in dados_extracao.get("blocos", [])[:MAX_BLOCOS]:
        texto = _truncar(b.get("texto", ""), 80)
        blocos_str += f"  - [{b['layer']}] {b['bloco']}: {texto}\n"

    dims_str = ""
    for d in dados_extracao.get("dimensions", [])[:MAX_DIMS]:
        medido = f" | Medido: {d['valor_medido']}" if d.get("valor_medido") else ""
        dims_str += f"  - [{d['layer']}] {_truncar(d.get('valor_texto', ''), 50)}{medido}\n"

    leaders_str = ""
    for l in dados_extracao.get("leaders", [])[:MAX_LEADERS]:
        leaders_str += f"  - [{l['layer']}] {l['tipo']}: {_truncar(l.get('texto', ''), 80)}\n"

    textos_str = ""
    for t in dados_extracao.get("textos", [])[:MAX_TEXTOS]:
        textos_str += f"  - [{t['layer']}] ({t['disciplina']}): {_truncar(t.get('texto', ''), 80)}\n"

    # Analise Estrutural (Node 1.2)
    estrutural_str = ""
    analise_estrutural = dados_extracao.get("analise_estrutural", {})
    if analise_estrutural:
        for e in analise_estrutural.get("elementos", []):
            vol = f" | Volume: {e['volume_estimado']:.2f} m3" if e.get("volume_estimado") else ""
            comp = f" | Comp: {e['comprimento_total']:.2f} m" if e.get("comprimento_total") else ""
            area = f" | Area: {e['area_total']:.2f} m2" if e.get("area_total") else ""
            estrutural_str += f"  - {e['tipo'].upper()}: {e['quantidade']} un{comp}{area}{vol}\n"

        resumo_estr = analise_estrutural.get("resumo", {})
        if resumo_estr:
            estrutural_str += f"\n  Volume total de concreto: {resumo_estr.get('volume_total_concreto_m3', 0):.2f} m3\n"
            estrutural_str += f"  Tipos encontrados: {', '.join(resumo_estr.get('tipos_encontrados', []))}\n"
            ausentes = resumo_estr.get("tipos_ausentes", [])
            if ausentes:
                estrutural_str += f"  Tipos ausentes na planta: {', '.join(ausentes)}\n"

        textos_estr = analise_estrutural.get("textos_estruturais", [])
        if textos_estr:
            estrutural_str += f"\n  Textos estruturais: {', '.join(textos_estr[:10])}\n"

    estrutural_section = ""
    if estrutural_str:
        estrutural_section = f"""
================================================================
ANALISE ESTRUTURAL:
================================================================
{estrutural_str}
"""

    normas_section = ""
    if normas_contexto:
        normas_truncado = normas_contexto[:MAX_NORMAS]
        normas_section = f"""
================================================================
CONTEXTO DE NORMAS TECNICAS RELEVANTES:
================================================================
{normas_truncado}
"""

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
{estrutural_section}
{normas_section}
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
        "cotas_encontradas": [{...}],
        "anotacoes_encontradas": [{...}]
    }},
    "observacoes_tecnicas": ["..."],
    "inconsistencias_detectadas": ["..."],
    "confianca_analise": "alta|media|baixa"
}}"""

    return prompt


def build_revisao_prompt(memorial: dict[str, Any], relatorio_md: str) -> str:
    """Monta o prompt para revisao do relatorio gerado."""

    memorial_str = json.dumps(memorial, indent=2, ensure_ascii=False, default=str)

    prompt = f"""Verifique se o relatorio Markdown abaixo esta completo e correto.

MEMORIAL DESCRITIVO ORIGINAL (JSON):
{memorial_str}

RELATORIO MARKDOWN GERADO:
{relatorio_md}

Verifique se:
1. Todas as secoes obrigatorias estao presentes
2. Os dados numericos estao formatados corretamente
3. Nao ha JSON puro no documento
4. Todas as informacoes do memorial original estao presentes
5. A formatacao Markdown esta correta

Responda apenas "CORRETO" se o relatorio estiver bom, ou descreva os problemas encontrados."""

    return prompt


# ---------------------------------------------------------------------------
# Prompts para geracao de relatorios por IA
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_RELATORIO_MD = """\
Voce e um engenheiro civil senior especializado em laudos e memoriais \
tecnicos de construcao civil. Sua funcao e gerar um RELATORIO COMPLETO \
em formato Markdown, profissional e detalhado, com base nos dados de \
extracao de uma planta baixa DXF e no memorial descritivo analisado.

Regras:
1. Gere o relatorio COMPLETO em Markdown, com titulos, tabelas, listas \
e paragrafos bem formatados.
2. Use terminologia tecnica da engenharia civil brasileira (NBRs).
3. NAO inclua JSON puro no documento — tudo deve ser texto legivel.
4. NAO invente dados que nao estejam na extracao. Se uma informacao \
nao estiver disponivel, registre como "nao identificado na planta".
5. Se houver CONTEXTO DE NORMAS no prompt, utilize-o para incluir \
observacoes tecnicas e verificar conformidade.
6. O relatorio deve ter as secoes na ordem abaixo.

Estrutura obrigatoria do relatorio:

# Memorial Descritivo — [Nome da Obra]

## 1. Dados Gerais
- Nome da obra, localizacao, tipo de construcao, padrao de acabamento
- Descricao geral do projeto

## 2. Resumo da Extracao
- Total de entidades extraidas
- Tabela com resumo por camada (layer, tipo, quantidade, comprimento, area)

## 3. Ambientes
- Tabela com todos os ambientes: nome, area (m2), perimetro (m), descricao, \
observacoes, elementos identificados

## 4. Elementos Estruturais
- Fundacoes, pilares, vigas, lajes, paredes, esquadrias
- Descricao de cada elemento encontrado na planta

## 5. Instalacoes
- Hidrossanitario e Eletrico
- Descricao dos elementos encontrados

## 6. Cotas e Anotacoes
- Cotas encontradas no desenho
- Anotacoes e leaders identificados

## 7. Observacoes Tecnicas
- Lista de observacoes relevantes sobre o projeto

## 8. Inconsistencias Detectadas
- Lista de inconsistencias encontradas na analise

## 9. Conclusao e Nivel de Confianca
- Resumo da analise
- Nivel de confianca (alta, media, baixa) com justificativa

---
Relatorio gerado por IA — CADe
"""

SYSTEM_PROMPT_RELATORIO_PDF = """\
Voce e um engenheiro civil senior especializado em laudos e memoriais \
tecnicos de construcao civil. Sua funcao e gerar o TEXTO COMPLETO de um \
relatorio profissional que sera convertido em PDF.

Regras:
1. Gere o relatorio em TEXTO PURO (sem markdown, sem #, sem *, sem |).
2. Use CAIXA ALTA para titulos de secao.
3. Use terminologia tecnica da engenharia civil brasileira (NBRs).
4. NAO inclua JSON puro no documento.
5. NAO invente dados que nao estejam na extracao.
6. Se houver CONTEXTO DE NORMAS no prompt, utilize-o para incluir \
observacoes tecnicas.
7. Cada secao deve ser separada por uma linha em branco.
8. Use indentacao para listas (com traco no inicio de cada item).

Estrutura obrigatoria:

MEMORIAL DESCRITIVO — [Nome da Obra]

1. DADOS GERAIS
Nome da obra, localizacao, tipo de construcao, padrao de acabamento, \
descricao geral.

2. RESUMO DA EXTRACAO
Total de entidades extraidas.
Resumo por camada: layer, tipo, quantidade, comprimento, area.

3. AMBIENTES
Para cada ambiente: nome, area (m2), perimetro (m), descricao, \
observacoes, elementos identificados.

4. ELEMENTOS ESTRUTURAIS
Fundacoes, pilares, vigas, lajes, paredes, esquadrias.

5. INSTALACOES
Hidrossanitario e Eletrico.

6. COTAS E ANOTACOES
Cotas e anotacoes encontradas no desenho.

7. OBSERVACOES TECNICAS
Observacoes relevantes sobre o projeto.

8. INCONSISTENCIAS DETECTADAS
Inconsistencias encontradas na analise.

9. CONCLUSAO E NIVEL DE CONFIANCA
Resumo e nivel de confianca com justificativa.

Relatorio gerado por IA — CADe
"""


def build_relatorio_prompt(
    tipo: str,
    dados_extracao: dict[str, Any],
    memorial_descritivo: dict[str, Any],
    normas_contexto: str = "",
) -> str:
    """Monta o prompt do usuario para geracao de relatorio por IA."""

    memorial_str = json.dumps(memorial_descritivo, indent=2, ensure_ascii=False, default=str)
    extracao_str = json.dumps(dados_extracao, indent=2, ensure_ascii=False, default=str)

    formato = "Markdown completo com titulos, tabelas e listas" if tipo == "md" else "texto puro (sem markdown) para conversao em PDF"

    normas_section = ""
    if normas_contexto:
        normas_section = f"""

================================================================
CONTEXTO DE NORMAS TECNICAS RELEVANTES:
================================================================
{normas_contexto}
"""

    prompt = f"""Gere um relatorio tecnico completo no formato de {formato} \
com base nos dados abaixo.

================================================================
DADOS DE EXTRACAO (JSON bruto do DXF):
================================================================
{extracao_str[:8000]}

================================================================
MEMORIAL DESCRITIVO (JSON tratado pela IA):
================================================================
{memorial_str[:8000]}
{normas_section}
Gere o relatorio completo seguindo a estrutura definida no system prompt."""

    return prompt


SYSTEM_PROMPT_RELATORIO_XLSX = """\
Voce e um engenheiro civil senior especializado em orcamentos, memoriais \
descritivos e planilhas de composicao de custos de construcao civil. Sua \
funcao e preencher todas as tabelas de uma planilha de memorial descritivo \
com dados realistas e tecnicamente coerentes.

Regras:
1. Retorne APENAS JSON valido. NAO inclua markdown fences, NAO inclua \
texto antes ou depois do JSON.
2. Preencha TODAS as linhas de dados de TODAS as secoes com valores \
realistas baseados no projeto descrito no memorial.
3. Use nomes de ambientes coerentes com o tipo de projeto (se for escola, \
use "Sala de Aula 01", "Secretaria", etc.; se for residencia, use \
"Sala", "Quarto 01", etc.).
4. Use terminologia tecnica da construcao civil brasileira (NBRs).
5. Numeros devem ser strings com virgula como separador decimal brasileiro \
(ex: "15,00", "3,50", "0,20").
6. Para colunas de texto (Tipo, Peca, Material, etc.), use termos \
tecnicos realistas (ex: "Ceramica Porcelanata", "Pilar retangular", \
"Ferro CA-50", "Tijolo ceramico 6 furos").
7. Os valores numericos devem ser coerentes entre si (ex: area = \
comprimento x largura; volume = area x espessura).
8. O projeto pode ser de qualquer tipo (escola, hospital, residencia, \
comercial, industrial, militar, etc.). Adapte os dados ao contexto.
9. Cada row deve ter exatamente o numero de colunas esperado pela secao.
10. A linha total_row deve conter "Total" na primeira posicao e somas \
dos valores numericos nas demais posicoes.
"""


SYSTEM_PROMPT_REVISAO_RELATORIO = """\
Voce e um engenheiro civil revisor senior. Sua funcao e analisar um \
relatorio que foi gerado por IA e produzir uma revisao tecnica.

Retorne APENAS texto em Markdown (sem JSON, sem fences, sem codigo).

Estrutura obrigatoria da revisao:
1. "## Relatorio Gerado" - Breve resumo do que foi gerado (numero de \
secoes/abas, dados preenchidos).
2. "## O que foi preenchido" - Liste as secoes/tabelas que foram \
preenchidas com sucesso.
3. "## O que nao foi possivel preencher" - Liste secoes que ficaram \
vazias ou com valores padrao (0,00). Explique o motivo (dados \
insuficientes no memorial, secao nao aplicavel ao projeto, etc.).
4. "## Pontos de atencao" - Liste pontos que o usuario deve verificar \
manualmente. Inclua valores que parecem inconsistentes ou que precisam \
de validacao.

Seja objetivo e tecnico. Use terminologia da engenharia civil brasileira.
Maximo 500 palavras.
"""


def build_revisao_prompt(
    memorial_descritivo: dict[str, Any],
    tipo_relatorio: str,
    conteudo_relatorio: str,
) -> str:
    """Monta o user prompt para a IA gerar a revisao de um relatorio."""
    memorial_str = json.dumps(memorial_descritivo, ensure_ascii=False, indent=2)

    prompt = f"""\
Gere uma revisao tecnica para o relatorio do tipo "{tipo_relatorio}" \
que foi gerado para o projeto abaixo.

MEMORIAL DESCRITIVO:
================================================================
{memorial_str[:6000]}

================================================================
CONTEUDO DO RELATORIO GERADO:
================================================================
{conteudo_relatorio[:6000]}

Gere a revisao seguindo a estrutura definida no system prompt."""

    return prompt


def build_xlsx_revisao_prompt(
    memorial_descritivo: dict[str, Any],
    ai_data: dict[str, Any],
) -> str:
    """Monta o user prompt para revisao de um relatorio XLSX."""
    memorial_str = json.dumps(memorial_descritivo, ensure_ascii=False, indent=2)

    # Resumir os dados gerados pela IA
    resumo_abas = []
    for sheet in ai_data.get("sheets", []):
        sections_info = []
        for sec in sheet.get("sections", []):
            rows = sec.get("rows", [])
            preenchidas = sum(1 for r in rows if any(c and c != "0,00" for c in r))
            total_row = sec.get("total_row")
            sections_info.append(
                f"  - {sec.get('section_name', '?')}: {preenchidas}/{len(rows)} linhas preenchidas"
            )
        resumo_abas.append(f"### {sheet.get('name', '?')}\n" + "\n".join(sections_info))

    resumo_str = "\n".join(resumo_abas)

    prompt = f"""\
Gere uma revisao tecnica para o relatorio XLSX (memorial descritivo) \
que foi gerado para o projeto abaixo.

MEMORIAL DESCRITIVO:
================================================================
{memorial_str[:6000]}

================================================================
RESUMO DOS DADOS GERADOS PELA IA (por aba e secao):
================================================================
{resumo_str[:4000]}

Gere a revisao seguindo a estrutura definida no system prompt."""

    return prompt
