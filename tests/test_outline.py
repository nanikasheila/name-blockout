# SPDX-License-Identifier: GPL-3.0-or-later
"""A mesh from straight above as its true outline, and cut at a height (synthetic meshes)."""

import numpy as np

from name_blockout.outline import MIN_CELL, cell_for, raster, rings_area, section, silhouette


def _box(x0, y0, x1, y1, z0=0.0, z1=1.0):
    verts = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    quads = [(0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]
    tris = [t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))]
    return np.array(verts, dtype=float), np.array(tris)


def _join(*meshes):
    verts, tris, n = [], [], 0
    for v, t in meshes:
        verts.append(v)
        tris.append(t + n)
        n += len(v)
    return np.vstack(verts), np.vstack(tris)


def test_an_l_shaped_house_stays_an_l():
    v, t = _join(_box(0, 0, 6, 2), _box(0, 2, 2, 5))
    rings = silhouette(v[:, :2], t)
    assert len(rings) == 1 and len(rings[0]) == 6
    # 18 m², not the 21 m² a convex outline would wrap; within the grid's cell along its edge.
    assert abs(rings_area(rings) - 18.0) < 22 * MIN_CELL


def test_each_tree_is_its_own_ring_and_a_courtyard_is_a_hole():
    v, t = _join(_box(0, 0, 1, 1), _box(3, 0, 4, 1), _box(10, 10, 10.05, 10.05))
    rings = silhouette(v[:, :2], t)
    assert len(rings) == 2  # the speck is left out
    xs = sorted(min(q[0] for q in ring) for ring in rings)
    assert abs(xs[0]) < 0.06 and abs(xs[1] - 3.0) < 0.06
    v, t = _join(_box(0, 0, 4, 0.2), _box(0, 3.8, 4, 4), _box(0, 0, 0.2, 4), _box(3.8, 0, 4, 4))
    outer, hole = silhouette(v[:, :2], t)
    assert rings_area([outer]) > 15 and rings_area([hole]) < -11  # the hole runs the other way
    assert 3.04 <= rings_area([outer, hole]) < 3.04 + 1.2  # walls 20 cm thick, a cell more on the drawing


def test_a_turned_box_is_a_few_points_and_a_sliver_is_not_lost():
    a = np.radians(30)
    turn = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    v, t = _box(0, 0, 6, 3)
    rings = silhouette(v[:, :2] @ turn.T, t)
    assert len(rings) == 1 and len(rings[0]) <= 12 and abs(rings_area(rings) - 18.0) < 1.5
    # A wall 1 cm thick and 5 m long: thinner than a cell, still drawn.
    v, t = _box(0, 0, 5, 0.01)
    mask, _ = raster(v[:, :2], t, MIN_CELL)
    assert mask.sum() >= 100
    assert len(silhouette(v[:, :2], t)) == 1


def test_a_large_thing_gets_a_coarser_grid():
    v, _ = _box(-100, -100, 100, 100)
    assert cell_for(v[:, :2]) == 0.5
    v, _ = _box(0, 0, 2, 1)
    assert cell_for(v[:, :2]) == MIN_CELL


def test_a_cut_gives_the_walls():
    v, t = _box(1, 2, 5, 2.2, 0.0, 2.6)
    lines = section(v, t, 1.2)
    assert len(lines) == 1 and lines[0][0] == lines[0][-1]  # one closed line around the wall
    xs, ys = [q[0] for q in lines[0]], [q[1] for q in lines[0]]
    assert (min(xs), max(xs), min(ys), max(ys)) == (1.0, 5.0, 2.0, 2.2)
    assert section(v, t, 3.0) == [] and section(v, t, -0.5) == []
    # A table under the cut is not cut; a cupboard through it is.
    table, _ = _box(0, 0, 1, 1, 0.0, 0.7)
    assert section(table, t, 1.2) == []
