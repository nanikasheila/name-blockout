"""The marks that say what a white ground is made of (groundmarks.py): Blender-free, from the picture's passes."""

from __future__ import annotations

import math

import numpy as np

from name_blockout.groundmarks import BLADE_MM, GAP_MM, KIND_CODES, NEAR_SPOT, counts, draw, spots

PX_PER_MM = 300 / 25.4


def passes(cam=(0.0, -30.0, 12.0), pitch=25.0, w=1200, h=700, f=1300.0):
    """A flat ground (z = 0) seen from `cam`, looking along +Y and down by `pitch`: where each pixel's ground lies
    (x, y), how far off along the view, and whether it shows ground at all."""
    p = math.radians(pitch)
    cols, rows = np.meshgrid(np.arange(w) - w / 2 + 0.5, np.arange(h) - h / 2 + 0.5)
    dy = f * math.cos(p) - rows * math.sin(p)
    dz = -f * math.sin(p) - rows * math.cos(p)
    t = np.where(dz < 0, -cam[2] / np.minimum(dz, -1e-9), np.inf)
    seen = np.isfinite(t) & (t * f < 5000)
    x, y = np.where(seen, cam[0] + t * cols, 0.0), np.where(seen, cam[1] + t * dy, 0.0)
    return x, y, np.where(seen, t * f, 0.0), seen


def lawn_soil_paving(x, y, seen):
    """A lawn left of x = 0, bare soil right of it beyond y = 10, paving before that."""
    kind = np.where(seen & (x < 0), KIND_CODES["草"], 0.0)
    return np.where(seen & (x >= 0) & (y > 10), KIND_CODES["土"], kind)


def test_marks_stand_sparse_on_a_lawn_and_soil_and_nowhere_else():
    x, y, distance, seen = passes()
    kind = lawn_soil_paving(x, y, seen)
    marks = spots(kind, x, y, distance, PX_PER_MM, 80.0)
    assert {m["kind"] for m in marks} == {"草", "土"}
    for m in marks:
        c, r = m["px"]
        assert abs(kind[r, c] - KIND_CODES[m["kind"]]) < 0.01  # on its own ground, never on the paving
        assert 0 < m["distanceM"] <= 80.0
        # …at its cell's spot of the place (the nearest pixel to it).
        size = 0.9 * 2 ** m["cell"][0]
        assert math.hypot(x[r, c] - m["atM"][0], y[r, c] - m["atM"][1]) < NEAR_SPOT * size
    # Sparse: a mark's nearest neighbour is about a gap off on the paper (cells of two sizes meet here and there).
    at = np.array([m["px"] for m in marks if m["kind"] == "草"], dtype=float)
    assert len(at) > 20
    off = np.hypot(at[:, None, 0] - at[None, :, 0], at[:, None, 1] - at[None, :, 1]) + np.eye(len(at)) * 1e9
    gap = GAP_MM * PX_PER_MM
    assert off.min() > 0.4 * gap and np.median(off.min(axis=1)) > 0.8 * gap
    # The same passes give the same marks.
    assert spots(kind, x, y, distance, PX_PER_MM, 80.0) == marks


def test_marks_end_with_the_texture_and_keep_off_what_is_laid_over_the_ground():
    x, y, distance, seen = passes()
    kind = lawn_soil_paving(x, y, seen)
    far = max(m["distanceM"] for m in spots(kind, x, y, distance, PX_PER_MM, 80.0))
    near = spots(kind, x, y, distance, PX_PER_MM, 30.0)
    assert near and far > 40.0 and max(m["distanceM"] for m in near) <= 30.0
    # A street laid over the lawn (x −12 to −6): none on it, the rest as before.
    street = (x > -12.0) & (x < -6.0)
    kept = spots(kind, x, y, distance, PX_PER_MM, 80.0, skip=street)
    assert kept and not any(-12.0 < x[r, c] < -6.0 for (c, r) in (m["px"] for m in kept))
    # No ground to mark: no marks.
    assert spots(np.zeros_like(kind), x, y, distance, PX_PER_MM, 80.0) == []


def test_marks_belong_to_the_place_not_to_the_camera():
    """From a camera a little to the side, a cell that carries a mark carries it at the same spot of the lawn."""
    a = passes()
    b = passes(cam=(4.0, -31.0, 12.0))
    one = {m["cell"]: m["atM"] for m in spots(lawn_soil_paving(a[0], a[1], a[3]), a[0], a[1], a[2], PX_PER_MM, 80.0)}
    two = {m["cell"]: m["atM"] for m in spots(lawn_soil_paving(b[0], b[1], b[3]), b[0], b[1], b[2], PX_PER_MM, 80.0)}
    shared = set(one) & set(two)
    assert len(shared) > 10 and all(one[c] == two[c] for c in shared)


def test_a_mark_is_a_few_strokes_of_the_finest_pen_and_none_runs_over_a_thing():
    x, y, distance, seen = passes()
    kind = lawn_soil_paving(x, y, seen)
    marks = spots(kind, x, y, distance, PX_PER_MM, 80.0)
    on = kind > 0.05
    # A thing stands on the lawn (a box's pixels are no ground): the marks by its foot are left out.
    c, r = next(m["px"] for m in marks if m["kind"] == "草")
    on[r - 14 : r - 2, c - 30 : c + 30] = False
    ink = draw(marks, on, PX_PER_MM, 0.15)
    drawn = [m for m in marks if m.get("drawn")]
    assert 0 < len(drawn) < len(marks)
    assert ink.max() == 1.0 and ink[~on].max() < 0.99  # a stroke's centre never lies off the ground
    # Black strokes, a pen's width: little ink, and none taller than a tuft may be on the paper.
    assert 0.0005 < (ink > 0.5).mean() < 0.01
    rows = np.nonzero((ink > 0.5).any(axis=1))[0]
    runs = np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1)
    assert max(len(run) for run in runs) < 4 * BLADE_MM[1] * PX_PER_MM  # tufts on neighbouring rows may touch
    said = counts(marks)
    assert said["草"]["marks"] == sum(1 for m in drawn if m["kind"] == "草") and said["草"]["fromM"] < said["草"]["toM"]
    # The same marks give the same ink.
    again = spots(kind, x, y, distance, PX_PER_MM, 80.0)
    assert np.array_equal(draw(again, on, PX_PER_MM, 0.15), ink)
