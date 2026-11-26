# SPDX-License-Identifier: GPL-3.0-or-later
"""The development's lines: as thick as their boundary is deep."""

import numpy as np

from name_blockout.lines import (
    FADE_FROM,
    MID_TONE,
    W_FULL_MM,
    W_MAX_MM,
    W_MIN_MM,
    boundary_depths,
    boundary_lines,
    stroke,
    tone_floor,
    widths,
)


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
    # …and the farther box (3 foregrounds off) counts less again by its distance.
    assert abs(near - (1 / 4 - 1 / 20) * 4) < 1e-3 and abs(mid - (1 / 12 - 1 / 20) * 4 * (FADE_FROM * 4 / 12)) < 1e-3
    assert depth[20, 9] == 0 and depth[20, 25] == 0  # the far side of the boundary, and inside the box
    w, black = widths(depth, 600 / 25.4)
    # Half as deep again… the square root: over a quarter the depth gives under half the width, both full black.
    assert w[20, 10] > 1.8 * w[20, 70] > 0 and black[20, 10] == black[20, 70] == 1.0


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
    assert info["bands"]["middle"] == 0.0 and info["bands"]["near"] > 0.1
    assert info["widthsMm"]["near"][0] == W_MAX_MM and info["widthsMm"]["middle"] is None


def test_beyond_the_foreground_a_boundary_counts_less_and_tones_take_over():
    h, w = 40, 200
    z = np.full((h, w), 1.0, dtype=np.float32)
    thing = np.zeros((h, w), dtype=bool)
    for i, metres in enumerate((5.0, 10.0, 20.0, 40.0, 80.0)):  # the same post against the sky, farther and farther
        thing[10:30, 10 + 40 * i : 30 + 40 * i] = True
        z[10:30, 10 + 40 * i : 30 + 40 * i] = metres
    depth, *_ = boundary_depths(z, thing, None, None, d_ref=5.0, deepest=5.0)
    got = [float(depth[20, 10 + 40 * i]) for i in range(5)]
    # 1/distance alone up to FADE_FROM foregrounds, then again by the distance.
    assert got[0] == 1.0 and abs(got[1] - 0.5) < 1e-3 and abs(got[2] - 0.25 * FADE_FROM * 5 / 20) < 1e-3
    assert abs(got[4] - (5 / 80) * (FADE_FROM * 5 / 80)) < 1e-4
    mm, black = widths(depth, 1.0)
    assert mm[20, 10] == W_MAX_MM and W_MIN_MM < mm[20, 130] < W_FULL_MM and 0 < black[20, 130] < 1  # 40 m: a pale hair
    assert mm[20, 170] == 0  # 80 m: no line
    # …and there the tone takes over: the far post is toned, the near one left as it is; the ground never.
    floor = tone_floor(z, thing, 5.0)
    assert floor[20, 20] == 0 and abs(floor[20, 180] - MID_TONE * (1 - FADE_FROM * 5 / 80)) < 1e-4 and floor[5, 180] == 0


def test_the_far_band_s_layers_get_no_lines_and_are_not_the_foreground():
    h, w = 40, 80
    z = np.full((h, w), 1.0, dtype=np.float32)
    thing = np.zeros((h, w), dtype=bool)
    thing[10:30, 10:70] = True
    z[10:30, 10:70] = 120.0  # a skyline against the sky, alone in the picture
    flat = thing.copy()
    ink, info = boundary_lines(z, thing, None, None, 600 / 25.4, flat=flat)
    assert ink.max() == 0.0
    ink, info = boundary_lines(z, thing, None, None, 600 / 25.4)  # the same as a thing: the picture's foreground
    assert ink[10, 40] == 1.0 and info["foregroundM"] == 120.0


def test_a_fold_is_a_thin_line_that_fades_with_distance():
    z, thing, normal = _scene()
    depth, *_ = boundary_depths(z, thing, normal, None, d_ref=4.0, deepest=4.0)
    # The wall's foot on the floor: a fold, no depth; thin beside the near box's outline.
    foot = depth[44, 55]
    assert 0 < foot < 0.02 and foot < depth[20, 10] / 5
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
    # A paler line beside a black one: each keeps its own blackness across its width.
    width[30, 5:36] = 3.0
    black = np.where(width == 3.0, 0.5, 1.0).astype(np.float32)
    ink = stroke(width, black)
    assert ink[20, 20] == 1.0 and ink[22, 20] == 1.0 and ink[30, 20] == 0.5 and ink[31, 20] == 0.5


def test_the_foreground_is_found_from_the_nearest_clear_boundaries():
    z, thing, normal = _scene()
    _, d_ref, deepest = boundary_depths(z, thing, normal, None)
    assert 3.5 <= d_ref <= 4.5
    # The deepest boundaries here: the near box before the wall (1/4 − 1/20: as a thing 5 m off against the sky).
    assert 4.5 <= deepest <= 5.5


def test_a_room_s_deepest_boundary_is_as_thick_as_a_lot_s():
    """Indoors nothing stands against the sky: the sofa before its wall is the picture's deepest boundary, and gets
    the thick line; a far-off picture's deepest boundary does not (nothing is deep from the far band on)."""
    z = np.full((40, 80), 6.0, dtype=np.float32)
    thing = np.ones((40, 80), dtype=bool)
    z[10:30, 20:60] = 4.5
    depth, _, deepest = boundary_depths(z, thing)
    assert depth[10, 40] > 0.9
    # Seen from a hill the same holds (a house before the land behind it), up to the far band: there nothing is deep.
    depth, _, deepest = boundary_depths(z * 10, thing)
    assert depth[10, 40] > 0.9
    depth, _, deepest = boundary_depths(z * 1000, thing)
    assert deepest == 250.0 and depth[10, 40] < 0.01


def test_a_far_horizon_is_no_line_but_a_thing_s_top_against_the_sky_is():
    """Where the ground ends against the sky beyond the foreground no line is drawn; a thing's level top there (a
    gatepost's cap) keeps its outline, and so does the ground's end near by or before a thing."""
    h, w = 60, 120
    thing = np.zeros((h, w), dtype=bool)
    z = np.full((h, w), 1.0, dtype=np.float32)
    ground = np.zeros((h, w), dtype=bool)
    for x0, metres, is_ground in ((5, 4.0, True), (35, 40.0, True), (65, 40.0, True), (95, 40.0, False)):
        thing[20:50, x0 : x0 + 20] = True
        z[20:50, x0 : x0 + 20] = metres
        ground[20:50, x0 : x0 + 20] = is_ground
    # Behind the third: a thing still farther (a hill).
    thing[10:20, 65:85] = True
    z[10:20, 65:85] = 200.0
    depth, *_ = boundary_depths(z, thing, None, None, d_ref=4.0, deepest=40.0, ground=ground)
    assert depth[20, 15] > 0.9  # the ground's end near by
    assert depth[20, 45] == 0  # the far ground's end against the sky: a horizon
    assert depth[20, 75] > 0  # the far ground's end before the hill
    assert depth[20, 105] > 0  # a far thing's top against the sky
