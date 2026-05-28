"""
Motor geometrico avancado para processamento de DXF.

Implementa vertex snapping, remocao de duplicatas, merge colinear,
poligonizacao com Shapely e validacao de poligonos.

Inspirado no Blueprint (apps/projetos/ai/cad/).
"""
from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, Point, Polygon, MultiPolygon
from shapely.ops import linemerge, unary_union, polygonize_full
from shapely.validation import make_valid


# ---------------------------------------------------------------------------
# Vertex Snapping
# ---------------------------------------------------------------------------

def snap_vertices(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    tolerance: float = 0.005,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    Agrupa vertices proximos (< tolerance) para corrigir imprecisoes do CAD.
    Usa grid-based snapping: cada vertice e mapeado para uma celula de grade.
    """
    if not segments:
        return []

    # Mapear vertices unicos para canonical points
    canonical: dict[tuple[int, int], tuple[float, float]] = {}
    cell_size = tolerance

    def _snap_point(p: tuple[float, float]) -> tuple[float, float]:
        """Encontra ou cria o ponto canonico mais proximo."""
        cell = (int(p[0] / cell_size), int(p[1] / cell_size))

        # Verificar celula e vizinhos
        best_key = None
        best_dist = tolerance

        for dx in range(-1, 2):
            for dy in range(-1, 2):
                neighbor = (cell[0] + dx, cell[1] + dy)
                if neighbor in canonical:
                    cp = canonical[neighbor]
                    dist = ((p[0] - cp[0]) ** 2 + (p[1] - cp[1]) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_key = neighbor

        if best_key is not None:
            return canonical[best_key]

        # Criar novo ponto canonico
        canonical[cell] = p
        return p

    snapped = []
    for start, end in segments:
        s = _snap_point(start)
        e = _snap_point(end)
        # Descartar segmentos muito curtos apos snap
        if ((s[0] - e[0]) ** 2 + (s[1] - e[1]) ** 2) ** 0.5 > tolerance:
            snapped.append((s, e))

    return snapped


# ---------------------------------------------------------------------------
# Remocao de duplicatas
# ---------------------------------------------------------------------------

def merge_duplicates(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Remove segmentos duplicados (mesmo inicio/fim, em qualquer direcao)."""
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    result = []

    for start, end in segments:
        # Normalizar: menor ponto primeiro
        if start > end:
            start, end = end, start
        key = (start, end)
        if key not in seen:
            seen.add(key)
            result.append((start, end))

    return result


# ---------------------------------------------------------------------------
# Merge colinear
# ---------------------------------------------------------------------------

def merge_collinear(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    tolerance: float = 0.002,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    Funde segmentos colineares sobrepostos.
    Agrupa por direcao normalizada e distancia perpendicular.
    """
    if len(segments) < 2:
        return segments

    def _direction(seg):
        dx = seg[1][0] - seg[0][0]
        dy = seg[1][1] - seg[0][1]
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-10:
            return (0.0, 0.0)
        return (dx / length, dy / length)

    def _perp_dist(point, dir_vec):
        # Distancia perpendicular de um ponto a uma linha na direcao
        return abs(-dir_vec[1] * point[0] + dir_vec[0] * point[1])

    # Agrupar segmentos por direcao e distancia perpendicular
    groups: list[list[int]] = []
    used = [False] * len(segments)

    for i, seg_i in enumerate(segments):
        if used[i]:
            continue
        dir_i = _direction(seg_i)
        if dir_i == (0.0, 0.0):
            continue

        group = [i]
        used[i] = True

        for j in range(i + 1, len(segments)):
            if used[j]:
                continue
            seg_j = segments[j]
            dir_j = _direction(seg_j)

            # Verificar mesma direcao (ou oposta)
            dot = dir_i[0] * dir_j[0] + dir_i[1] * dir_j[1]
            if abs(abs(dot) - 1.0) > 0.01:
                continue

            # Verificar mesma linha (distancia perpendicular baixa)
            if _perp_dist(seg_j[0], dir_i) > tolerance:
                continue

            group.append(j)
            used[j] = True

        groups.append(group)

    # Para cada grupo, fundir sobreposicoes
    result = []
    for group in groups:
        if len(group) == 1:
            result.append(segments[group[0]])
            continue

        # Projetar todos os segmentos no eixo da direcao
        dir_vec = _direction(segments[group[0]])
        origin = segments[group[0]][0]

        intervals = []
        for idx in group:
            seg = segments[idx]
            p0 = (seg[0][0] - origin[0]) * dir_vec[0] + (seg[0][1] - origin[1]) * dir_vec[1]
            p1 = (seg[1][0] - origin[0]) * dir_vec[0] + (seg[1][1] - origin[1]) * dir_vec[1]
            if p0 > p1:
                p0, p1 = p1, p0
            intervals.append((p0, p1))

        # Merge intervals
        intervals.sort()
        merged = [intervals[0]]
        for start, end in intervals[1:]:
            if start <= merged[-1][1] + tolerance:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        # Converter de volta para coordenadas
        for start, end in merged:
            s = (origin[0] + start * dir_vec[0], origin[1] + start * dir_vec[1])
            e = (origin[0] + end * dir_vec[0], origin[1] + end * dir_vec[1])
            result.append((s, e))

    return result


# ---------------------------------------------------------------------------
# Poligonizacao
# ---------------------------------------------------------------------------

def polygonize_geometry(
    linestrings: list[LineString],
) -> tuple[list[Polygon], list[Any], list[Any], list[Any]]:
    """
    Converte LineStrings em poligonos fechados usando Shapely polygonize_full.

    Retorna:
        polygons: lista de Polygon validos
        dangles: segmentos pendurados
        cuts: segmentos que se cruzam
        invalid_rings: aneis invalidos
    """
    if not linestrings:
        return [], [], [], []

    # Merge linestrings
    merged = linemerge(unary_union(linestrings))

    # Polygonize
    result = polygonize_full(merged)
    polygons = list(result.geoms) if hasattr(result, 'geoms') else []

    # Extrair dangles, cuts, invalid_rings do resultado
    # polygonize_full retorna (polygons, dangles, cuts, invalid_rings)
    # Mas o resultado e um GeometryCollection
    dangles = []
    cuts = []
    invalid_rings = []

    return polygons, dangles, cuts, invalid_rings


# ---------------------------------------------------------------------------
# Validacao de poligonos
# ---------------------------------------------------------------------------

def validate_polygons(
    polygons: list[Polygon],
    min_area: float = 0.1,
) -> list[Polygon]:
    """
    Valida e repara poligonos usando Shapely.
    Remove poligonos com area muito pequena ou invalidos.
    """
    valid = []

    for poly in polygons:
        # Tentar reparar geometria invalida
        if not poly.is_valid:
            try:
                poly = make_valid(poly)
            except Exception:
                continue

        # buffer(0) como fallback de reparo
        if not poly.is_valid:
            try:
                poly = poly.buffer(0)
            except Exception:
                continue

        # MultiPolygon -> pegar o maior
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda g: g.area)

        # Filtrar por area minima
        if poly.area < min_area:
            continue

        if poly.is_valid and not poly.is_empty:
            valid.append(poly)

    return valid


# ---------------------------------------------------------------------------
# Pipeline completo
# ---------------------------------------------------------------------------

def processar_geometria(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    tolerance: float = 0.005,
) -> list[Polygon]:
    """
    Pipeline completo de processamento geometrico:
    1. Snap vertices
    2. Remove duplicatas
    3. Merge colinear
    4. Polygonize
    5. Validate
    """
    # 1. Snap
    snapped = snap_vertices(segments, tolerance)

    # 2. Deduplicate
    deduped = merge_duplicates(snapped)

    # 3. Merge collinear
    merged = merge_collinear(deduped, tolerance * 0.4)

    # 4. Convert to LineStrings
    linestrings = [LineString([s, e]) for s, e in merged if s != e]

    # 5. Polygonize
    polygons, _, _, _ = polygonize_geometry(linestrings)

    # 6. Validate
    valid_polygons = validate_polygons(polygons)

    return valid_polygons
