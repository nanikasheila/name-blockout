# SPDX-License-Identifier: GPL-3.0-or-later
"""A mesh seen from straight above, as a plan would draw it: its true outline (an L-shaped house stays an L, every
tree of a planting is its own shape, a courtyard is a hole) and its cut at a height (the walls of a floor plan).

The outline is measured on a grid: the mesh's triangles are filled into cells, and the cells' border is walked
into rings (outer rings counter-clockwise, holes clockwise). A cell counts when the mesh touches it, so an outline
runs up to a cell outside the mesh (5 cm for a thing under 20 m across): a drawing to read a layout from, not a
survey. A convex hull would wrap a whole garden into one
blob; this does not.

numpy only (no bpy): vertices and triangles come in as arrays.
"""

from __future__ import annotations

import math

import numpy as np

#: The grid's cell (m): as fine as MIN_CELL, coarser for a large thing so that it is at most MAX_CELLS across.
MIN_CELL = 0.05
MAX_CELL = 0.5
MAX_CELLS = 400
#: Rings smaller than this are left out (m²), and a ring keeps to its cells' border within this share of a cell.
MIN_AREA = 0.02
SMOOTH = 1.5
KEEP_AREA = 0.7
#: A cut's ends closer than this are one point (m), and its lines are straightened within this (m).
JOIN = 0.01
STRAIGHT = 0.01


def cell_for(xy: np.ndarray) -> float:
    """The grid's cell for a thing of this extent."""
    if not len(xy):
        return MIN_CELL
    extent = float((xy.max(axis=0) - xy.min(axis=0)).max())
    return min(MAX_CELL, max(MIN_CELL, extent / MAX_CELLS))


def raster(xy: np.ndarray, tris: np.ndarray, cell: float) -> tuple[np.ndarray, tuple[float, float]]:
    """The cells a mesh covers from above: a mask (rows along y, columns along x) and its lowest corner (m)."""
    xy = np.asarray(xy, dtype=np.float64)
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if not len(xy) or not len(tris):
        return np.zeros((1, 1), dtype=bool), (0.0, 0.0)
    lo = np.floor(xy.min(axis=0) / cell) - 1
    grid = xy / cell - lo  # in cells
    nx, ny = (np.floor(grid.max(axis=0)).astype(int) + 2).tolist()
    mask = np.zeros((ny, nx), dtype=bool)

    p = grid[tris]  # (m, 3, 2)
    # Every edge, sampled twice a cell: a sliver thinner than a cell still leaves its mark.
    a, b = p, np.roll(p, -1, axis=1)
    steps = np.ceil(np.abs(b - a).max(axis=2) * 2).astype(int) + 1  # (m, 3)
    count = steps.reshape(-1)
    start = np.repeat(a.reshape(-1, 2), count, axis=0)
    span = np.repeat((b - a).reshape(-1, 2), count, axis=0)
    first = np.cumsum(count) - count
    t = (np.arange(count.sum()) - np.repeat(first, count)) / np.repeat(np.maximum(count - 1, 1), count)
    on = np.floor(start + span * t[:, None]).astype(int)
    mask[on[:, 1], on[:, 0]] = True

    # The inside of the triangles wider than a cell or two.
    lo_c = np.floor(p.min(axis=1)).astype(int)
    hi_c = np.floor(p.max(axis=1)).astype(int)
    for i in np.nonzero(((hi_c - lo_c) >= 2).any(axis=1))[0]:
        (x0, y0), (x1, y1) = lo_c[i], hi_c[i]
        xs = np.arange(x0, x1 + 1) + 0.5
        ys = np.arange(y0, y1 + 1) + 0.5
        gx, gy = np.meshgrid(xs, ys)
        (ax, ay), (bx, by), (cx, cy) = p[i]
        e0 = (bx - ax) * (gy - ay) - (by - ay) * (gx - ax)
        e1 = (cx - bx) * (gy - by) - (cy - by) * (gx - bx)
        e2 = (ax - cx) * (gy - cy) - (ay - cy) * (gx - cx)
        inside = ((e0 >= 0) & (e1 >= 0) & (e2 >= 0)) | ((e0 <= 0) & (e1 <= 0) & (e2 <= 0))
        mask[y0 : y1 + 1, x0 : x1 + 1] |= inside
    return mask, (float(lo[0] * cell), float(lo[1] * cell))


def _area(ring) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) / 2


def _straighten(points: list, eps: float) -> list:
    """A line through fewer of its points, never further than eps from the ones left out (Douglas–Peucker)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = points[i], points[j]
        dx, dy = bx - ax, by - ay
        n = math.hypot(dx, dy)
        worst, at = 0.0, None
        for k in range(i + 1, j):
            px, py = points[k]
            d = abs(dx * (py - ay) - dy * (px - ax)) / n if n > 1e-12 else math.hypot(px - ax, py - ay)
            if d > worst:
                worst, at = d, k
        if at is not None and worst > eps:
            keep[at] = True
            stack += [(i, at), (at, j)]
    return [q for q, k in zip(points, keep) if k]


def _smooth_ring(ring: list, eps: float) -> list:
    """A closed ring straightened: cut at its two points furthest apart, each half straightened."""
    if len(ring) < 5:
        return ring
    a = min(range(len(ring)), key=lambda i: ring[i])
    b = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[a][0]) ** 2 + (ring[i][1] - ring[a][1]) ** 2)
    a, b = sorted((a, b))
    one = _straighten(ring[a : b + 1], eps)
    two = _straighten(ring[b:] + ring[: a + 1], eps)
    return one[:-1] + two[:-1]


def trace(mask: np.ndarray, cell: float, origin: tuple[float, float], min_area: float = MIN_AREA) -> list[list[list[float]]]:
    """The border of a mask's cells as rings (m): outer rings counter-clockwise, holes clockwise, the largest
    first."""
    m = np.pad(np.asarray(mask, dtype=bool), 1)
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(sel, start, end):
        rows, cols = np.nonzero(sel)
        for r, c in zip(rows.tolist(), cols.tolist()):
            edges.setdefault((c + start[0], r + start[1]), []).append((c + end[0], r + end[1]))

    # A filled cell (r, c) covers x c..c+1, y r..r+1. Each side that faces an empty cell is an edge with the
    # filled cell on its left.
    add(m & ~np.roll(m, 1, axis=0), (0, 0), (1, 0))  # below is empty
    add(m & ~np.roll(m, -1, axis=1), (1, 0), (1, 1))  # right is empty
    add(m & ~np.roll(m, -1, axis=0), (1, 1), (0, 1))  # above is empty
    add(m & ~np.roll(m, 1, axis=1), (0, 1), (0, 0))  # left is empty

    rings = []
    while edges:
        first = next(iter(edges))
        ring = [first]
        prev, here = None, first
        while True:
            nexts = edges[here]
            if len(nexts) == 1 or prev is None:
                nxt = nexts.pop(0)
            else:
                # Two cells touching at a corner: turn left, so that each ring stays simple.
                dx, dy = here[0] - prev[0], here[1] - prev[1]
                nxt = max(nexts, key=lambda q: dx * (q[1] - here[1]) - dy * (q[0] - here[0]))
                nexts.remove(nxt)
            if not nexts:
                del edges[here]
            if nxt == first:
                break
            ring.append(nxt)
            prev, here = here, nxt
        # The pad's one cell back off, into metres.
        pts = [[origin[0] + (x - 1) * cell, origin[1] + (y - 1) * cell] for x, y in ring]
        smooth = _smooth_ring(pts, cell * SMOOTH)
        if len(smooth) < 3 or abs(_area(smooth)) < KEEP_AREA * abs(_area(pts)):
            # A thing about a cell thin (a fence, a sheet of glass) would be straightened away: keep its cells.
            smooth = _smooth_ring(pts, cell * 0.01)
        pts = smooth
        if len(pts) >= 3 and abs(_area(pts)) >= min_area:
            rings.append([[round(x, 3), round(y, 3)] for x, y in pts])
    rings.sort(key=lambda r: -abs(_area(r)))
    return rings


def silhouette(xy: np.ndarray, tris: np.ndarray, min_area: float = MIN_AREA) -> list[list[list[float]]]:
    """A mesh's outline from straight above, as rings (m)."""
    cell = cell_for(np.asarray(xy, dtype=np.float64))
    mask, origin = raster(xy, tris, cell)
    return trace(mask, cell, origin, min_area)


def rings_area(rings: list) -> float:
    """What rings cover (m²): outer rings less their holes."""
    return sum(_area(r) for r in rings)


def section(xyz: np.ndarray, tris: np.ndarray, z: float) -> list[list[list[float]]]:
    """A mesh cut by the level plane at height z: the cut's lines on the ground (m), joined end to end."""
    xyz = np.asarray(xyz, dtype=np.float64)
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if not len(xyz) or not len(tris):
        return []
    d = xyz[:, 2] - z
    d = np.where(d == 0.0, 1e-9, d)  # a vertex on the plane counts as above it
    dt = d[tris]
    crossing = (dt.min(axis=1) < 0) & (dt.max(axis=1) > 0)
    t3, d3 = tris[crossing], dt[crossing]
    if not len(t3):
        return []
    ends = np.zeros((len(t3), 2, 2))
    filled = np.zeros(len(t3), dtype=int)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        cross = (d3[:, i] < 0) != (d3[:, j] < 0)
        t = d3[:, i] / np.where(cross, d3[:, i] - d3[:, j], 1.0)
        point = xyz[t3[:, i], :2] + (xyz[t3[:, j], :2] - xyz[t3[:, i], :2]) * t[:, None]
        rows = np.nonzero(cross)[0]
        ends[rows, filled[rows]] = point[rows]
        filled[rows] += 1
    keys = np.round(ends / JOIN).astype(np.int64)
    links: dict[tuple[int, int], list[tuple[int, int]]] = {}
    seen = set()
    for a, b in keys.tolist():
        a, b = tuple(a), tuple(b)
        if a == b or (a, b) in seen or (b, a) in seen:
            continue
        seen.add((a, b))
        links.setdefault(a, []).append(b)
        links.setdefault(b, []).append(a)

    def take(a, b):
        links[a].remove(b)
        links[b].remove(a)

    lines = []
    # Open lines from their ends first, then what is left is closed loops.
    for starts in ([k for k, v in links.items() if len(v) != 2], list(links)):
        for s in starts:
            while links.get(s):
                line, here = [s], s
                while links.get(here):
                    nxt = links[here][0]
                    take(here, nxt)
                    line.append(nxt)
                    here = nxt
                    if here == s or len(links.get(here, ())) != 1:
                        break
                pts = _straighten([[x * JOIN, y * JOIN] for x, y in line], STRAIGHT)
                lines.append([[round(x, 3), round(y, 3)] for x, y in pts])
    return lines
