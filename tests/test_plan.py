# SPDX-License-Identifier: GPL-3.0-or-later
"""The Blockout plan: boxes fill what was marked, figures stand where drawn, the ground reaches them."""

import json
from pathlib import Path

from name_blockout.instruction import read_instruction
from name_blockout.plan import build_plan

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "two-point" / "指示.json"


def plan():
    data = read_instruction(EXAMPLE)
    return build_plan(data, data["shots"][0], EXAMPLE)


def test_boxes_fill_their_ranges():
    p = plan()
    for obj in p["objects"]:
        assert obj["placed"]["iou"] > 0.98, obj


def test_box_for_the_second_point_runs_along_its_axis():
    p = plan()
    by_id = {o["id"]: o for o in p["objects"]}
    assert by_id["o1"]["placed"]["along"] == "X" and by_id["o2"]["placed"]["along"] == "Y"


def test_figure_feet_where_drawn():
    p = plan()
    fig = p["figures"][0]["placed"]
    assert abs(fig["boxPx"][3] - fig["targetPx"][3]) < 2


def test_ground_reaches_the_farthest_thing():
    p = plan()
    reach = max(max(abs(o["placed"]["centreM"][0]), abs(o["placed"]["centreM"][1])) for o in p["objects"])
    rings = p["ground"]["rings"]
    assert rings[-1]["extentM"] >= reach
    assert all(b["spacingM"] == 4 * a["spacingM"] for a, b in zip(rings, rings[1:]))
    # Each ring ends on the next ring's cells, so no faces overlap (Freestyle warns of edges twice).
    assert all(abs(a["extentM"] / b["spacingM"] - round(a["extentM"] / b["spacingM"])) < 1e-9 for a, b in zip(rings, rings[1:]))


def test_plan_is_json_and_deterministic():
    a, b = plan(), plan()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_usual_size_keeps_a_sofa_a_sofa():
    data = read_instruction(EXAMPLE)
    shot = data["shots"][0]
    shot["objects"][1]["label"] = "ソファ"
    p = build_plan(data, shot, EXAMPLE)
    w, d, h = next(o for o in p["objects"] if o["id"] == "o2")["placed"]["sizeM"]
    assert 0.25 < h / w < 0.8
