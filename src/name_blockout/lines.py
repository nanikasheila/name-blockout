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
foreground a boundary counts less again, by the square of its distance (the middle distance is told by tones, not
lines: a tree twice the foreground off against the sky gets half the line of one in the foreground).
So one rule gives all three: a near thing against a far wall gets a thick line; the same thing's foot on the ground
a thin one; a gatepost a few foregrounds off the finest, and a tree 200 m off against the sky none.

A line is black, and no thinner than a pen's finest (0.15 mm): a boundary too shallow for that gets no line at all
(never a paler one: a grey hair is neither a line nor a tone, and breaks into dots in print). A thing's outline
(where it stands before another surface, however little behind) is never left out near by: it gets at least the
finest line, so a stone on the ground keeps a closed outline.

Where the lines thin out, the tones take over (`tone_floor`): a standing thing in the middle distance is never left
white on a white ground.

All of it works on pictures (numpy arrays, rows from the top), with no Blender: develop.py renders the depths and
normals and calls in here.
"""

from __future__ import annotations

import math

import numpy as np

from .far import FAR_M, NEAR_M

#: The thickest line (the deepest boundary) and the thinnest (a pen's finest), in mm on the page. A boundary whose
#: depth asks for less than W_DROP_MM gets no line (it is told by the tones on its two sides); from there up to
#: W_MIN_MM it gets the finest. Every line is black.
W_MAX_MM = 0.5
W_MIN_MM = 0.15
W_DROP_MM = 0.1
#: A thing's line is no wider than this share of the thing's own width where it is drawn (a wire, an aerial's ring:
#: thinner than the line its depth asks for), and no thinner than the finest.
THIN_SHARE = 0.5
#: A piece of line shorter than this (mm on the page) and joined to no other is a fragment (one lump of a crown
#: just showing before another, a boundary flickering round what is drawn): not a line.
FRAGMENT_MM = 1.0
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
#: Beyond this many foregrounds off a boundary counts less: × (FADE_FROM × foreground / distance) ^ FADE_POWER.
FADE_FROM = 1.0
FADE_POWER = 2.0
#: Where one surface stands before another by more than this share of its distance, it is a thing's outline (not a
#: curved surface's own turn): it counts at least as a fold in the foreground, up to OUTLINE_REACH foregrounds off
#: (as far as a floor's joints are drawn: an outline matters more than a joint), then less with distance. So does
#: the edge of a soft thing (a bush on the ground: no fold, hardly a gap) against what is not soft.
OUTLINE_GAP = 0.01
OUTLINE_REACH = 4.0
#: The tones take over from the lines (tone_floor) from this many foregrounds off, evenly with distance.
TONE_FROM = 2.0
#: Width = W_MAX × depth^GAMMA (the square root: a boundary a quarter as deep gets half the width, so the middle
#: depths keep some weight, as a pen's three or four sizes).
GAMMA = 0.5
#: A fold between two faces (no depth between them), at the foreground's distance: how deep it counts (the finest
#: line). Farther off it counts less, as its distance grows.
FOLD_DEPTH = (W_MIN_MM / W_MAX_MM) ** (1.0 / GAMMA)
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
    """How much a boundary's depth counts at each pixel's distance: 1 up to FADE_FROM foregrounds off, then less by
    the distance's FADE_POWER (0 on the sky)."""
    near = np.minimum(1.0, FADE_FROM * d_ref / np.maximum(z, 1e-3))
    return np.where(thing, near**FADE_POWER, 0.0).astype(np.float32)


def tone_floor(z: np.ndarray, standing: np.ndarray, d_ref: float) -> np.ndarray:
    """The least tone density each pixel should show: where the lines have thinned out with distance, a standing
    thing (`standing`: not the ground, a floor or a roof's top, not the far band's layers) gets up to MID_TONE, so
    its shape is told by its tone against the white round it; 0 elsewhere. (From TONE_FROM foregrounds off, evenly:
    the things just behind the foreground keep their white faces.)"""
    lines_left = np.minimum(1.0, TONE_FROM * d_ref / np.maximum(z, 1e-3))
    return np.where(standing, MID_TONE * (1.0 - lines_left), 0.0).astype(np.float32)


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
    ground: np.ndarray | None = None,
) -> tuple[np.ndarray, float, float]:
    """How deep the boundary at each pixel is (0: none … 1: the deepest), marked on the boundary's near side; the
    foreground distance (`d_ref`) and the deepest boundaries' distance (`deepest`) used.

    `z`: each pixel's depth from the camera (m); `thing`: where there is a surface (not the sky); `normal`: each
    pixel's surface normal (unit, 3 values) for the folds; `soft`: surfaces whose folds are not drawn (a crown's
    lumps, a louvre's slats); `ground`: the ground's surfaces (a lot, a lawn: their far end against the sky is a
    horizon)."""
    q = np.where(thing, 1.0 / np.maximum(z, 1e-3), 0.0).astype(np.float32)
    gap = np.zeros_like(q)
    solid = np.zeros_like(q)  # the same, before things only (not before the sky)
    for dy, dx in _SHIFTS:
        behind = _shift(q, dy, dx)
        before = _shift(q, -dy, -dx)
        # A plane's 1/z runs evenly across the picture: what this pixel's surface would be one pixel on is taken
        # off, so a floor running away from the eye is no boundary.
        jump = np.where(thing, np.maximum(np.minimum(q - behind, 2 * q - before - behind), 0.0), 0.0)
        gap = np.maximum(gap, jump)
        solid = np.maximum(solid, np.where(_shift(thing, dy, dx), jump, 0.0))
    # At the picture's edge there is no pixel before to tell a surface's slope by: no boundary is marked there.
    gap[0, :] = gap[-1, :] = 0.0
    gap[:, 0] = gap[:, -1] = 0.0
    if d_ref is None or deepest is None:
        found = scales(z, thing, gap)
        d_ref = found[0] if d_ref is None else d_ref
        deepest = found[1] if deepest is None else deepest
    if ground is not None:
        # Beyond the foreground, where the ground ends against the sky is a horizon, not a thing's outline: told
        # by the white ground under the sky or the backdrop's tones, with no line.
        horizon = thing & ground & (z > TONE_FROM * d_ref)
        gap = np.where(horizon, solid, gap)
    depth = np.minimum(1.0, gap * deepest) * line_fade(z, thing, d_ref)
    # A thing's outline, however shallow: at least the finest line, up to OUTLINE_REACH foregrounds off.
    outline = thing & (gap * np.maximum(z, 1e-3) > OUTLINE_GAP)
    if soft is not None:
        # A soft thing (a crown, a bush) has no folds to end it: where it meets what is not soft (the ground it
        # sits on, the wall behind it, the sky) is its outline, unless that other surface stands before it.
        bush = thing & soft
        for dy, dx in _SHIFTS:
            other = _shift(q, dy, dx)
            outline |= bush & ~_shift(bush, dy, dx) & ((other - q) * np.maximum(z, 1e-3) <= OUTLINE_GAP)
    depth = np.maximum(depth, np.where(outline, FOLD_DEPTH * np.minimum(1.0, q * d_ref * OUTLINE_REACH), 0.0))
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
    """Each boundary pixel's line width in pixels (0: no line): as its depth asks, no thinner than the finest, and
    none where the depth asks for under W_DROP_MM."""
    mm = W_MAX_MM * np.power(depth, GAMMA, dtype=np.float32)
    return np.where(mm >= W_DROP_MM, np.maximum(mm, W_MIN_MM) * px_per_mm, 0.0).astype(np.float32)


def thickness(z: np.ndarray, thing: np.ndarray, reach: int) -> np.ndarray:
    """How many pixels wide the surface at each pixel is, across the rows or down the columns (the narrower), counted
    up to `reach` each way (2 × reach + 1: that wide or wider). One surface runs on while its distance changes by
    under D_REF_GAP from pixel to pixel; a thing going off the picture's edge is taken to go on."""
    q = np.where(thing, 1.0 / np.maximum(z, 1e-3), 0.0).astype(np.float32)
    best = np.full(q.shape, np.inf, dtype=np.float32)
    for dy, dx in ((0, 1), (1, 0)):
        run = np.ones(q.shape, dtype=np.float32)
        for sy, sx in ((dy, dx), (-dy, -dx)):
            other = _shift(q, sy, sx)
            link = thing & _shift(thing, sy, sx) & (np.abs(q - other) <= D_REF_GAP * np.maximum(q, other))
            alive = link
            for k in range(1, reach + 1):
                run += alive
                if k < reach:
                    alive = alive & _shift(link, sy * k, sx * k)
        best = np.minimum(best, run)
    return best


def no_wider_than_the_thing(width: np.ndarray, z: np.ndarray, thing: np.ndarray, finest: float) -> np.ndarray:
    """The widths, each no more than THIN_SHARE of its thing's own width there (and no less than `finest`, the
    finest line in pixels): a wire or an aerial's ring is not drawn thicker than it is."""
    top = float(width.max()) if width.size else 0.0
    if top <= finest:
        return width
    wide = thickness(z, thing, int(math.ceil(top / THIN_SHARE)))
    return np.where(width > 0, np.minimum(width, np.maximum(finest, THIN_SHARE * wide)), 0.0).astype(np.float32)


def fragments(mask: np.ndarray, under: int) -> np.ndarray:
    """Where `mask`'s pieces (pixels joined side to side or corner to corner) have fewer than `under` pixels."""
    h, w = mask.shape
    if under <= 1 or not mask.any():
        return np.zeros((h, w), dtype=bool)
    label = np.where(mask, np.arange(1, h * w + 1, dtype=np.int32).reshape(h, w), 0)

    def round_it(a: np.ndarray, pick) -> np.ndarray:
        rows = a.copy()
        pick(rows[:, 1:], a[:, :-1], out=rows[:, 1:])
        pick(rows[:, :-1], a[:, 1:], out=rows[:, :-1])
        both = rows.copy()
        pick(both[1:], rows[:-1], out=both[1:])
        pick(both[:-1], rows[1:], out=both[:-1])
        return both

    # Each pixel takes the largest number within `under` steps along its piece: a piece smaller than that ends up
    # with one number all over; a larger one is still changing somewhere, and is no fragment whatever its counts.
    for _ in range(under):
        label = np.where(mask, round_it(label, np.maximum), 0)
    lowest = round_it(np.where(mask, label, np.iinfo(np.int32).max), np.minimum)
    unsettled = mask & ((round_it(label, np.maximum) != label) | (lowest != label))
    still = np.zeros(h * w + 2, dtype=bool)
    still[label[unsettled]] = True
    counts = np.bincount(label.ravel(), minlength=h * w + 2)
    return mask & (counts[label] < under) & ~still[label]


def stroke(width: np.ndarray) -> np.ndarray:
    """The ink (0–1) of black lines `width` pixels wide centred on the pixels where width > 0: round, their edges
    smooth; a line thinner than a pixel covers that share of its pixel (the picture is too coarse for it)."""
    half = width / 2.0
    ink = np.where((width > 0) & (width < 1), width, 0.0).astype(np.float32)
    wide = width >= 1
    v = np.where(wide, half, -np.inf).astype(np.float32)
    top = float(half.max()) if half.size else 0.0
    if top >= 0.5:
        # Each pixel's best (half width − distance) over the line pixels round it (a chamfer: 1 along the rows and
        # columns, √2 across), so a line is as wide as its own boundary is deep.
        steps = [(dy, dx, np.float32(1.0)) for dy, dx in _SHIFTS]
        steps += [(dy, dx, np.float32(math.sqrt(2.0))) for dy, dx in ((1, 1), (1, -1), (-1, 1), (-1, -1))]
        h, w = width.shape
        for _ in range(int(math.ceil(top + 0.5))):
            best = v.copy()
            for dy, dx, cost in steps:
                to = (slice(max(-dy, 0), h - max(dy, 0)), slice(max(-dx, 0), w - max(dx, 0)))
                frm = (slice(max(dy, 0), h - max(-dy, 0)), slice(max(dx, 0), w - max(-dx, 0)))
                np.maximum(best[to], v[frm] - cost, out=best[to])
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
    flat: np.ndarray | None = None,
    ground: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """The lines' ink (0–1) at the picture's size, from passes drawn `by` times as large; and what was measured
    (the foreground distance, the deepest boundaries' distance, the share of the picture inked and the lines'
    widths, by band). `flat`: surfaces that get no lines of their own (the far band's layers: flat tones);
    `ground`: the ground's surfaces (no line where they end against the sky far off)."""
    lined = thing if flat is None else thing & ~flat
    if d_ref is None or deepest is None:
        # The picture's scales from the things that are lined (a backdrop's skyline is not its foreground).
        found = boundary_depths(z, lined, ground=ground)[1:]
        d_ref = found[0] if d_ref is None else d_ref
        deepest = found[1] if deepest is None else deepest
    depth, d_ref, deepest = boundary_depths(z, thing, normal, soft, d_ref, deepest, ground)
    if flat is not None:
        depth[flat] = 0.0
    width = widths(depth, px_per_mm * by)
    width = no_wider_than_the_thing(width, z, thing, W_MIN_MM * px_per_mm * by)
    width[fragments(width > 0, int(round(FRAGMENT_MM * px_per_mm * by)))] = 0.0
    drawn = stroke(width)
    info = {
        "foregroundM": round(d_ref, 2),
        "deepestM": round(deepest, 2),
        "inkShare": round(float(drawn.mean()), 4),
        "bands": bands_report(width, z, thing),
        "widthsMm": widths_report(width / (px_per_mm * by), z),
    }
    return shrink(drawn, by), info


#: A distance band with under this share of the picture in it is left out of the reports.
BAND_MIN_SHARE = 0.002


def _bands() -> dict:
    return {"near": (0.0, NEAR_M), "middle": (NEAR_M, FAR_M), "far": (FAR_M, math.inf)}


def widths_report(mm: np.ndarray, z: np.ndarray) -> dict:
    """The lines' widths (mm: the median and the 95th percentile) in each distance band, for checking that near
    and deep boundaries get the thick lines."""
    out = {}
    for name, (lo, hi) in _bands().items():
        band = (z >= lo) & (z < hi)
        got = mm[(mm > 0) & band]
        out[name] = [round(float(np.percentile(got, q)), 3) for q in (50, 95)] if got.size and band.mean() >= BAND_MIN_SHARE else None
    return out


def bands_report(width: np.ndarray, z: np.ndarray, thing: np.ndarray) -> dict:
    """How much of each distance band is inked by its own boundaries' lines (near: up to 25 m; middle: up to 250 m;
    far: beyond): the lines' area (each boundary pixel's width) over the band's, for checking that lines thin out
    with distance. (A near thing's line before a far backdrop is the near band's.)"""
    out = {}
    area = width
    for name, (lo, hi) in _bands().items():
        where = thing & (z >= lo) & (z < hi)
        # A band with next to nothing in it (a sliver at the picture's edge) tells nothing.
        out[name] = round(min(1.0, float(area[where].sum() / where.sum())), 4) if where.mean() >= BAND_MIN_SHARE else None
    return out
