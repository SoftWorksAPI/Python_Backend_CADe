"""
Gerador de relatório Markdown a partir do memorial_descritivo JSON.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def gerar_markdown(
    memorial: dict[str, Any],
    dados_extracao: dict[str, Any] | None = None,
    arquivo_original: str = "N/A",
) -> str:
    """
    Gera um relatório completo em Markdown e salva no disco.

    Args:
        memorial: dict do memorial_descretivo (retorno da IA)
        dados_extracao: dict com os dados brutos da extração DXF
        arquivo_original: nome do arquivo DXF original

    Returns:
        Caminho do arquivo .md gerado
    """
    now = datetime.now()
    nome_arquivo = Path(arquivo_original).stem
    nome_saida = f"{nome_arquivo}_memorial_{now.strftime('%Y%m%d_%H%M%S')}.md"
    caminho = OUTPUT_DIR / nome_saida

    dg = memorial.get("dados_gerais", {})
    ambientes = memorial.get("ambientes", [])
    elementos = memorial.get("elementos_estruturais", {})
    instalacoes = memorial.get("instalacoes", {})
    cotas_anotacoes = memorial.get("cotas_anotacoes", {})
    obs = memorial.get("observacoes_tecnicas", [])
    inconsistencias = memorial.get("inconsistencias_detectadas", [])
    confianca = memorial.get("confianca_analise", "N/A")

    # ---------------------------------------------------------------------------
    linhas: list[str] = []

    # Capa
    linhas.append("# MEMORIAL DESCRITIVO")
    linhas.append("")
    linhas.append(f"**Arquivo:** {arquivo_original}")
    linhas.append(f"**Data de geração:** {now.strftime('%d/%m/%Y %H:%M')}")
    linhas.append(f"**Confiança da análise:** {confianca}")
    linhas.append("")
    linhas.append("---")
    linhas.append("")

    # Dados Gerais
    linhas.append("## 1. Dados Gerais")
    linhas.append("")
    linhas.append(f"| Campo | Valor |")
    linhas.append(f"|-------|-------|")
    linhas.append(f"| Nome da Obra | {dg.get('nome_obra', 'N/A')} |")
    linhas.append(f"| Localização | {dg.get('localizacao', 'N/A')} |")
    linhas.append(f"| Tipo de Construção | {dg.get('tipo_construcao', 'N/A')} |")
    linhas.append(f"| Padrão de Acabamento | {dg.get('padrao_acabamento', 'N/A')} |")
    linhas.append("")
    linhas.append(f"**Descrição Geral:** {dg.get('descricao_geral', 'N/A')}")
    linhas.append("")

    # Resumo da Extração
    if dados_extracao:
        total = dados_extracao.get("total_entidades", 0)
        resumo = dados_extracao.get("resumo", [])
        linhas.append("## 2. Resumo da Extração DXF")
        linhas.append("")
        linhas.append(f"**Total de entidades extraídas:** {total}")
        linhas.append("")

        if resumo:
            linhas.append("| Layer | Tipo | Quantidade | Comprimento | Área |")
            linhas.append("|-------|------|-----------|-------------|------|")
            for r in resumo:
                linhas.append(
                    f"| {r['layer']} | {r['tipo']} | {r['quantidade']} | "
                    f"{r.get('total_comprimento', 0):.2f} | {r.get('total_area', 0):.2f} |"
                )
            linhas.append("")

    # Ambientes
    linhas.append("## 3. Ambientes Identificados")
    linhas.append("")
    if ambientes:
        linhas.append("| Nome | Área (m²) | Perímetro (m) | Descrição |")
        linhas.append("|------|-----------|--------------|-----------|")
        for a in ambientes:
            linhas.append(
                f"| {a.get('nome', 'N/A')} | {a.get('area_m2', 0):.2f} | "
                f"{a.get('perimetro_m', 0):.2f} | {a.get('descricao', 'N/A')} |"
            )
        linhas.append("")

        for a in ambientes:
            elems = a.get("elementos_identificados", [])
            obs_a = a.get("observacoes", "")
            if elems or obs_a:
                linhas.append(f"### {a.get('nome', 'N/A')}")
                if elems:
                    linhas.append(f"- **Elementos:** {', '.join(elems)}")
                if obs_a:
                    linhas.append(f"- **Observações:** {obs_a}")
                linhas.append("")
    else:
        linhas.append("*Nenhum ambiente identificado na planta.*")
        linhas.append("")

    # Elementos Estruturais
    linhas.append("## 4. Elementos Estruturais")
    linhas.append("")
    if elementos:
        for chave, valor in elementos.items():
            linhas.append(f"- **{chave.replace('_', ' ').title()}:** {valor}")
        linhas.append("")
    else:
        linhas.append("*Nenhum elemento estrutural identificado.*")
        linhas.append("")

    # Instalações
    linhas.append("## 5. Instalações")
    linhas.append("")
    if instalacoes:
        for chave, valor in instalacoes.items():
            linhas.append(f"- **{chave.replace('_', ' ').title()}:** {valor}")
        linhas.append("")
    else:
        linhas.append("*Nenhuma instalação identificada.*")
        linhas.append("")

    # Cotas e Anotações
    linhas.append("## 6. Cotas e Anotações")
    linhas.append("")
    cotas = cotas_anotacoes.get("cotas_encontradas", [])
    anotacoes = cotas_anotacoes.get("anotacoes_encontradas", [])
    if cotas or anotacoes:
        if cotas:
            linhas.append("### Cotas")
            for c in cotas:
                linhas.append(f"- {c}")
            linhas.append("")
        if anotacoes:
            linhas.append("### Anotações")
            for a in anotacoes:
                linhas.append(f"- {a}")
            linhas.append("")
    else:
        linhas.append("*Nenhuma cota ou anotação encontrada.*")
        linhas.append("")

    # Observações Técnicas
    linhas.append("## 7. Observações Técnicas")
    linhas.append("")
    if obs:
        for i, o in enumerate(obs, 1):
            linhas.append(f"{i}. {o}")
        linhas.append("")
    else:
        linhas.append("*Nenhuma observação técnica.*")
        linhas.append("")

    # Inconsistências
    linhas.append("## 8. Inconsistências Detectadas")
    linhas.append("")
    if inconsistencias:
        linhas.append("> **ATENÇÃO:** As seguintes inconsistências foram identificadas:")
        linhas.append("")
        for i, inc in enumerate(inconsistencias, 1):
            linhas.append(f"{i}. {inc}")
        linhas.append("")
    else:
        linhas.append("*Nenhuma inconsistência detectada.*")
        linhas.append("")

    # Dados brutos da extração (resumo)
    if dados_extracao:
        blocos = dados_extracao.get("blocos", [])
        dimensions = dados_extracao.get("dimensions", [])
        leaders = dados_extracao.get("leaders", [])

        linhas.append("## 9. Dados Complementares da Extração")
        linhas.append("")

        if blocos:
            linhas.append(f"### Blocos/Símbolos ({len(blocos)})")
            for b in blocos[:20]:  # Limitar a 20
                geo = b.get("geometria_interna", [])
                geo_info = f" ({len(geo)} entidades internas)" if geo else ""
                linhas.append(f"- [{b['layer']}] **{b['bloco']}**: {b['texto']}{geo_info}")
            if len(blocos) > 20:
                linhas.append(f"- *... e mais {len(blocos) - 20} blocos*")
            linhas.append("")

        if dimensions:
            linhas.append(f"### Cotas ({len(dimensions)})")
            for d in dimensions[:20]:
                medido = f" (medido: {d['valor_medido']})" if d.get("valor_medido") else ""
                linhas.append(f"- [{d['layer']}] {d['valor_texto']}{medido}")
            if len(dimensions) > 20:
                linhas.append(f"- *... e mais {len(dimensions) - 20} cotas*")
            linhas.append("")

        if leaders:
            linhas.append(f"### Anotações Técnicas ({len(leaders)})")
            for l in leaders[:20]:
                linhas.append(f"- [{l['layer']}] {l['tipo']}: {l['texto']}")
            if len(leaders) > 20:
                linhas.append(f"- *... e mais {len(leaders) - 20} anotações*")
            linhas.append("")

    # Rodapé
    linhas.append("---")
    linhas.append("")
    linhas.append(f"*Relatório gerado automaticamente pelo sistema CADe em {now.strftime('%d/%m/%Y %H:%M')}.*")
    linhas.append(f"*Confiança da análise: {confianca}*")

    # Salvar
    conteudo = "\n".join(linhas)
    caminho.write_text(conteudo, encoding="utf-8")

    return str(caminho)
