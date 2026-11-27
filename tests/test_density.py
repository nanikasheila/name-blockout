# SPDX-License-Identifier: GPL-3.0-or-later
"""How much is drawn, in numbers: a take beside its reference."""

import numpy as np

from name_blockout.density import FAIL_UNDER, cell_name, compare, emptiest_cells, grey, measure, shrink


def _picture(h=90, w=150, black=(), tone=()):
    """White paper with black boxes and grey boxes (y0, y1, x0, x1)."""
    p = np.ones((h, w, 4), dtype=np.float32)
    for y0, y1, x0, x1 in tone:
        p[y0:y1, x0:x1, :3] = 0.6
    for y0, y1, x0, x1 in black:
        p[y0:y1, x0:x1, :3] = 0.0
    return p


def test_shares_of_black_tone_and_paper():
    m = measure(grey(_picture(black=[(0, 30, 0, 50)], tone=[(60, 90, 100, 150)])))
    assert abs(m["dark"] - 1 / 9) < 1e-3 and abs(m["tone"] - 1 / 9) < 1e-3 and abs(m["white"] - 7 / 9) < 1e-3
    assert m["grid"]["dark"][0][0] == 1.0 and m["grid"]["dark"][2][2] == 0.0
    assert m["grid"]["tone"][2][2] == 1.0
    assert cell_name(2, 0) == "下段・左"


def test_a_transparent_picture_is_read_on_white_paper():
    p = np.zeros((10, 10, 4), dtype=np.float32)  # nothing drawn: black pixels with no alpha
    assert measure(grey(p))["white"] == 1.0


def test_shrinking_keeps_the_mean():
    p = np.random.default_rng(1).random((77, 131)).astype(np.float32)
    small = shrink(p, 20, 30)
    assert small.shape == (20, 30) and abs(float(small.mean()) - float(p.mean())) < 0.01
    assert shrink(p, 200, 300).shape == p.shape  # never larger


def test_a_take_as_dense_as_its_reference_passes():
    reference = _picture(black=[(0, 30, 0, 50), (60, 90, 100, 150)])
    result = compare(reference.copy(), reference)
    assert result["pass"] and result["ratios"]["dark"] == 1.0 and not result["tooEmpty"]


def test_an_empty_corner_is_named():
    reference = _picture(black=[(0, 30, 0, 50), (60, 90, 100, 150)])
    take = _picture(black=[(0, 30, 0, 50), (60, 90, 100, 110)])  # the bottom right a fifth as black
    result = compare(take, reference)
    assert not result["pass"]
    names = [f["where"] for f in result["tooEmpty"]]
    assert "下段・右" in names and "全体" in names
    assert all(f["ratio"] < FAIL_UNDER for f in result["tooEmpty"])
    assert emptiest_cells(result) == [(2, 2)]


def test_pictures_of_different_sizes_are_compared_at_the_same_width():
    reference = _picture(h=180, w=300, black=[(0, 60, 0, 100)])
    take = _picture(h=90, w=150, black=[(0, 30, 0, 50)])
    result = compare(take, reference)
    assert result["comparedAtPx"] == 150 and result["sameFraming"] and result["pass"]


def test_cells_are_not_compared_across_different_framings():
    reference = _picture(h=150, w=150, black=[(100, 150, 100, 150)])
    take = _picture(h=90, w=150)
    result = compare(take, reference)
    assert not result["sameFraming"]
    assert [f["where"] for f in result["tooEmpty"]] == ["全体"]
