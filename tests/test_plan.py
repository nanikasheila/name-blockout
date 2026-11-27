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


def test_a_building_looked_up_at_keeps_a_building_s_size():
    """Its range ends above the eye level (the foot is not in it): the usual size says how far it stands, instead
    of the range's bottom pushing it kilometres off and making it kilometres tall."""
    path = EXAMPLE.parents[1] / "three-point" / "指示.json"
    data = read_instruction(path)
    p = build_plan(data, data["shots"][0], path)
    tower = p["objects"][0]
    assert tower["footless"] and 20 < tower["placed"]["sizeM"][2] < 45 and tower["distanceM"] < 60, tower
    assert tower["placed"]["iou"] > 0.98
    box, target = tower["placed"]["boxPx"], tower["placed"]["targetPx"]
    assert all(abs(a - b) < 8 for a, b in zip(box[:3], target[:3])) and box[3] > target[3]
    assert any("足もとがコマに出ていない" in n for n in p["notes"])


def test_a_development_is_drawn_at_300_dpi_whatever_the_instruction_s_dpi():
    """A name written out at 150 dpi: the Blockout's preview keeps to it, the development draws its box at 300 dpi
    (a 0.1 mm line is under a pixel at 150) and says so; the targets stay in the instruction's pixels."""
    from name_blockout.plan import build_develop_plan

    data = read_instruction(EXAMPLE)
    shot = json.loads(json.dumps(data["shots"][0]))
    shot["frame"] = {**shot["frame"], "dpi": 150}
    shot["frame"].pop("sizePx", None)
    preview = build_plan(data, shot, EXAMPLE, 300)
    assert preview["render"]["dpi"] == 150
    develop = build_develop_plan(data, shot, EXAMPLE)
    assert develop["frame"]["dpi"] == 150 and develop["render"]["dpi"] == 300
    assert all(abs(a - 2 * b) <= 1 for a, b in zip(develop["render"]["sizePx"], develop["frame"]["sizePx"]))
    assert develop["targets"]["sizePx"] == develop["frame"]["sizePx"]
    assert any("150" in n and "300dpi で描きます" in n for n in develop["notes"])
    # At the instruction's own dpi or under it nothing is said.
    assert not any("dpi で描きます" in n for n in build_develop_plan(data, data["shots"][0], EXAMPLE)["notes"])
