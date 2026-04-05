import ezdxf
import pandas as pd
import math
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize
from tqdm import tqdm
import re
import os
import subprocess
import shutil

# ==============================
# CONFIG
# ==============================

INPUT_FILE = "Base.dxf"  # pode ser .dwg ou .dxf
OUTPUT_EXCEL = "Memorial_COMPLETO.xlsx"
OUTPUT_HTML = "Relatorio_COMPLETO.html"

ODA_PATH = r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe"
TEMP_FOLDER = "temp"
SUPPORTED_VERSIONS = ["ACAD2018", "ACAD2013", "ACAD2010"]

# ==============================
# UTIL
# ==============================

def is_dxf(file):
    return file.lower().endswith(".dxf")

def is_dwg(file):
    return file.lower().endswith(".dwg")

def ensure_dirs():
    os.makedirs(TEMP_FOLDER, exist_ok=True)

def check_oda():
    if not os.path.exists(ODA_PATH):
        raise FileNotFoundError(
            f"❌ ODA não encontrado em:\n{ODA_PATH}"
        )

def clean_temp():
    if os.path.exists(TEMP_FOLDER):
        shutil.rmtree(TEMP_FOLDER, ignore_errors=True)

# ==============================
# CONVERSÃO DWG → DXF
# ==============================

def convert_dwg(file_path):
    print("🔄 Convertendo DWG → DXF...")

    check_oda()
    ensure_dirs()

    input_dir = os.path.join(TEMP_FOLDER, "input")
    output_dir = os.path.join(TEMP_FOLDER, "output")

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    file_name = os.path.basename(file_path)
    temp_file = os.path.join(input_dir, file_name)

    shutil.copy2(file_path, temp_file)

    for version in SUPPORTED_VERSIONS:
        try:
            print(f"⚙️ Tentando versão: {version}")

            subprocess.run([
                ODA_PATH,
                input_dir,
                output_dir,
                version,
                "DXF",
                "0",
                "1"
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            output_file = os.path.join(
                output_dir,
                file_name.replace(".dwg", ".dxf")
            )

            if os.path.exists(output_file):
                print("✅ Conversão concluída!")
                return output_file

        except subprocess.CalledProcessError:
            print(f"⚠️ Falha na versão {version}")

    raise RuntimeError("❌ Falha ao converter DWG")

# ==============================
# ENTRADA INTELIGENTE
# ==============================

def preparar_arquivo(file_path):

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

    if is_dxf(file_path):
        print("📐 DXF detectado")
        return file_path

    elif is_dwg(file_path):
        print("📦 DWG detectado")
        return convert_dwg(file_path)

    else:
        raise ValueError("Formato não suportado")

# ==============================
# CLASSIFICADOR
# ==============================

def classificar(layer, texto=""):
    l = (str(layer) + " " + str(texto)).upper()

    if "ELE" in l or "CIRCUITO" in l:
        return "ELÉTRICO"
    if "HIDRO" in l or "AGUA" in l:
        return "HIDROSSANITÁRIO"
    if "VIGA" in l or "PILAR" in l:
        return "ESTRUTURAL"
    if "PORTA" in l:
        return "PORTA"
    if "JANELA" in l:
        return "JANELA"

    return "ARQUITETÔNICO"

# ==============================
# GEOMETRIA
# ==============================

def linha_para_shape(e):
    try:
        return LineString([(e.dxf.start.x, e.dxf.start.y),
                           (e.dxf.end.x, e.dxf.end.y)])
    except:
        return None

def poly_para_shape(e):
    try:
        pts = [(p[0], p[1]) for p in e.get_points()]
        return LineString(pts)
    except:
        return None

# ==============================
# PARSE ELÉTRICO
# ==============================

def parse_circuito(texto):
    dados = {}
    campos = ["CIRC", "CABO", "CARGA"]

    for c in campos:
        m = re.search(fr"{c}:\s*([^,]+)", texto)
        if m:
            dados[c] = m.group(1)

    return dados

# ==============================
# PREPARAÇÃO DO ARQUIVO
# ==============================

DXF_PATH = preparar_arquivo(INPUT_FILE)

# ==============================
# LEITURA DXF
# ==============================

print("🚀 Lendo DXF...")
doc = ezdxf.readfile(DXF_PATH)
msp = doc.modelspace()

linhas = []
elementos = []
blocos = []
textos = []

# ==============================
# PROCESSAMENTO
# ==============================

for e in tqdm(msp, desc="Processando"):

    layer = e.dxf.layer
    tipo = e.dxftype()

    try:

        if tipo == "LINE":
            shape = linha_para_shape(e)
            if shape:
                linhas.append(shape)
                elementos.append({
                    "Layer": layer,
                    "Disciplina": classificar(layer),
                    "Tipo": "LINE",
                    "Comprimento": shape.length
                })

        elif tipo in ["LWPOLYLINE", "POLYLINE"]:
            shape = poly_para_shape(e)
            if shape:
                linhas.append(shape)
                elementos.append({
                    "Layer": layer,
                    "Disciplina": classificar(layer),
                    "Tipo": "POLYLINE",
                    "Comprimento": shape.length
                })

        elif tipo == "HATCH":
            try:
                for p in e.paths:
                    pts = [(v[0], v[1]) for v in p.vertices]
                    if len(pts) >= 3:
                        poly = Polygon(pts)
                        if poly.is_valid:
                            elementos.append({
                                "Layer": layer,
                                "Disciplina": classificar(layer),
                                "Tipo": "AREA",
                                "Area": poly.area
                            })
            except:
                pass

        elif tipo == "INSERT":
            nome = e.dxf.name
            attrs = ""

            if e.attribs:
                attrs = " ".join([a.dxf.text for a in e.attribs])

            texto = f"{nome} {attrs}"

            blocos.append({
                "Layer": layer,
                "Disciplina": classificar(layer, texto),
                "Bloco": nome,
                "Texto": texto,
                **parse_circuito(texto)
            })

        elif tipo in ["TEXT", "MTEXT"]:
            conteudo = e.dxf.text if tipo == "TEXT" else e.text

            textos.append({
                "Layer": layer,
                "Disciplina": classificar(layer, conteudo),
                "Texto": str(conteudo)
            })

    except Exception as erro:
        print(f"⚠️ Erro em {tipo}: {erro}")

# ==============================
# AMBIENTES
# ==============================

print("🏠 Detectando ambientes...")

try:
    poligonos = list(polygonize(linhas))
except:
    poligonos = []

ambientes = []
for i, p in enumerate(poligonos):
    if p.area > 1:
        ambientes.append({
            "Ambiente": f"Amb_{i+1}",
            "Area": p.area,
            "Perimetro": p.length
        })

# ==============================
# DATAFRAMES
# ==============================

df_elem = pd.DataFrame(elementos)
df_blocos = pd.DataFrame(blocos)
df_textos = pd.DataFrame(textos)
df_amb = pd.DataFrame(ambientes)

if not df_elem.empty:
    resumo = df_elem.groupby(["Layer", "Tipo"]).sum(numeric_only=True).reset_index()
else:
    resumo = pd.DataFrame()

# ==============================
# EXPORTAÇÃO EXCEL
# ==============================

print("📊 Gerando Excel...")

with pd.ExcelWriter(OUTPUT_EXCEL, engine="openpyxl") as writer:

    if not resumo.empty:
        resumo.to_excel(writer, sheet_name="Resumo", index=False)

    if not df_elem.empty:
        df_elem.to_excel(writer, sheet_name="Elementos", index=False)

    if not df_blocos.empty:
        df_blocos.to_excel(writer, sheet_name="Blocos", index=False)

    if not df_textos.empty:
        df_textos.to_excel(writer, sheet_name="Textos", index=False)

    if not df_amb.empty:
        df_amb.to_excel(writer, sheet_name="Ambientes", index=False)

    if (resumo.empty and df_elem.empty and df_blocos.empty 
        and df_textos.empty and df_amb.empty):
        pd.DataFrame({"Aviso": ["Nenhum dado encontrado"]})\
            .to_excel(writer, sheet_name="Aviso", index=False)

print("✅ Excel gerado!")

# ==============================
# HTML
# ==============================

print("🌐 Gerando HTML...")

html = f"""
<html>
<head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body class="container mt-4">

<h2>Resumo</h2>
{resumo.to_html(index=False) if not resumo.empty else "<p>Sem dados</p>"}

<h2>Ambientes</h2>
{df_amb.to_html(index=False) if not df_amb.empty else "<p>Sem ambientes</p>"}

<h2>Blocos</h2>
{df_blocos.head(500).to_html(index=False) if not df_blocos.empty else "<p>Sem blocos</p>"}

</body>
</html>
"""

with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html)

print("🎯 FINALIZADO COM SUCESSO!")

# ==============================
# LIMPEZA FINAL
# ==============================

try:
    clean_temp()
    print("🧹 Temporários removidos")
except:
    pass