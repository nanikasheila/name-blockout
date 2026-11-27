# SPDX-License-Identifier: GPL-3.0-or-later
"""How much is drawn in a picture, in numbers: to compare a take with a reference by measuring, not by eye.

A picture is read as its grey (0 = black, 1 = paper, as shown on a screen). Three shares: black (lines and ベタ),
tone (the greys between) and paper; and the same per cell of a 3×3 grid, since a picture as dense as its reference
on the whole can still be empty in one corner. Two pictures are compared at the same number of pixels across
(a thin line is black only while a pixel is no wider than it), each keeping its own shape.

numpy only (no bpy): the pictures come in as arrays.
"""

from __future__ import annotations

import numpy as np

#: Grey below this is black (a line, ベタ); above WHITE it is paper; between, a tone.
DARK = 0.35
WHITE = 0.92
#: The grid's rows and columns, and their names (rows from the top, columns from the left).
GRID = 3
ROWS = ("上", "中", "下")
COLUMNS = ("左", "中", "右")
#: A take with less than this share of its reference's black is too empty.
FAIL_UNDER = 0.8
#: A reference cell with less black than this is not compared (the ratio of two near-nothings says nothing).
MIN_SHARE = 0.01
#: Shapes (width / height) further apart than this are not the same framing: the cells do not show the same things.
SAME_SHAPE = 0.05


def grey(rgba: np.ndarray) -> np.ndarray:
    """A picture (h, w) or (h, w, 3 or 4) as its grey on white paper."""
    a = np.asarray(rgba, dtype=np.float32)
    if a.ndim == 2:
        return np.clip(a, 0.0, 1.0)
    lum = a[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32) if a.shape[-1] >= 3 else a[..., 0]
    if a.shape[-1] == 4:
        lum = lum * a[..., 3] + (1.0 - a[..., 3])
    return np.clip(lum, 0.0, 1.0)


def shrink(picture: np.ndarray, h: int, w: int) -> np.ndarray:
    """A picture (h, w) or (h, w, c) made smaller by the mean of the pixels each new one covers; never larger."""
    a = np.asarray(picture, dtype=np.float32)
    sh, sw = a.shape[:2]
    h, w = min(h, sh), min(w, sw)
    if (h, w) == (sh, sw):
        return a
    ys = np.linspace(0, sh, h + 1).round().astype(int)
    xs = np.linspace(0, sw, w + 1).round().astype(int)
    total = np.add.reduceat(np.add.reduceat(a.astype(np.float64), ys[:-1], axis=0), xs[:-1], axis=1)
    area = (np.diff(ys)[:, None] * np.diff(xs)[None, :]).astype(np.float64)
    return (total / (area if a.ndim == 2 else area[..., None])).astype(np.float32)


def cell_name(row: int, column: int) -> str:
    return f"{ROWS[row]}段・{COLUMNS[column]}"


def cell_box(shape: tuple[int, int], row: int, column: int) -> tuple[int, int, int, int]:
    """A grid cell's pixels: y0, y1, x0, x1."""
    h, w = shape
    ys = np.linspace(0, h, GRID + 1).round().astype(int)
    xs = np.linspace(0, w, GRID + 1).round().astype(int)
    return int(ys[row]), int(ys[row + 1]), int(xs[column]), int(xs[column + 1])


def _shares(lum: np.ndarray) -> dict:
    n = max(lum.size, 1)
    dark = float((lum < DARK).sum()) / n
    white = float((lum > WHITE).sum()) / n
    return {
        "ink": round(float((1.0 - lum).mean()) if lum.size else 0.0, 4),
        "dark": round(dark, 4),
        "tone": round(max(0.0, 1.0 - dark - white), 4),
        "white": round(white, 4),
    }


def measure(lum: np.ndarray) -> dict:
    """The shares of a grey picture, and per cell of the grid (rows from the top)."""
    out = _shares(lum)
    cells = [
        [_shares(lum[slice(*cell_box(lum.shape, r, c)[:2]), slice(*cell_box(lum.shape, r, c)[2:])]) for c in range(GRID)]
        for r in range(GRID)
    ]
    out["grid"] = {key: [[cell[key] for cell in row] for row in cells] for key in ("ink", "dark", "tone")}
    return out


def same_width(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two grey pictures at the same number of pixels across (the wider made smaller), each keeping its own shape."""
    w = min(a.shape[1], b.shape[1])
    return tuple(shrink(p, max(1, round(p.shape[0] * w / p.shape[1])), w) for p in (a, b))  # type: ignore[return-value]


def _ratio(value: float, reference: float) -> float | None:
    return round(value / reference, 2) if reference >= MIN_SHARE else None


def compare(take: np.ndarray, reference: np.ndarray) -> dict:
    """A take's numbers beside its reference's: the ratios (take / reference), and where the take is too empty."""
    take, reference = same_width(grey(take), grey(reference))
    mine, theirs = measure(take), measure(reference)
    shapes = [p.shape[1] / p.shape[0] for p in (take, reference)]
    same_framing = abs(shapes[0] / shapes[1] - 1.0) <= SAME_SHAPE
    ratios = {key: _ratio(mine[key], theirs[key]) for key in ("ink", "dark", "tone")}
    ratios["grid"] = {
        key: [[_ratio(mine["grid"][key][r][c], theirs["grid"][key][r][c]) for c in range(GRID)] for r in range(GRID)]
        for key in ("ink", "dark")
    }
    findings = []
    if ratios["dark"] is not None and ratios["dark"] < FAIL_UNDER:
        findings.append({"where": "全体", "measure": "dark", "take": mine["dark"], "reference": theirs["dark"], "ratio": ratios["dark"]})
    if same_framing:
        for r in range(GRID):
            for c in range(GRID):
                ratio = ratios["grid"]["dark"][r][c]
                if ratio is not None and ratio < FAIL_UNDER:
                    findings.append(
                        {
                            "where": cell_name(r, c),
                            "cell": [r, c],
                            "measure": "dark",
                            "take": mine["grid"]["dark"][r][c],
                            "reference": theirs["grid"]["dark"][r][c],
                            "ratio": ratio,
                        }
                    )
    return {
        "comparedAtPx": int(take.shape[1]),
        "sameFraming": same_framing,
        "take": mine,
        "reference": theirs,
        "ratios": ratios,
        "failUnder": FAIL_UNDER,
        "tooEmpty": findings,
        "pass": not findings,
    }


def emptiest_cells(result: dict, count: int = 2) -> list[tuple[int, int]]:
    """The cells where the take falls furthest short of its reference (to look at closer)."""
    cells = sorted((f for f in result.get("tooEmpty", []) if "cell" in f), key=lambda f: f["ratio"])
    return [tuple(f["cell"]) for f in cells[:count]]
