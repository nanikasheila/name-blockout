# SPDX-License-Identifier: GPL-3.0-or-later
"""The development's lines: a line is a boundary, and as thick as the boundary is deep.

The author's rule for a manga background's finish:

- a line stands for a boundary, between a thing and what is behind it or between two faces of a thing;
- the deeper the boundary, the thicker the line; a shallow one (a fold in a surface, a thing's foot on the ground) is
  thin;
- near things are told by their lines; in the middle distance things are told by their tones (the shapes left white
  or toned: negative space), and far away lines are all but gone;
- hatching and the like (a floor's joints) are not these lines: they are drawn apart (develop.py).

How deep a boundary is, is measured as the eye sees depth: by the difference of 1/distance on its two sides (as
parallax), against the picture's own deepest boundaries (the deepest twentieth of them count 1: a room's sofa before
its wall, a lot's gatepost before the sky), but never finer than a thing 25 m off against the sky: beyond the near
band nothing is deep. So one rule gives all three: a near thing against a far wall gets a thick line; the same
thing's foot on the ground a thin one; a tree 200 m off against the sky almost none.

All of it works on pictures (numpy arrays, rows from the top), with no Blender: develop.py renders the depths and
normals and calls in here.
"""

from __future__ import annotations

import math

import numpy as np

from .far import NEAR_M

#: The thickest line (the deepest boundary), and the thinnest drawn (a pen's finest: a shallower boundary gets no
#: line, and is told by the tones on its two sides), in mm on the page.
W_MAX_MM = 0.4
W_MIN_MM = 0.05
#: A fold between two faces (no depth between them), at the foreground's distance: how deep it counts. Farther
#: off it counts less, as its distance grows.
FOLD_DEPTH = 0.15
#: Two faces fold if their normals differ by more than this.
FOLD_MIN_DEG = 30.0
#: The foreground's distance is kept within these (m): nearer, a boundary is as deep as it gets.
D_REF_MIN = 1.5
D_REF_MAX = NEAR_M
#: Boundaries deeper than this share of their distance are clear ones: the nearest of them tell where the
#: picture's foreground is, the deepest how deep its boundaries get.
D_REF_GAP = 0.05
D_REF_PERCENTILE = 5.0
DEEPEST_PERCENTILE = 95.0
#: Width = W_MAX × depth^GAMMA (under 1: the middle depths keep some width, as a pen's three or four weights).
GAMMA = 0.75
#: A boundary pixel with fewer than this many boundary pixels in the 5 × 5 round it is a speck (a face smaller
#: than a pixel), not a line.
SPECK_UNDER = 4

_SHIFTS = ((0, 1), (0, -1), (1, 0), (-1, 0))


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """a[y + dy, x + dx] at [y, x], the picture's edge repeated."""
    pad = [(max(-dy, 0), max(dy, 0)), (max(-dx, 0), max(dx, 0))] + [(0, 0)] * (a.ndim - 2)
    p = np.pad(a, pad, mode="edge")
    h, w = a.shape[:2]
    y0, x0 = max(dy, 0), max(dx, 0)
    return p[y0 : y0 + h, x0 : x0 + w]


def scales(z: np.ndarray, thing: np.ndarray, gap: np.ndarray) -> tuple[float, float]:
    """The picture's foreground distance (m: where its nearest clear boundaries are) and the distance a thing
    against the sky would be at to make the picture's deepest boundaries (1 / their jump of 1/z), both kept within
    D_REF_MIN–D_REF_MAX. `gap`: each pixel's jump of 1/z."""
    clear = thing & (gap * z > D_REF_GAP)
    if clear.any():
        near = float(np.percentile(z[clear], D_REF_PERCENTILE))
        deepest = 1.0 / max(float(np.percentile(gap[clear], DEEPEST_PERCENTILE)), 1e-6)
    else:
        near = deepest = float(np.percentile(z[thing], D_REF_PERCENTILE)) if thing.any() else D_REF_MAX
    return tuple(float(min(D_REF_MAX, max(D_REF_MIN, v))) for v in (near, deepest))


def _count(mask: np.ndarray, r: int) -> np.ndarray:
    """How many of the (2r+1)² pixels round each pixel are set."""
    padded = np.pad(mask.astype(np.int32), r + 1, mode="constant")
    total = padded.cumsum(0).cumsum(1)
    n = 2 * r + 1
    h, w = mask.shape
    return total[n : n + h, n : n + w] - total[0:h, n : n + w] - total[n : n + h, 0:w] + total[0:h, 0:w]


def boundary_depths(
    z: np.ndarray,
    thing: np.ndarray,
    normal: np.ndarray | None = None,
    soft: np.ndarray | None = None,
    d_ref: float | None = None,
    deepest: float | None = None,
) -> tuple[np.ndarray, float, float]:
    """How deep the boundary at each pixel is (0: none … 1: the deepest), marked on the boundary's near side; the
    foreground distance (`d_ref`) and the deepest boundaries' distance (`deepest`) used.

    `z`: each pixel's depth from the camera (m); `thing`: where there is a surface (not the sky); `normal`: each
    pixel's surface normal (unit, 3 values) for the folds; `soft`: surfaces whose folds are not drawn (a crown's
    lumps, a louvre's slats)."""
    q = np.where(thing, 1.0 / np.maximum(z, 1e-3), 0.0).astype(np.float32)
    gap = np.zeros_like(q)
    for dy, dx in _SHIFTS:
        behind = _shift(q, dy, dx)
        before = _shift(q, -dy, -dx)
        # A plane's 1/z runs evenly across the picture: what this pixel's surface would be one pixel on is taken
        # off, so a floor running away from the eye is no boundary.
        jump = np.minimum(q - behind, 2 * q - before - behind)
        gap = np.maximum(gap, np.where(thing, np.maximum(jump, 0.0), 0.0))
    # At the picture's edge there is no pixel before to tell a surface's slope by: no boundary is marked there.
    gap[0, :] = gap[-1, :] = 0.0
    gap[:, 0] = gap[:, -1] = 0.0
    if d_ref is None or deepest is None:
        found = scales(z, thing, gap)
        d_ref = found[0] if d_ref is None else d_ref
        deepest = found[1] if deepest is None else deepest
    depth = np.minimum(1.0, gap * deepest)
    if normal is not None:
        cos_min = math.cos(math.radians(FOLD_MIN_DEG))
        hard = thing if soft is None else thing & ~soft
        fold = np.zeros(q.shape, dtype=bool)
        nearest = np.zeros_like(q)
        for dy, dx in ((0, 1), (1, 0)):
            other = _shift(normal, dy, dx)
            both = hard & _shift(hard, dy, dx)
            bent = both & ((normal * other).sum(axis=-1) < cos_min)
            fold |= bent
            nearest = np.maximum(nearest, np.where(bent, np.maximum(q, _shift(q, dy, dx)), 0.0))
        depth = np.maximum(depth, np.where(fold, FOLD_DEPTH * np.minimum(1.0, nearest * d_ref), 0.0))
    depth[depth < 1e-3] = 0.0  # rounding on an even plane
    depth[(depth > 0) & (_count(depth > 0, 2) < SPECK_UNDER)] = 0.0
    return depth.astype(np.float32), d_ref, deepest


def fold_mm() -> float:
    """A fold's line width at the foreground's distance (mm on the page)."""
    return W_MAX_MM * FOLD_DEPTH**GAMMA


def widths(depth: np.ndarray, px_per_mm: float) -> np.ndarray:
    """Each boundary pixel's line width in pixels (0: no line)."""
    w = W_MAX_MM * np.power(depth, GAMMA, dtype=np.float32) * px_per_mm
    return np.where(w >= W_MIN_MM * px_per_mm, w, 0.0).astype(np.float32)


def stroke(width: np.ndarray) -> np.ndarray:
    """The ink (0–1) of lines `width` pixels wide centred on the pixels where width > 0: round, their edges
    smooth, a line thinner than a pixel drawn as a paler one."""
    half = width / 2.0
    # A line thinner than a pixel covers that share of its pixel.
    ink = np.where((width > 0) & (width < 1), width, 0.0).astype(np.float32)
    v = np.where(width >= 1, half, -np.inf).astype(np.float32)
    top = float(half.max()) if half.size else 0.0
    if top >= 0.5:
        # Each pixel's best (half width − distance) over the line pixels round it (a chamfer: 1 along the rows and
        # columns, √2 across), so a line is as wide as its own boundary is deep.
        root2 = np.float32(math.sqrt(2.0))
        for _ in range(int(math.ceil(top + 0.5))):
            best = v
            for dy, dx in _SHIFTS:
                best = np.maximum(best, _shift(v, dy, dx) - 1.0)
            for dy, dx in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                best = np.maximum(best, _shift(v, dy, dx) - root2)
            v = best
        ink = np.maximum(ink, np.clip(v + 0.5, 0.0, 1.0))
    return ink


def shrink(ink: np.ndarray, by: int) -> np.ndarray:
    """A picture drawn `by` times as large, brought down (each pixel the mean of its by × by)."""
    if by == 1:
        return ink
    h, w = ink.shape[0] // by, ink.shape[1] // by
    return ink[: h * by, : w * by].reshape(h, by, w, by).mean(axis=(1, 3)).astype(np.float32)


def boundary_lines(
    z: np.ndarray,
    thing: np.ndarray,
    normal: np.ndarray | None,
    soft: np.ndarray | None,
    px_per_mm: float,
    by: int = 1,
    d_ref: float | None = None,
    deepest: float | None = None,
) -> tuple[np.ndarray, dict]:
    """The lines' ink (0–1) at the picture's size, from passes drawn `by` times as large; and what was measured
    (the foreground distance, the deepest boundaries' distance, the share of the picture inked, by band)."""
    depth, d_ref, deepest = boundary_depths(z, thing, normal, soft, d_ref, deepest)
    drawn = stroke(widths(depth, px_per_mm * by))
    info = {
        "foregroundM": round(d_ref, 2),
        "deepestM": round(deepest, 2),
        "inkShare": round(float(drawn.mean()), 4),
        "bands": bands_report(drawn, z, thing, d_ref),
    }
    return shrink(drawn, by), info


def bands_report(ink: np.ndarray, z: np.ndarray, thing: np.ndarray, d_ref: float) -> dict:
    """The share of each distance band's pixels that is inked (near: up to 3 foregrounds off; middle: up to 12;
    far: beyond), for checking that lines thin out with distance."""
    out = {}
    edges = {"near": (0.0, 3 * d_ref), "middle": (3 * d_ref, 12 * d_ref), "far": (12 * d_ref, math.inf)}
    for name, (lo, hi) in edges.items():
        where = thing & (z >= lo) & (z < hi)
        out[name] = round(float(ink[where].mean()), 4) if where.any() else None
    return out
