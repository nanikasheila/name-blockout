# SPDX-License-Identifier: GPL-3.0-or-later
"""What lies round a place: a town from a seed, anchored to the world, and only beyond the place."""

import copy
import json
import math
from pathlib import Path

from name_blockout.camera import fit_camera
from name_blockout.checks import check_shot
from name_blockout.instruction import read_instruction, schema_problems
from name_blockout.plan import build_plan
from name_blockout.requirement import effective
from name_blockout.top import build_top, to_svg, top_words
from name_blockout.town import BLOCK_DEEP_M, REACH_M, STREET_M, beyond, place_reach, rect, seen_reach, town, town_words

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "develop" / "指示.json"


def looking_down(position=(-20.0, -22.0, 15.0), **around):
    """The develop example's shot, looked down on from a roof's height (the horizon above the panel)."""
    data = copy.deepcopy(read_instruction(EXAMPLE))
    shot = data["shots"][0]
    shot["frame"] = {"boxMm": [17, 17, 110, 77], "dpi": 150, "shapeMm": [[20, 20], [107, 20], [107, 74], [20, 74]]}
    shot["ruler"] = {"points": 2, "horizonMm": [[20, -23], [107, -23]], "vanishingMm": [[150, -23], [-40, -23]]}
    shot["camera"] = {"heightM": position[2], "positionM": list(position), "lensMm": 37}
    shot["figures"] = []
    if around:
        shot["surroundings"] = around
    return data, shot


def test_looking_down_the_picture_ends_on_the_ground():
    _, shot = looking_down()
    assert 30 < seen_reach(fit_camera(shot)) < REACH_M
    level = read_instruction(EXAMPLE)["shots"][0]
    assert seen_reach(fit_camera(level)) == REACH_M  # the horizon is in the picture


def test_the_same_seed_is_the_same_town_and_another_seed_another():
    _, shot = looking_down()
    camera = fit_camera(shot)
    a, b, c = town(camera, {"seed": 4}), town(camera, {"seed": 4}), town(camera, {"seed": 5})
    assert a == b and json.dumps(a, ensure_ascii=False)
    assert [h["centreM"] for h in a["houses"]] != [h["centreM"] for h in c["houses"]]
    assert len(a["houses"]) > 10 and a["poles"] and a["trees"]
    # Nearest first, all within reach and within what the picture looks toward.
    assert [h["distanceM"] for h in a["houses"]] == sorted(h["distanceM"] for h in a["houses"])
    assert a["houses"][-1]["distanceM"] <= a["reachM"]


def test_the_town_stays_where_it_is_when_the_camera_moves():
    """A house is the same house from another camera (the town is anchored to the world, not to the view)."""
    _, shot = looking_down()
    _, moved = looking_down(position=(-26.0, -18.0, 17.0))
    a = {h["id"]: h for h in town(fit_camera(shot), {"seed": 4})["houses"]}
    b = {h["id"]: h for h in town(fit_camera(moved), {"seed": 4})["houses"]}
    both = set(a) & set(b)
    assert len(both) > 5
    for ident in both:
        assert {k: v for k, v in a[ident].items() if k != "distanceM"} == {k: v for k, v in b[ident].items() if k != "distanceM"}


def test_houses_stand_on_their_plots_clear_of_each_other_and_of_the_streets():
    _, shot = looking_down()
    made = town(fit_camera(shot), {"seed": 4, "reachM": 150})
    boxes = [(min(x for x, _ in r), min(y for _, y in r), max(x for x, _ in r), max(y for _, y in r)) for r in map(rect, made["houses"])]
    for i, (ax0, ay0, ax1, ay1) in enumerate(boxes):
        for bx0, by0, bx1, by1 in boxes[i + 1 :]:
            assert ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0
        # A street runs along X every BLOCK_DEEP_M (its middle on the line): no house reaches into it.
        row = math.floor(ay0 / BLOCK_DEEP_M)
        assert ay0 >= row * BLOCK_DEEP_M + STREET_M / 2 and ay1 <= (row + 1) * BLOCK_DEEP_M - STREET_M / 2
    for house in made["houses"]:
        assert house["sizeM"][2] >= 3.0 and house["roof"] in ("gable", "flat") and house["front"] in ("-Y", "+Y")


def test_only_what_is_beyond_the_place_is_kept():
    _, shot = looking_down()
    camera = fit_camera(shot)
    origin = camera.position[:2]
    made = town(camera, {"seed": 4})
    place = [(x, y) for x in (-6.0, 0.0, 6.0) for y in (-2.0, 4.0, 10.0)]  # a house and its garden's things
    kept = beyond(made, place, origin)
    far = place_reach(place, origin)
    assert 0 < len(kept["houses"]) < len(made["houses"])
    assert kept["dropped"]["houses"] == len(made["houses"]) - len(kept["houses"])
    for house in kept["houses"]:
        for x, y in rect(house):
            a = int(math.floor(math.degrees(math.atan2(y - origin[1], x - origin[0])))) % 360
            if a in far:
                assert math.hypot(x - origin[0], y - origin[1]) > far[a] + STREET_M
    # Nothing on the place's own ground either, however far it goes.
    lot = (-30.0, -30.0, 30.0, 30.0)
    off = beyond(made, place, origin, grounds=[lot])
    assert len(off["houses"]) <= len(kept["houses"])
    for item in [q for h in off["houses"] for q in rect(h)] + [t["centreM"] for t in off["trees"]] + [p["centreM"] for p in off["poles"]]:
        assert not (lot[0] < item[0] < lot[2] and lot[1] < item[1] < lot[3])
    assert "家" in town_words(kept) and "入りませんでした" in town_words({**kept, "houses": []})


def test_the_plan_lays_the_town_clear_of_the_author_s_things_and_the_top_view_shows_it():
    data, shot = looking_down(kind="town", seed=4)
    assert schema_problems(data) == []
    plan = build_plan(data, shot, EXAMPLE)
    around = plan["surroundings"]
    assert around["kind"] == "town" and around["houses"]
    origin = plan["camera"]["positionM"][:2]
    reach = max(math.hypot(o["placed"]["centreM"][0] - origin[0], o["placed"]["centreM"][1] - origin[1]) for o in plan["objects"])
    assert around["houses"][0]["distanceM"] > 0 and around["dropped"]["houses"] >= 0
    top = build_top(plan)
    assert len(top["surroundings"]["houses"]) == len(around["houses"])
    assert any(line.startswith("まわりは市街地") for line in top_words(top))
    svg = to_svg(top)
    assert svg.count('fill="#f3ead8"') == len(around["houses"])
    # The drawing reaches the town's nearest houses.
    assert top["reachM"] >= min(around["houses"][0]["distanceM"], reach)
    # No surroundings: none in the plan, none on the drawing.
    data, shot = looking_down()
    plan = build_plan(data, shot, EXAMPLE)
    assert plan["surroundings"] is None and build_top(plan)["surroundings"] is None


def test_a_look_down_without_surroundings_is_asked_and_an_unknown_kind_is_an_error():
    data, shot = looking_down()
    found = {f["code"]: f for f in check_shot(data, shot)}
    asked = found["surroundings.open"]
    assert asked["level"] == "info" and [o["set"] for o in asked["question"]["options"]] == [
        {"surroundings.kind": "town"},
        {"surroundings.kind": "open"},
    ]
    # The answer fills the instruction, and the town is planned from it.
    answered, _ = effective(shot, asked["question"]["options"][0]["set"])
    assert answered["surroundings"] == {"kind": "town"} and build_plan(data, answered, EXAMPLE)["surroundings"]["houses"]
    for kind in ("town", "open"):
        data, shot = looking_down(kind=kind)
        assert "surroundings.open" not in {f["code"] for f in check_shot(data, shot)}
    # At eye level the horizon is in the picture and the far layers are what lies beyond: not asked.
    level = read_instruction(EXAMPLE)
    assert "surroundings.open" not in {f["code"] for f in check_shot(level, level["shots"][0])}
    data, shot = looking_down(kind="village")
    assert schema_problems(data)
    assert "surroundings.kind" in {f["code"] for f in check_shot(data, shot)}
