import os
import json
import subprocess
import ezdxf
from shapely.geometry import LineString, Polygon, Point
from math import isclose
from math import hypot

# ==============================
# CONFIG
# ==============================

ODA_PATH = r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe"
TEMP_FOLDER = "temp"

# ==============================
# UTIL
# ==============================

def is_dxf(file):
    return file.lower().endswith(".dxf")

def is_dwg(file):
    return file.lower().endswith(".dwg")

def ensure_dirs():
    os.makedirs(TEMP_FOLDER, exist_ok=True)

# ==============================
# CONVERSÃO
# ==============================

def convert_dwg(file_path):
    ensure_dirs()

    input_dir = os.path.join(TEMP_FOLDER, "input")
    output_dir = os.path.join(TEMP_FOLDER, "output")

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    file_name = os.path.basename(file_path)
    temp_file = os.path.join(input_dir, file_name)

    with open(file_path, "rb") as f_src:
        with open(temp_file, "wb") as f_dst:
            f_dst.write(f_src.read())

    subprocess.run([
        ODA_PATH,
        input_dir,
        output_dir,
        "ACAD2018",
        "DXF",
        "0",
        "1"
    ], check=True)

    return os.path.join(output_dir, file_name.replace(".dwg", ".dxf"))

# ==============================
# EXTRAÇÃO
# ==============================

def extract_entities(msp):
    linhas = []
    poligonos = []
    textos = []
    blocos = []

    for e in msp:
        if e.dxftype() == "LINE":
            start = tuple(e.dxf.start)
            end = tuple(e.dxf.end)

            linhas.append({
                "geom": LineString([start, end])
            })

        elif e.dxftype() == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 3 and e.closed:
                poligonos.append(Polygon(pts))

        elif e.dxftype() in ["TEXT", "MTEXT"]:
            try:
                txt = e.text if e.dxftype() == "TEXT" else e.plain_text()
                textos.append({
                    "texto": txt.lower(),
                    "ponto": Point(e.dxf.insert)
                })
            except:
                pass

        elif e.dxftype() == "INSERT":
            blocos.append({
                "nome": e.dxf.name.lower(),
                "posicao": tuple(e.dxf.insert),
                "escala": (
                    e.dxf.xscale if hasattr(e.dxf, "xscale") else 1,
                    e.dxf.yscale if hasattr(e.dxf, "yscale") else 1
                )
            })

    return linhas, poligonos, textos, blocos

# ==============================
# PAREDES
# ==============================

def is_parallel(l1, l2, tol=0.01):
    dx1 = l1.coords[1][0] - l1.coords[0][0]
    dy1 = l1.coords[1][1] - l1.coords[0][1]

    dx2 = l2.coords[1][0] - l2.coords[0][0]
    dy2 = l2.coords[1][1] - l2.coords[0][1]

    return isclose(dx1 * dy2, dy1 * dx2, abs_tol=tol)

def line_midpoint(line):
    coords = list(line.coords)
    return (
        (coords[0][0] + coords[1][0]) / 2,
        (coords[0][1] + coords[1][1]) / 2
    )

def distance(p1, p2):
    return hypot(p1[0] - p2[0], p1[1] - p2[1])


def detect_walls(linhas):
    paredes = []
    usadas = set()

    # 🔥 Filtra linhas muito pequenas (ruído)
    linhas_filtradas = [
        l for l in linhas if l["geom"].length > 0.3
    ]

    for i, l1 in enumerate(linhas_filtradas):
        if i in usadas:
            continue

        mid1 = line_midpoint(l1["geom"])

        for j, l2 in enumerate(linhas_filtradas[i+1:], start=i+1):
            if j in usadas:
                continue

            # 🔥 ignora se estiver longe demais
            mid2 = line_midpoint(l2["geom"])
            if distance(mid1, mid2) > 1.0:
                continue

            if is_parallel(l1["geom"], l2["geom"]):
                dist = l1["geom"].distance(l2["geom"])

                if 0.05 < dist < 0.5:
                    paredes.append({
                        "comprimento": l1["geom"].length,
                        "espessura": dist
                    })

                    usadas.update([i, j])
                    break
    return paredes

# ==============================
# AMBIENTES
# ==============================

def detect_rooms(poligonos, textos):
    ambientes = []

    for poly in poligonos:
        nome = "desconhecido"

        for t in textos:
            if poly.contains(t["ponto"]):
                nome = t["texto"]
                break

        ambientes.append({
            "nome": nome,
            "area": poly.area,
            "perimetro": poly.length
        })

    return ambientes

# ==============================
# PORTAS E JANELAS
# ==============================

def detect_openings(blocos):
    portas = []
    janelas = []

    for b in blocos:
        nome = b["nome"]

        if any(k in nome for k in ["porta", "door"]):
            portas.append(b)

        elif any(k in nome for k in ["janela", "window"]):
            janelas.append(b)

    return portas, janelas

# ==============================
# PILARES E VIGAS
# ==============================

def detect_structure(blocos):
    pilares = []
    vigas = []

    for b in blocos:
        nome = b["nome"]

        if any(k in nome for k in ["pilar", "column"]):
            pilares.append(b)

        elif any(k in nome for k in ["viga", "beam"]):
            vigas.append(b)

    return pilares, vigas

# ==============================
# VOLUME DE CONCRETO
# ==============================

def estimate_concrete(pilares, vigas, altura_padrao=3.0):
    volume_pilares = 0
    volume_vigas = 0

    # Heurística simples (ajustável)
    for p in pilares:
        base = 0.2 * 0.2  # 20x20 cm padrão
        volume_pilares += base * altura_padrao

    for v in vigas:
        secao = 0.2 * 0.4  # 20x40 cm padrão
        comprimento = 3.0  # estimativa média
        volume_vigas += secao * comprimento

    return volume_pilares, volume_vigas

# ==============================
# BUILD JSON FINAL
# ==============================

def build_json(paredes, ambientes, portas, janelas, pilares, vigas, vol_p, vol_v):
    return {
        "resumo": {
            "area_total": sum(a["area"] for a in ambientes),
            "comprimento_paredes": sum(p["comprimento"] for p in paredes),
            "volume_concreto_total": vol_p + vol_v
        },
        "arquitetura": {
            "ambientes": ambientes,
            "paredes": paredes,
            "portas": portas,
            "janelas": janelas
        },
        "estrutura": {
            "pilares": pilares,
            "vigas": vigas,
            "volume_concreto_pilares": vol_p,
            "volume_concreto_vigas": vol_v
        }
    }

# ==============================
# PIPELINE
# ==============================

def process(file_path):
    if is_dxf(file_path):
        dxf_path = file_path
    elif is_dwg(file_path):
        dxf_path = convert_dwg(file_path)
    else:
        raise Exception("Formato inválido")

    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    linhas, poligonos, textos, blocos = extract_entities(msp)

    paredes = detect_walls(linhas)
    ambientes = detect_rooms(poligonos, textos)
    portas, janelas = detect_openings(blocos)
    pilares, vigas = detect_structure(blocos)

    vol_p, vol_v = estimate_concrete(pilares, vigas)

    resultado = build_json(
        paredes, ambientes,
        portas, janelas,
        pilares, vigas,
        vol_p, vol_v
    )

    with open("memorial.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=4, ensure_ascii=False)

    print("✅ Memorial completo gerado!")

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    process("PNR S Ten Sgt - 2ª Fase.dxf")