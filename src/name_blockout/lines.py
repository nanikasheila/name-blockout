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
its wall, a lot's gatepost before the sky, a house seen from a hill before the land behind it). Beyond the picture's
foreground a boundary counts less again, as its distance grows (the middle distance is told by tones, not lines).
So one rule gives all three: a near thing against a far wall gets a thick line; the same thing's foot on the ground
a thin one; a gatepost ten foregrounds off a hair, and a tree 200 m off against the sky none.

Where the lines thin out, the tones take over (`tone_floor`): a standing thing in the middle distance is never left
white on a white ground.

All of it works on pictures (numpy arrays, rows from the top), with no Blender: develop.py renders the depths and
normals and calls in here.
"""

from __future__ import annotations

import math

import numpy as np

from .far import FAR_M, NEAR_M

#: The thickest line (the deepest boundary), and the thinnest drawn (a pen's finest: a shallower boundary gets no
#: line, and is told by the tones on its two sides), in mm on the page. Between the thinnest and W_FULL_MM a line
#: is drawn paler as well as thinner (it dies away, instead of stopping short where a boundary shallows).
W_MAX_MM = 0.5
W_FULL_MM = 0.1
W_MIN_MM = 0.05
#: A fold between two faces (no depth between them), at the foreground's distance: how deep it counts (a 0.1 mm
#: line). Farther off it counts less, as its distance grows.
FOLD_DEPTH = 0.04
#: Two faces fold if their normals differ by more than this.
FOLD_MIN_DEG = 30.0
#: The foreground's distance and the deepest boundaries' are kept within these (m): nearer, a boundary is as deep
#: as it gets; from the far band on nothing is deep.
D_REF_MIN = 1.5
D_REF_MAX = FAR_M
#: Boundaries deeper than this share of their distance are clear ones: the nearest of them tell where the
#: picture's foreground is, the deepest how deep its boundaries get.
D_REF_GAP = 0.05
D_REF_PERCENTILE = 5.0
DEEPEST_PERCENTILE = 95.0
#: Beyond this many foregrounds off a boundary counts less: × (FADE_FROM × foreground / distance).
FADE_FROM = 2.0
#: Width = W_MAX × depth^GAMMA (the square root: a boundary a quarter as deep gets half the width, so the middle
#: depths keep some weight, as a pen's three or four sizes).
GAMMA = 0.5
#: A boundary pixel with fewer than this many boundary pixels in the 5 × 5 round it is a speck (a face smaller
#: than a pixel), not a line.
SPECK_UNDER = 4
#: Where the lines have thinned out (far beyond the foreground), a standing thing's lit faces are at least this
#: dense a tone: its shape reads against the white ground and sky without a line round it.
MID_TONE = 0.18

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


def line_fade(z: np.ndarray, thing: np.ndarray, d_ref: float) -> np.ndarray:
    """How much a boundary's depth counts at each pixel's distance: 1 up to FADE_FROM foregrounds off, then less as
    the distance grows (0 on the sky)."""
    return np.where(thing, np.minimum(1.0, FADE_FROM * d_ref / np.maximum(z, 1e-3)), 0.0).astype(np.float32)


def tone_floor(z: np.ndarray, standing: np.ndarray, d_ref: float) -> np.ndarray:
    """The least tone density each pixel should show: where the lines have thinned out with distance, a standing
    thing (`standing`: not the ground, a floor or a roof's top, not the far band's layers) gets up to MID_TONE, so
    its shape is told by its tone against the white round it; 0 elsewhere."""
    return np.where(standing, MID_TONE * (1.0 - line_fade(z, standing, d_ref)), 0.0).astype(np.float32)


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
    depth = np.minimum(1.0, gap * deepest) * line_fade(z, thing, d_ref)
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


def widths(depth: np.ndarray, px_per_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """Each boundary pixel's line width in pixels (0: no line), and how black it is drawn (1, or paler as the width
    comes down from W_FULL_MM to W_MIN_MM)."""
    mm = W_MAX_MM * np.power(depth, GAMMA, dtype=np.float32)
    black = np.clip((mm - W_MIN_MM) / (W_FULL_MM - W_MIN_MM), 0.0, 1.0).astype(np.float32)
    return np.where(black > 0, mm * px_per_mm, 0.0).astype(np.float32), black


def stroke(width: np.ndarray, black: np.ndarray | None = None) -> np.ndarray:
    """The ink (0–1) of lines `width` pixels wide centred on the pixels where width > 0: round, their edges
    smooth, a line thinner than a pixel drawn as a paler one; `black`: how black each line pixel's line is."""
    if black is None:
        black = np.ones(width.shape, dtype=np.float32)
    half = width / 2.0
    # A line thinner than a pixel covers that share of its pixel.
    ink = np.where((width > 0) & (width < 1), width * black, 0.0).astype(np.float32)
    wide = width >= 1
    v = np.where(wide, half, -np.inf).astype(np.float32)
    top = float(half.max()) if half.size else 0.0
    if top >= 0.5:
        # Each pixel's best (half width − distance) over the line pixels round it (a chamfer: 1 along the rows and
        # columns, √2 across), so a line is as wide as its own boundary is deep; and that line's blackness with it.
        shade = np.where(wide, black, 0.0).astype(np.float32)
        steps = [(dy, dx, np.float32(1.0)) for dy, dx in _SHIFTS]
        steps += [(dy, dx, np.float32(math.sqrt(2.0))) for dy, dx in ((1, 1), (1, -1), (-1, 1), (-1, -1))]
        h, w = width.shape
        for _ in range(int(math.ceil(top + 0.5))):
            best, best_shade = v.copy(), shade.copy()
            for dy, dx, cost in steps:
                to = (slice(max(-dy, 0), h - max(dy, 0)), slice(max(-dx, 0), w - max(dx, 0)))
                frm = (slice(max(dy, 0), h - max(-dy, 0)), slice(max(dx, 0), w - max(-dx, 0)))
                reached = v[frm] - cost
                better = reached > best[to]
                np.copyto(best[to], reached, where=better)
                np.copyto(best_shade[to], shade[frm], where=better)
            v, shade = best, best_shade
        ink = np.maximum(ink, np.clip(v + 0.5, 0.0, 1.0) * shade)
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
    flat: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """The lines' ink (0–1) at the picture's size, from passes drawn `by` times as large; and what was measured
    (the foreground distance, the deepest boundaries' distance, the share of the picture inked and the lines'
    widths, by band). `flat`: surfaces that get no lines of their own (the far band's layers: flat tones)."""
    lined = thing if flat is None else thing & ~flat
    if d_ref is None or deepest is None:
        # The picture's scales from the things that are lined (a backdrop's skyline is not its foreground).
        found = boundary_depths(z, lined)[1:]
        d_ref = found[0] if d_ref is None else d_ref
        deepest = found[1] if deepest is None else deepest
    depth, d_ref, deepest = boundary_depths(z, thing, normal, soft, d_ref, deepest)
    if flat is not None:
        depth[flat] = 0.0
    width, black = widths(depth, px_per_mm * by)
    drawn = stroke(width, black)
    info = {
        "foregroundM": round(d_ref, 2),
        "deepestM": round(deepest, 2),
        "inkShare": round(float(drawn.mean()), 4),
        "bands": bands_report(width, black, z, thing),
        "widthsMm": widths_report(width / (px_per_mm * by), z),
    }
    return shrink(drawn, by), info


def _bands() -> dict:
    return {"near": (0.0, NEAR_M), "middle": (NEAR_M, FAR_M), "far": (FAR_M, math.inf)}


def widths_report(mm: np.ndarray, z: np.ndarray) -> dict:
    """The lines' widths (mm: the median and the 95th percentile) in each distance band, for checking that near
    and deep boundaries get the thick lines."""
    out = {}
    for name, (lo, hi) in _bands().items():
        got = mm[(mm > 0) & (z >= lo) & (z < hi)]
        out[name] = [round(float(np.percentile(got, q)), 3) for q in (50, 95)] if got.size else None
    return out


def bands_report(width: np.ndarray, black: np.ndarray, z: np.ndarray, thing: np.ndarray) -> dict:
    """How much of each distance band is inked by its own boundaries' lines (near: up to 25 m; middle: up to 250 m;
    far: beyond): the lines' area (each boundary pixel's width × its blackness) over the band's, for checking that
    lines thin out with distance. (A near thing's line before a far backdrop is the near band's.)"""
    out = {}
    area = width * black
    for name, (lo, hi) in _bands().items():
        where = thing & (z >= lo) & (z < hi)
        out[name] = round(float(area[where].sum() / where.sum()), 4) if where.any() else None
    return out
