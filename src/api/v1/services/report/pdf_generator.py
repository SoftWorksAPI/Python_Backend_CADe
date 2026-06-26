"""
Gerador de PDF profissional do Memorial Descritivo usando reportlab.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers de formatacao
# ---------------------------------------------------------------------------

def _fmt_texto(valor: Any) -> str:
    """Converte qualquer valor para string limpa e escapada para XML/HTML."""
    if valor is None:
        return "Nao informado"
    if isinstance(valor, (list, tuple)):
        partes = [_fmt_texto(v) for v in valor]
        return ", ".join(partes) if partes else "Nenhum"
    if isinstance(valor, dict):
        return str(valor)
    texto = str(valor).strip()
    if not texto or texto.lower() in ("none", "null", "n/a", ""):
        return "Nao informado"
    return html.escape(texto)


def _fmt_numero(valor: Any, casas: int = 2) -> str:
    """Formata numero com casas decimais."""
    if valor is None:
        return "-"
    try:
        return f"{float(valor):,.{casas}f}"
    except (ValueError, TypeError):
        return str(valor)


def _fmt_lista_bullets(itens: list | None, prefixo: str = "") -> list[str]:
    """Formata lista de itens como bullets."""
    if not itens:
        return []
    resultado = []
    for i, item in enumerate(itens, 1):
        texto = _fmt_texto(item)
        if prefixo:
            resultado.append(f"<b>{prefixo}{i}:</b> {texto}")
        else:
            resultado.append(f"&#8226; {texto}")
    return resultado


def _safe_str(valor: Any) -> str:
    """Retorna string segura para Paragraph (escapa XML)."""
    if valor is None:
        return ""
    return html.escape(str(valor))


# ---------------------------------------------------------------------------
# Gerador de PDF
# ---------------------------------------------------------------------------

def gerar_pdf(
    memorial: dict[str, Any],
    dados_extracao: dict[str, Any] | None = None,
    arquivo_original: str = "N/A",
) -> str:
    """
    Gera PDF formatado do Memorial Descritivo.
    Retorna o caminho do arquivo gerado.
    """

    now = datetime.now()
    nome_arquivo = Path(arquivo_original).stem
    nome_saida = f"{nome_arquivo}_memorial_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    caminho = OUTPUT_DIR / nome_saida

    doc = SimpleDocTemplate(
        str(caminho),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    # --- Estilos ---
    styles = getSampleStyleSheet()

    navy = HexColor("#1a3c5e")
    navy_light = HexColor("#2c5f8a")
    cinza = HexColor("#4a6d8c")
    cinza_bg = HexColor("#f4f6f8")
    vermelho = HexColor("#c0392b")
    verde = HexColor("#27ae60")

    titulo_style = ParagraphStyle("Titulo", parent=styles["Title"], fontSize=20, textColor=navy, spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica-Bold")
    subtitulo_style = ParagraphStyle("Subtitulo", parent=styles["Normal"], fontSize=10, textColor=cinza, spaceAfter=8, alignment=TA_CENTER)
    secao_style = ParagraphStyle("Secao", parent=styles["Heading2"], fontSize=13, textColor=navy, spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold")
    subsecao_style = ParagraphStyle("Subsecao", parent=styles["Heading3"], fontSize=11, textColor=navy_light, spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold")
    corpo_style = ParagraphStyle("Corpo", parent=styles["Normal"], fontSize=10, alignment=TA_JUSTIFY, spaceAfter=4, leading=14)
    bullet_style = ParagraphStyle("Bullet", parent=styles["Normal"], fontSize=10, alignment=TA_LEFT, spaceAfter=3, leftIndent=12, leading=13)
    alerta_style = ParagraphStyle("Alerta", parent=styles["Normal"], fontSize=10, textColor=vermelho, spaceAfter=3, leading=13)

    # --- Coletar dados ---
    dg = memorial.get("dados_gerais") or {}
    ambientes = memorial.get("ambientes") or []
    elementos = memorial.get("elementos_estruturais") or {}
    instalacoes = memorial.get("instalacoes") or {}
    cotas_anotacoes = memorial.get("cotas_anotacoes") or {}
    obs = memorial.get("observacoes_tecnicas") or []
    inconsistencias = memorial.get("inconsistencias_detectadas") or []
    confianca = _fmt_texto(memorial.get("confianca_analise"))

    story = []

    # ======== CAPA ========
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph("MEMORIAL DESCRITIVO", titulo_style))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="80%", thickness=2, color=navy))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"Arquivo: {_safe_str(arquivo_original)}", subtitulo_style))
    story.append(Paragraph(f"Gerado em: {now.strftime('%d/%m/%Y as %H:%M')}", subtitulo_style))
    story.append(Paragraph(f"Confianca da analise: <b>{confianca}</b>", subtitulo_style))

    # Dados da obra na capa
    nome_obra = _fmt_texto(dg.get("nome_obra"))
    localizacao = _fmt_texto(dg.get("localizacao"))
    story.append(Spacer(1, 8 * mm))
    capa_dados = [
        ["", ""],
        ["Obra:", nome_obra],
        ["Localizacao:", localizacao],
    ]
    t = Table(capa_dados, colWidths=[3 * cm, 12 * cm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (0, -1), navy),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]))
    story.append(t)

    story.append(Spacer(1, 2 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=cinza))

    # ======== 1. DADOS GERAIS ========
    story.append(Paragraph("1. Dados Gerais da Obra", secao_style))

    tipo = _fmt_texto(dg.get("tipo_construcao"))
    padrao = _fmt_texto(dg.get("padrao_acabamento"))
    descricao = _fmt_texto(dg.get("descricao_geral"))

    dados_tabela = [
        ["Campo", "Informacao"],
        ["Nome da Obra", nome_obra],
        ["Localizacao", localizacao],
        ["Tipo de Construcao", tipo],
        ["Padrao de Acabamento", padrao],
    ]
    t = Table(dados_tabela, colWidths=[5 * cm, 11 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [cinza_bg, HexColor("#ffffff")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"<b>Descricao:</b> {descricao}", corpo_style))

    # ======== 2. RESUMO DA EXTRACAO ========
    if dados_extracao:
        total = dados_extracao.get("total_entidades", 0)
        resumo = dados_extracao.get("resumo") or []

        story.append(Paragraph("2. Resumo da Extracao", secao_style))
        story.append(Paragraph(f"Total de entidades extraidas do arquivo DXF: <b>{total}</b>", corpo_style))

        if resumo:
            story.append(Spacer(1, 2 * mm))
            resumo_tabela = [["Layer", "Tipo", "Qtd", "Comprimento", "Area"]]
            for r in resumo:
                resumo_tabela.append([
                    _safe_str(r.get("layer", "")),
                    _safe_str(r.get("tipo", "")),
                    str(r.get("quantidade", 0)),
                    _fmt_numero(r.get("total_comprimento", 0)),
                    _fmt_numero(r.get("total_area", 0)),
                ])
            t = Table(resumo_tabela, colWidths=[4.5 * cm, 3 * cm, 1.5 * cm, 3.5 * cm, 3.5 * cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [cinza_bg, HexColor("#ffffff")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (2, 1), (2, -1), "CENTER"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ]))
            story.append(t)

    # ======== 3. AMBIENTES ========
    story.append(Paragraph("3. Ambientes Identificados", secao_style))

    if ambientes:
        amb_tabela = [["Nome", "Area (m2)", "Perimetro (m)", "Descricao"]]
        for a in ambientes:
            amb_tabela.append([
                _fmt_texto(a.get("nome")),
                _fmt_numero(a.get("area_m2", 0)),
                _fmt_numero(a.get("perimetro_m", 0)),
                _fmt_texto(a.get("descricao")),
            ])
        t = Table(amb_tabela, colWidths=[3 * cm, 2.5 * cm, 2.5 * cm, 8 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [cinza_bg, HexColor("#ffffff")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (1, 1), (2, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
        story.append(Spacer(1, 3 * mm))

        # Detalhes por ambiente
        for a in ambientes:
            elems = a.get("elementos_identificados") or []
            obs_a = _fmt_texto(a.get("observacoes"))
            nome = _fmt_texto(a.get("nome"))

            if elems or obs_a not in ("Nao informado", ""):
                bloco = []
                bloco.append(Paragraph(f"<b>{nome}</b>", subsecao_style))
                if elems:
                    bloco.append(Paragraph(f"<b>Elementos:</b> {', '.join(_fmt_texto(e) for e in elems)}", bullet_style))
                if obs_a not in ("Nao informado", ""):
                    bloco.append(Paragraph(f"<b>Observacoes:</b> {obs_a}", bullet_style))
                story.append(KeepTogether(bloco))
    else:
        story.append(Paragraph("<i>Nenhum ambiente identificado na planta.</i>", corpo_style))

    # ======== 4. ELEMENTOS ESTRUTURAIS ========
    story.append(Paragraph("4. Elementos Estruturais", secao_style))
    if elementos:
        elem_tabela = [["Elemento", "Descricao"]]
        for chave, valor in elementos.items():
            nome_elem = _safe_str(chave.replace("_", " ").title())
            desc_elem = _fmt_texto(valor)
            elem_tabela.append([nome_elem, desc_elem])
        t = Table(elem_tabela, colWidths=[5 * cm, 11 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [cinza_bg, HexColor("#ffffff")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("<i>Nenhum elemento estrutural identificado.</i>", corpo_style))

    # ======== 5. INSTALACOES ========
    story.append(Paragraph("5. Instalacoes", secao_style))
    if instalacoes:
        inst_tabela = [["Tipo", "Descricao"]]
        for chave, valor in instalacoes.items():
            nome_inst = _safe_str(chave.replace("_", " ").title())
            desc_inst = _fmt_texto(valor)
            inst_tabela.append([nome_inst, desc_inst])
        t = Table(inst_tabela, colWidths=[5 * cm, 11 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [cinza_bg, HexColor("#ffffff")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("<i>Nenhuma instalacao identificada.</i>", corpo_style))

    # ======== 6. COTAS E ANOTACOES ========
    cotas = cotas_anotacoes.get("cotas_encontradas") or []
    anotacoes = cotas_anotacoes.get("anotacoes_encontradas") or []

    if cotas or anotacoes:
        story.append(Paragraph("6. Cotas e Anotacoes Tecnicas", secao_style))

        if cotas:
            story.append(Paragraph("<b>Cotas encontradas:</b>", corpo_style))
            for c in cotas[:20]:
                story.append(Paragraph(f"&#8226; {_fmt_texto(c)}", bullet_style))
            if len(cotas) > 20:
                story.append(Paragraph(f"<i>... e mais {len(cotas) - 20} cotas.</i>", bullet_style))

        if anotacoes:
            story.append(Paragraph("<b>Anotacoes encontradas:</b>", corpo_style))
            for a in anotacoes[:20]:
                story.append(Paragraph(f"&#8226; {_fmt_texto(a)}", bullet_style))
            if len(anotacoes) > 20:
                story.append(Paragraph(f"<i>... e mais {len(anotacoes) - 20} anotacoes.</i>", bullet_style))

    # ======== 7. OBSERVACOES TECNICAS ========
    story.append(Paragraph("7. Observacoes Tecnicas", secao_style))
    if obs:
        for i, o in enumerate(obs, 1):
            story.append(Paragraph(f"<b>{i}.</b> {_fmt_texto(o)}", bullet_style))
    else:
        story.append(Paragraph("<i>Nenhuma observacao tecnica registrada.</i>", corpo_style))

    # ======== 8. INCONSISTENCIAS ========
    story.append(Paragraph("8. Inconsistencias Detectadas", secao_style))
    if inconsistencias:
        story.append(Paragraph("As seguintes inconsistencias foram identificadas pela analise automatizada:", corpo_style))
        story.append(Spacer(1, 2 * mm))
        for i, inc in enumerate(inconsistencias, 1):
            story.append(Paragraph(f"<b>{i}.</b> {_fmt_texto(inc)}", alerta_style))
    else:
        story.append(Paragraph("&#10003; <b>Nenhuma inconsistencia detectada.</b>", ParagraphStyle("Ok", parent=corpo_style, textColor=verde)))

    # ======== RODAPE ========
    story.append(Spacer(1, 1.5 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=navy))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"Documento gerado automaticamente pelo sistema <b>CADe</b> em {now.strftime('%d/%m/%Y as %H:%M')}.",
        ParagraphStyle("Rodape", parent=subtitulo_style, fontSize=8, textColor=cinza),
    ))
    story.append(Paragraph(
        f"Nivel de confianca da analise: <b>{confianca}</b>",
        ParagraphStyle("RodapeConf", parent=subtitulo_style, fontSize=8, textColor=cinza),
    ))

    doc.build(story)
    return str(caminho)


# ---------------------------------------------------------------------------
# Gerador de PDF a partir de texto gerado por IA
# ---------------------------------------------------------------------------

def gerar_pdf_de_texto(
    texto_ia: str,
    arquivo_original: str = "N/A",
) -> str:
    """
    Gera PDF profissional a partir de TEXTO PURO gerado por IA.
    Faz parse simples de titulos em CAIXA ALTA e listas com traco.
    Retorna o caminho do arquivo gerado.
    """

    now = datetime.now()
    nome_arquivo = Path(arquivo_original).stem
    nome_saida = f"{nome_arquivo}_memorial_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    caminho = OUTPUT_DIR / nome_saida

    doc = SimpleDocTemplate(
        str(caminho),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    navy = HexColor("#1a3c5e")
    cinza = HexColor("#4a6d8c")
    navy_light = HexColor("#2c5f8a")

    titulo_style = ParagraphStyle("TituloIA", parent=styles["Title"], fontSize=18, textColor=navy, spaceAfter=6, alignment=TA_CENTER, fontName="Helvetica-Bold")
    secao_style = ParagraphStyle("SecaoIA", parent=styles["Heading2"], fontSize=13, textColor=navy, spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold")
    corpo_style = ParagraphStyle("CorpoIA", parent=styles["Normal"], fontSize=10, alignment=TA_JUSTIFY, spaceAfter=4, leading=14)
    bullet_style = ParagraphStyle("BulletIA", parent=styles["Normal"], fontSize=10, alignment=TA_LEFT, spaceAfter=3, leftIndent=12, leading=13)
    subtitulo_style = ParagraphStyle("SubIA", parent=styles["Normal"], fontSize=10, textColor=cinza, spaceAfter=8, alignment=TA_CENTER)

    story = []

    # Cabecalho
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph("MEMORIAL DESCRITIVO", titulo_style))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="80%", thickness=2, color=navy))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"Arquivo: {_safe_str(arquivo_original)}", subtitulo_style))
    story.append(Paragraph(f"Gerado em: {now.strftime('%d/%m/%Y as %H:%M')}", subtitulo_style))
    story.append(Spacer(1, 1.5 * cm))

    # Parse do texto da IA
    linhas = texto_ia.split('\n')
    for linha in linhas:
        linha_strip = linha.strip()

        if not linha_strip:
            story.append(Spacer(1, 2 * mm))
            continue

        # Titulo: todo em caixa alta com mais de 3 caracteres (ex: "1. DADOS GERAIS")
        if len(linha_strip) > 3 and linha_strip.isupper():
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph(html.escape(linha_strip), secao_style))
            continue

        # Linha de separacao
        if linha_strip.startswith('---') or linha_strip.startswith('==='):
            story.append(HRFlowable(width="100%", thickness=0.5, color=cinza))
            continue

        # Lista com traco
        if linha_strip.startswith('- '):
            item = linha_strip[2:].strip()
            story.append(Paragraph(f"&#8226; {html.escape(item)}", bullet_style))
            continue

        # Paragrafo normal
        story.append(Paragraph(html.escape(linha_strip), corpo_style))

    # Rodape
    story.append(Spacer(1, 1.5 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=navy))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"Documento gerado automaticamente pelo sistema <b>CADe</b> em {now.strftime('%d/%m/%Y as %H:%M')}.",
        ParagraphStyle("RodapeIA", parent=subtitulo_style, fontSize=8, textColor=cinza),
    ))

    doc.build(story)
    return str(caminho)
