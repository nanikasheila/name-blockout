# SPDX-License-Identifier: GPL-3.0-or-later
"""The development's lines: as thick as their boundary is deep."""

import numpy as np

from name_blockout.lines import W_MAX_MM, boundary_depths, boundary_lines, stroke, widths


def _scene(h=60, w=120):
    """A wall 20 m off; before it a box 4 m off (left) and a box 12 m off (right); a floor running away below."""
    z = np.full((h, w), 20.0, dtype=np.float32)
    thing = np.ones((h, w), dtype=bool)
    normal = np.zeros((h, w, 3), dtype=np.float32)
    normal[..., 1] = -1.0  # facing the camera
    z[10:40, 10:40] = 4.0
    z[10:40, 70:100] = 12.0
    # The floor: 1/z even down the rows (a plane), from the wall's 20 m to 2 m at the bottom.
    rows = np.arange(45, h)
    q = np.linspace(1 / 20.0, 1 / 2.0, len(rows), dtype=np.float32)
    z[45:] = (1.0 / q)[:, None]
    normal[45:] = (0.0, 0.0, 1.0)
    return z, thing, normal


def test_a_deeper_boundary_gets_a_thicker_line():
    z, thing, normal = _scene()
    depth, *_ = boundary_depths(z, thing, None, None, d_ref=4.0, deepest=4.0)
    near, mid = depth[20, 10], depth[20, 70]
    assert near > mid > 0  # 4 m before 20 m is deeper than 12 m before 20 m
    assert abs(near - (1 / 4 - 1 / 20) * 4) < 1e-3 and abs(mid - (1 / 12 - 1 / 20) * 4) < 1e-3
    assert depth[20, 9] == 0 and depth[20, 25] == 0  # the far side of the boundary, and inside the box
    w = widths(depth, 600 / 25.4)
    assert w[20, 10] > 3 * w[20, 70]


def test_a_floor_running_away_is_no_boundary_and_the_sky_is_the_deepest():
    z, thing, normal = _scene()
    depth, *_ = boundary_depths(z, thing, None, None, d_ref=4.0, deepest=4.0)
    assert depth[46:, 5].max() < 0.01  # the floor's own slope
    thing[:10] = False  # the sky over the wall
    z[10:40, 10:40] = 4.0
    thing[5:40, 10:40] = True
    z[5:40, 10:40] = 4.0  # the near box stands up into the sky
    depth, *_ = boundary_depths(z, thing, None, None, d_ref=4.0, deepest=4.0)
    assert depth[5, 20] == 1.0  # a foreground thing against the sky
    assert depth[9, 60] < 0.25  # the wall 20 m off against the sky: shallow, seen from a 4 m foreground


def test_far_things_get_almost_no_line():
    h, w = 40, 80
    z = np.full((h, w), 1.0, dtype=np.float32)
    thing = np.zeros((h, w), dtype=bool)
    thing[10:30, 10:30] = True
    z[10:30, 10:30] = 200.0  # a tree 200 m off against the sky
    thing[10:30, 50:70] = True
    z[10:30, 50:70] = 5.0  # a thing 5 m off
    ink, info = boundary_lines(z, thing, None, None, 600 / 25.4, d_ref=5.0, deepest=5.0)
    assert ink[10, 20] == 0.0 and ink[10, 60] == 1.0
    assert info["bands"]["far"] == 0.0 and info["bands"]["near"] > 0.1


def test_a_fold_is_a_thin_line_that_fades_with_distance():
    z, thing, normal = _scene()
    depth, *_ = boundary_depths(z, thing, normal, None, d_ref=4.0, deepest=4.0)
    # The wall's foot on the floor: a fold, no depth; thin beside the near box's outline.
    foot = depth[44, 55]
    assert 0 < foot < 0.1 and foot < depth[20, 10] / 5
    # A speck (one pixel of another normal: a face smaller than a pixel) is no line.
    speck = normal.copy()
    speck[50, 60] = (1.0, 0.0, 0.0)
    assert boundary_depths(z, thing, speck, None, d_ref=4.0, deepest=4.0)[0][48:53, 58:63].max() == 0
    # The same fold seen nearer counts more.
    z2 = z / 5.0
    assert boundary_depths(z2, thing, normal, None, d_ref=4.0, deepest=4.0)[0][44, 55] > 3 * foot
    # A soft surface (a crown) has no folds drawn.
    soft = np.zeros(thing.shape, dtype=bool)
    soft[40:50] = True
    assert boundary_depths(z, thing, normal, soft, d_ref=4.0, deepest=4.0)[0][44, 55] == 0


def test_stroke_widths_round_and_smooth():
    width = np.zeros((41, 41), dtype=np.float32)
    width[20, 5:36] = 7.0  # a line 7 px wide
    ink = stroke(width)
    column = ink[:, 20]
    assert 6.0 <= column.sum() <= 8.0 and column[20] == 1.0 and column[10] == 0.0
    thin = np.zeros((9, 9), dtype=np.float32)
    thin[4, :] = 0.4
    assert abs(stroke(thin)[4, 4] - 0.4) < 1e-6 and stroke(thin)[3, 4] == 0.0
    assert W_MAX_MM > 0


def test_the_foreground_is_found_from_the_nearest_clear_boundaries():
    z, thing, normal = _scene()
    _, d_ref, deepest = boundary_depths(z, thing, normal, None)
    assert 3.5 <= d_ref <= 4.5
    # The deepest boundaries here: the near box before the wall (1/4 − 1/20: as a thing 5 m off against the sky).
    assert 4.5 <= deepest <= 5.5


def test_a_room_s_deepest_boundary_is_as_thick_as_a_lot_s():
    """Indoors nothing stands against the sky: the sofa before its wall is the picture's deepest boundary, and gets
    the thick line; a far-off picture's deepest boundary does not (nothing is deep beyond the near band)."""
    z = np.full((40, 80), 6.0, dtype=np.float32)
    thing = np.ones((40, 80), dtype=bool)
    z[10:30, 20:60] = 4.5
    depth, _, deepest = boundary_depths(z, thing)
    assert depth[10, 40] > 0.9
    depth, _, deepest = boundary_depths(z * 100, thing)
    assert deepest == 25.0 and depth[10, 40] < 0.05
