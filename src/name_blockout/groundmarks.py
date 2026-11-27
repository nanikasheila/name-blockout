"""Marks on a white ground that say what it is made of: short blades on a lawn, dots on bare soil.

A manga leaves the ground white whatever it is made of, so a lawn, a yard of soil and a road run into one white
(a reader of the picture alone cannot tell the road from the lot). Paving has its joints; a lawn and soil get a
few marks, sparse, in the near and middle ground only. A mark is no boundary: it is drawn with the finest pen.

The marks stand at fixed spots of the place (a grid over its x and y, thinned with distance), so the same lawn
has the same blades from any camera, and the same instruction gives the same picture. Blender-free: from the
picture's passes (which ground each pixel shows, where it lies, how far off)."""

from __future__ import annotations

import math

import numpy as np

#: What the ground-kind pass says at a pixel (a face attribute's value): none, a lawn, bare soil.
KIND_CODES = {"草": 0.25, "土": 0.5}
#: The grid's cell near the camera (m): one mark a cell at most.
CELL_M = 0.9
#: Marks stand at least this far apart on the paper (mm), across; up the picture, where the ground lies flat to
#: the eye and rows of it close up, this share of it.
GAP_MM = 4.5
GAP_UP = 0.7
#: The share of cells that carry a mark (the rest stay empty: a lawn's marks are not a pattern).
KEEP = 0.55
#: A mark stands within this share of its cell from its spot, or not at all (its spot is hidden).
NEAR_SPOT = 0.2
#: A tuft's height (m), and what it may show as on the paper (mm): smaller, the marks end.
BLADE_M = (0.2, 0.3)
BLADE_MM = (0.7, 1.8)
#: A tuft's blades, side by side (from one point they would make an arrowhead): where each stands (across, in
#: tuft heights), how far it leans (degrees from upright) and its share of the tuft's height.
BLADES = ((-0.4, -14.0, 0.6), (0.0, 2.0, 1.0), (0.38, 12.0, 0.75))
LEAN_JITTER = 8.0
#: A dot of soil: as wide as this many pen widths; this many to a mark, within a blade's height of each other.
DOT_WIDTHS = 1.3
DOTS = 3


def _hash(*ints: np.ndarray, salt: int) -> np.ndarray:
    """A number in 0–1 for each cell (its whole-number coordinates), the same on every machine."""
    h = np.full(np.shape(ints[0]), np.uint64((0x9E3779B97F4A7C15 + salt * 0x632BE59BD9B4E019) & 0xFFFFFFFFFFFFFFFF), dtype=np.uint64)
    with np.errstate(over="ignore"):
        for v in ints:
            h ^= (
                np.asarray(v).astype(np.int64).astype(np.uint64) + np.uint64(0x9E3779B97F4A7C15) + (h << np.uint64(6)) + (h >> np.uint64(2))
            )
            h *= np.uint64(0xBF58476D1CE4E5B9)
            h ^= h >> np.uint64(31)
    return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def spots(
    kind: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    distance: np.ndarray,
    px_per_mm: float,
    reach: float,
    skip: np.ndarray | None = None,
) -> list[dict]:
    """Where the marks stand: for each, its pixel (`px`: across, down), its spot of the ground (`atM`), its
    distance, how many metres a pixel shows there across (`mPerPx`), its kind (草, 土) and its cell's number (for
    the blades' leans).

    `kind`: each pixel's ground (KIND_CODES' values; anything else is no ground to mark); `x`, `y`: where on the
    place each pixel's surface lies (m); `distance`: how far off (m); `reach`: marks end there; `skip`: pixels to
    leave alone (a street of the town laid over the land)."""
    h, w = kind.shape
    out: list[dict] = []
    for name, code in KIND_CODES.items():
        on = (np.abs(kind - code) < 0.05) & (distance > 0.0) & (distance <= reach)
        if skip is not None:
            on &= ~skip
        if not on.any():
            continue
        # Metres a pixel shows across and up the picture, from the pass itself (no camera needed): a lawn seen
        # flat to the eye shows many metres to a pixel's row.
        across = np.hypot(np.gradient(x, axis=1), np.gradient(y, axis=1))
        up = np.hypot(np.gradient(x, axis=0), np.gradient(y, axis=0))
        gap = GAP_MM * px_per_mm
        need = np.maximum(across, up * GAP_UP) * gap  # the cell (m) that keeps the marks `gap` apart here
        level = np.clip(np.ceil(np.log2(np.maximum(need, 1e-6) / CELL_M)), 0, 12).astype(np.int64)
        size = CELL_M * np.exp2(level)
        ix, iy = np.floor(x / size).astype(np.int64), np.floor(y / size).astype(np.int64)
        kept = _hash(level, ix, iy, salt=1) < KEEP
        # The cell's spot, and each pixel's distance from it.
        sx = (ix + 0.15 + 0.7 * _hash(level, ix, iy, salt=2)) * size
        sy = (iy + 0.15 + 0.7 * _hash(level, ix, iy, salt=3)) * size
        off = np.hypot(x - sx, y - sy)
        rows, cols = np.nonzero(on & kept & (off < NEAR_SPOT * size))
        if not len(rows):
            continue
        # One pixel a cell: the nearest to its spot.
        keys = np.stack([level[rows, cols], ix[rows, cols], iy[rows, cols]], axis=1)
        order = np.lexsort((off[rows, cols], keys[:, 2], keys[:, 1], keys[:, 0]))
        keys, rows, cols = keys[order], rows[order], cols[order]
        first = np.ones(len(rows), dtype=bool)
        first[1:] = (keys[1:] != keys[:-1]).any(axis=1)
        for r, c, key in zip(rows[first], cols[first], keys[first]):
            per = float(across[r, c])
            if per <= 0.0 or not (BLADE_MM[0] * px_per_mm <= BLADE_M[1] / per):
                continue  # too small on the paper to be a blade
            out.append(
                {
                    "px": (int(c), int(r)),
                    "atM": (round(float(sx[r, c]), 3), round(float(sy[r, c]), 3)),
                    "distanceM": round(float(distance[r, c]), 2),
                    "mPerPx": per,
                    "kind": name,
                    "cell": tuple(int(v) for v in key),
                }
            )
    out.sort(key=lambda s: (s["kind"], s["cell"]))
    return out


def _stamp(ink: np.ndarray, cx: float, cy: float, radius: float) -> None:
    h, w = ink.shape
    x0, x1 = max(0, int(cx - radius - 1)), min(w, int(cx + radius + 2))
    y0, y1 = max(0, int(cy - radius - 1)), min(h, int(cy + radius + 2))
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    cover = np.clip(radius + 0.5 - np.hypot(xx - cx, yy - cy), 0.0, 1.0)
    np.maximum(ink[y0:y1, x0:x1], cover, out=ink[y0:y1, x0:x1])


def draw(marks: list[dict], on: np.ndarray, px_per_mm: float, pen_mm: float) -> np.ndarray:
    """The marks as ink (0–1) on a picture the size of `on` (the pixels that show a ground to mark): each tuft
    three strokes of the finest pen side by side, upward from its spot; each mark of soil a few dots a pen's width
    across. A mark that would run over anything else (a thing standing by its spot, a path's edge) is left out:
    a mark is not to be mistaken for a part of a thing."""
    ink = np.zeros(on.shape, dtype=np.float32)
    h, w = on.shape
    radius = pen_mm * px_per_mm / 2.0

    def clear(px: float, py: float) -> bool:
        c, r = int(round(px)), int(round(py))
        return 0 <= c < w and 0 <= r < h and bool(on[r, c])

    for mark in marks:
        (cx, cy), per, cell = mark["px"], mark["mPerPx"], mark["cell"]
        key = [np.asarray(v) for v in cell]
        tall = BLADE_M[0] + (BLADE_M[1] - BLADE_M[0]) * float(_hash(*key, salt=4))
        tall_px = min(max(tall / per, BLADE_MM[0] * px_per_mm), BLADE_MM[1] * px_per_mm)
        stamps: list[tuple[float, float, float]] = []
        if mark["kind"] == "土":
            for i in range(DOTS):
                a = 2 * math.pi * float(_hash(*key, salt=10 + i))
                d = tall_px * (0.3 + 0.7 * float(_hash(*key, salt=20 + i)))
                stamps.append((cx + d * math.cos(a), cy + 0.4 * d * math.sin(a), radius * DOT_WIDTHS))
        else:
            for i, (aside, lean, share) in enumerate(BLADES):
                lean += LEAN_JITTER * (2.0 * float(_hash(*key, salt=30 + i)) - 1.0)
                dx, dy = math.sin(math.radians(lean)), -math.cos(math.radians(lean))
                steps = max(2, int(tall_px * share * 2))
                for s in range(steps + 1):
                    t = tall_px * share * s / steps
                    stamps.append((cx + aside * tall_px + dx * t, cy + dy * t, radius))
        if all(clear(px, py) for px, py, _ in stamps):
            for px, py, r in stamps:
                _stamp(ink, px, py, r)
            mark["drawn"] = True
    return ink


def counts(marks: list[dict]) -> dict:
    """How many marks of each kind, and how far off they go (for the check: numbers, not looks)."""
    out: dict = {}
    for name in KIND_CODES:
        mine = [m for m in marks if m["kind"] == name and m.get("drawn")]
        if mine:
            out[name] = {"marks": len(mine), "fromM": min(m["distanceM"] for m in mine), "toM": max(m["distanceM"] for m in mine)}
    return out
