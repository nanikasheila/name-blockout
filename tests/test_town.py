# SPDX-License-Identifier: GPL-3.0-or-later
"""What lies round a place: a town from a seed, anchored to the world, and only beyond the place."""

import copy
import json
import math
from pathlib import Path

import pytest

from name_blockout.camera import fit_camera
from name_blockout.checks import check_shot
from name_blockout.far import NEAR_M
from name_blockout.instruction import read_instruction, schema_problems
from name_blockout.materials import natural_parts
from name_blockout.plan import build_plan
from name_blockout.requirement import effective
from name_blockout.top import build_top, to_svg, top_words
from name_blockout.town import (
    BLOCK_DEEP_M,
    LOT_MAX_M,
    REACH_M,
    STREET_M,
    beyond,
    off_outline,
    outline,
    place_reach,
    rect,
    seen_reach,
    town,
    town_words,
)

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
    assert len(a["houses"]) > 5 and a["poles"] and a["trees"]
    # None in the near band: what stands near is the author's to draw.
    at = camera.position[:2]
    assert min(math.hypot(x - at[0], y - at[1]) for h in a["houses"] for x, y in rect(h)) > NEAR_M
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
        assert house["ridge"] in ("along", "across")


def test_a_street_runs_where_the_place_s_road_does_and_along_either_axis():
    """`street`: one of the town's streets through a given line (the place's own road carried on), along X or Y."""
    _, shot = looking_down()
    camera = fit_camera(shot)
    plain = town(camera, {"seed": 4, "reachM": 150})
    moved = town(camera, {"seed": 4, "reachM": 150, "street": {"axis": "X", "atM": -18.5}})
    assert plain["street"] == {"axis": "X", "atM": 0.0, "widthM": STREET_M} and moved["street"] == {
        "axis": "X",
        "atM": -18.5,
        "widthM": STREET_M,
    }
    lines = [st["atM"] for st in moved["streets"] if st["axis"] == "X"]
    assert -18.5 in lines and all(abs((v + 18.5) / BLOCK_DEEP_M - round((v + 18.5) / BLOCK_DEEP_M)) < 1e-6 for v in lines)
    for house in moved["houses"]:
        ys = [y for _, y in rect(house)]
        assert all(not (min(ys) < line + STREET_M / 2 - 1e-6 and max(ys) > line - STREET_M / 2 + 1e-6) for line in lines)
    assert "y = -18.5 を 1 本が通る" in town_words(moved)
    # As wide as the place's road: the houses and the poles stand off it, and the next street is as much farther.
    wide = town(camera, {"seed": 4, "reachM": 150, "street": {"axis": "X", "atM": -18.5, "widthM": 8.2}})
    assert wide["streetM"] == 8.2 and "幅 8.2 m" in town_words(wide)
    lines = sorted(st["atM"] for st in wide["streets"] if st["axis"] == "X")
    assert -18.5 in lines and lines[1] - lines[0] == pytest.approx(BLOCK_DEEP_M + 2.2)
    for house in wide["houses"]:
        ys = [y for _, y in rect(house)]
        assert all(not (min(ys) < line + 4.1 - 1e-6 and max(ys) > line - 4.1 + 1e-6) for line in lines)
    assert wide["poles"] and all(min(abs(p["centreM"][1] - line) for line in lines) > 4.1 for p in wide["poles"])
    # Along Y: the same town turned, its houses fronting ±X, their footprints deep along X.
    turned = town(camera, {"seed": 4, "reachM": 150, "street": {"axis": "Y", "atM": 10.0}})
    assert turned["houses"] and {h["front"] for h in turned["houses"]} <= {"-X", "+X"}
    lines = [st["atM"] for st in turned["streets"] if st["axis"] == "Y"]
    assert 10.0 in lines
    for house in turned["houses"]:
        xs = [x for x, _ in rect(house)]
        assert max(xs) - min(xs) == pytest.approx(house["sizeM"][1])  # its depth lies along X
        assert all(not (min(xs) < line + STREET_M / 2 - 1e-6 and max(xs) > line - STREET_M / 2 + 1e-6) for line in lines)
    # The cross streets too are clear of houses.
    for made in (moved, turned):
        main = made["street"]["axis"]
        for st in made["streets"]:
            if st["axis"] == main:
                continue
            for house in made["houses"]:
                r = rect(house)
                along = [q[0] if main == "X" else q[1] for q in r]
                across = [q[1] if main == "X" else q[0] for q in r]
                inside_row = min(across) > st["fromM"] and max(across) < st["toM"]
                assert not (inside_row and min(along) < st["atM"] + STREET_M / 2 - 1e-6 and max(along) > st["atM"] - STREET_M / 2 + 1e-6)


def test_a_potted_plant_s_pot_is_not_a_natural_part():
    assert natural_parts(["concrete", "plant", "trunk"]) == [False, True, True]
    assert natural_parts(["leaf", "bark", "Material.001"]) == [True, True, True]
    assert natural_parts(["stone"]) == [True]  # a rock has no leaves: all of it is the natural thing
    assert natural_parts(["leaves", "metal"]) == [True, False]


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
    # Nor among the place's things: a yard behind a long wall is the place's, though it lies beyond the wall.
    wall = [(x, -14.0) for x in range(-60, 61, 5)]
    yard = beyond(made, place + wall, origin)
    hull = outline(place + wall)
    assert (-60.0, -14.0) in hull and (60.0, -14.0) in hull and (0.0, 4.0) not in hull
    assert off_outline(hull, 30.0, -5.0) < 0 < off_outline(hull, 30.0, 30.0)
    assert yard["houses"] and len(yard["houses"]) < len(kept["houses"])
    for item in (
        [q for h in yard["houses"] for q in rect(h)] + [t["centreM"] for t in yard["trees"]] + [p["centreM"] for p in yard["poles"]]
    ):
        assert off_outline(hull, item[0], item[1]) > STREET_M
    assert off_outline([(0.0, 0.0), (10.0, 0.0)], 5.0, 3.0) == 3.0 and off_outline([], 1.0, 1.0) == math.inf
    # Nothing on the place's own ground either, however far it goes.
    lot = (-30.0, -30.0, 30.0, 30.0)
    off = beyond(made, place, origin, grounds=[lot])
    assert len(off["houses"]) <= len(kept["houses"])
    for item in [q for h in off["houses"] for q in rect(h)] + [t["centreM"] for t in off["trees"]] + [p["centreM"] for p in off["poles"]]:
        assert not (lot[0] < item[0] < lot[2] and lot[1] < item[1] < lot[3])
    # A ground out to the horizon is the land the place was modelled on, not its lot: the town stands on it.
    land = (-150.0, -150.0, 150.0, 150.0)
    assert max(land[2] - land[0], land[3] - land[1]) > LOT_MAX_M
    assert beyond(made, place, origin, grounds=[land])["houses"] == kept["houses"]
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
    assert svg.count('stroke="#ece7dc"') == len(around["streets"]) > 0  # the streets' lines, to lay on the place's road
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
