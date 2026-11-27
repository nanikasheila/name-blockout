# SPDX-License-Identifier: GPL-3.0-or-later
"""俯瞰図: the layout from straight above, as numbers and as a drawing, before anything is built."""

import copy
import json
import math
import shutil
from pathlib import Path

from name_blockout.cli import main
from name_blockout.instruction import read_instruction
from name_blockout.plan import build_develop_plan, build_plan
from name_blockout.top import build_top, to_svg, top_words

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
TWO_POINT = EXAMPLES / "two-point" / "指示.json"
INDOOR = EXAMPLES / "indoor" / "指示.json"


def _plan(path=TWO_POINT, develop=False):
    data = read_instruction(path)
    return (build_develop_plan if develop else build_plan)(data, data["shots"][0], path)


def test_things_stand_where_the_plan_put_them():
    plan = _plan()
    top = build_top(plan)
    by_id = {t["id"]: t for t in top["things"]}
    for obj in plan["objects"]:
        t = by_id[obj["id"]]
        assert t["centreM"] == [round(v, 3) for v in obj["placed"]["centreM"][:2]]
        xs = [q[0] for q in t["footprintM"]]
        ys = [q[1] for q in t["footprintM"]]
        w, d = obj["placed"]["sizeM"][:2]
        if obj["placed"]["along"] == "Y":
            w, d = d, w
        assert abs((max(xs) - min(xs)) - w) < 2e-3 and abs((max(ys) - min(ys)) - d) < 2e-3
        assert t["panelOverlap"] > 0.98
    assert by_id["f1"]["kind"] == "figure"


def test_the_camera_sees_what_is_in_the_panel():
    plan = _plan()
    top = build_top(plan)
    cam = top["camera"]
    # The angle of view across: the frame's width over the focal length.
    w = plan["camera"]["sizePx"][0]
    expected = 2 * math.degrees(math.atan(w / 2 / plan["camera"]["focalPx"]))
    assert abs(cam["viewDeg"] - expected) < 0.5
    # Everything marked on the panel stands between the two edges of the view, in front of the camera.
    left, right = (math.radians(d) for d in cam["edgesDeg"])
    for t in top["things"]:
        d = (t["centreM"][0] - cam["positionM"][0], t["centreM"][1] - cam["positionM"][1])
        assert math.cos(left) * d[1] - math.sin(left) * d[0] <= 0 <= math.cos(right) * d[1] - math.sin(right) * d[0]
    # The ground that shows starts where the panel's bottom edge meets it and runs out to the reach.
    seen = [math.hypot(q[0] - cam["positionM"][0], q[1] - cam["positionM"][1]) for q in top["groundSeenM"]]
    assert min(seen) > 1.0 and abs(max(seen) - top["reachM"]) < 1e-2
    assert top["reachM"] >= max(t["distanceM"] for t in top["things"])


def test_a_room_and_its_window_and_the_sun():
    top = build_top(_plan(INDOOR, develop=True))
    assert top["room"]["windows"] and top["room"]["rectM"]
    assert top["sun"]["towardDeg"] is not None
    words = "\n".join(top_words(top))
    assert "部屋" in words and "窓" in words and "ソファ" in words


def test_the_drawing_names_everything_and_is_the_same_twice():
    plan = _plan(INDOOR, develop=True)
    svg = to_svg(build_top(plan))
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    for word in ("俯瞰図", "カメラ", "ソファ", "テーブル", "本棚", "窓", "奥の壁", "日差し", "1 m"):
        assert word in svg, word
    assert svg == to_svg(build_top(_plan(INDOOR, develop=True)))


def test_a_place_s_contents_are_drawn_and_reach_is_theirs():
    plan = copy.deepcopy(_plan())
    plan["place"] = {"name": "庭", "file": "x.blend"}
    cam = plan["camera"]["positionM"]
    level = build_top(plan)["camera"]["levelDir"]
    ahead = (cam[0] + level[0] * 60, cam[1] + level[1] * 60)
    outlines = [
        {
            "name": "母屋",
            "footprintM": [
                [ahead[0] - 4, ahead[1] - 4],
                [ahead[0] + 4, ahead[1] - 4],
                [ahead[0] + 4, ahead[1] + 4],
                [ahead[0] - 4, ahead[1] + 4],
            ],
            "heightM": [0, 6],
            "ground": False,
        },
        {"name": "敷地", "footprintM": [[-500, -500], [500, -500], [500, 500], [-500, 500]], "heightM": [0, 0.1], "ground": True},
    ]
    top = build_top(plan, outlines)
    assert top["place"]["outlinesKnown"] and top["reachM"] > 60
    assert top["reachM"] < 200  # the lot's far corners do not stretch the drawing
    svg = to_svg(top)
    assert "母屋" in svg and "stroke-dasharray" in svg
    assert "中身は Blender" in "\n".join(top_words(build_top(plan)))


def test_a_thing_placed_on_the_top_view_stands_there(tmp_path):
    data = read_instruction(TWO_POINT)
    shot = copy.deepcopy(data["shots"][0])
    before = {o["id"]: o for o in build_plan(data, shot, TWO_POINT)["objects"]}["o1"]["placed"]
    moved = [before["centreM"][0] + 1.5, before["centreM"][1] - 0.5]
    shot["objects"][0]["positionM"] = moved
    plan = build_plan(data, shot, TWO_POINT)
    after = {o["id"]: o for o in plan["objects"]}["o1"]
    assert after["placed"]["centreM"][:2] == [round(v, 4) for v in moved]
    assert after["placed"]["sizeM"] == before["sizeM"] and after["fixedPlace"]
    assert after["placed"]["iou"] < before["iou"] and "俯瞰図" in after["placed"]["note"]
    # The same place gives the same picture: nothing was moved back to fill the panel's range.
    shot["objects"][0]["positionM"] = before["centreM"][:2]
    same = {o["id"]: o for o in build_plan(data, shot, TWO_POINT)["objects"]}["o1"]["placed"]
    assert abs(same["iou"] - before["iou"]) < 1e-3


def test_top_command_writes_the_drawing_and_takes_a_correction(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree(EXAMPLES / "two-point", work, ignore=shutil.ignore_patterns("案", "blockout", "俯瞰図", "要求"))
    path = work / "指示.json"
    assert main(["top", str(path)]) == 0
    assert "倉庫" in capsys.readouterr().out
    top = json.loads((work / "俯瞰図" / "panel1.json").read_text(encoding="utf-8"))
    assert (work / "俯瞰図" / "panel1.svg").read_text(encoding="utf-8").startswith("<svg")
    o1 = next(t for t in top["things"] if t["id"] == "o1")
    # A correction on the top view is an answer; the next drawing has the thing there.
    there = [o1["centreM"][0] + 2.0, o1["centreM"][1]]
    assert main(["answer", str(path), "--shot", "panel1", "--set", f"objects/o1/positionM={json.dumps(there)}"]) == 0
    assert main(["top", str(path), "--json"]) == 0
    again = json.loads((work / "俯瞰図" / "panel1.json").read_text(encoding="utf-8"))
    assert next(t for t in again["things"] if t["id"] == "o1")["centreM"] == [round(v, 3) for v in there]


def test_a_size_far_from_usual_is_doubted():
    plan = copy.deepcopy(_plan())
    plan["objects"][0]["placed"]["sizeM"] = [6.0, 3.0, 200.0]  # a 倉庫 200 m tall
    top = build_top(plan)
    assert "20.0 倍" in top["things"][0]["doubt"]
    assert not top["things"][1].get("doubt")
    assert "！" in "\n".join(top_words(top)) and "#b3261e" in to_svg(top)


def test_a_place_is_drawn_by_its_true_shapes_and_indoors_as_a_floor_plan():
    plan = copy.deepcopy(_plan(develop=True))
    plan["place"] = {"name": "家", "file": "x.blend"}
    cam = plan["camera"]["positionM"]
    level = build_top(plan)["camera"]["levelDir"]

    def ahead(d, side=0.0):
        return [cam[0] + level[0] * d - level[1] * side, cam[1] + level[1] * d + level[0] * side]

    square = [ahead(4, -1), ahead(4, 1), ahead(6, 1), ahead(6, -1)]
    trees = [[ahead(30, s - 1), ahead(30, s + 1), ahead(32, s + 1), ahead(32, s - 1)] for s in (-6, 6)]
    outlines = [
        {"name": "plants", "footprintM": trees[0] + trees[1], "ringsM": trees, "heightM": [0, 5], "ground": False},
        {
            "name": "shell",
            "footprintM": square,
            "ringsM": [square],
            "sectionM": [[ahead(6, -1), ahead(6, 1)]],
            "heightM": [0, 3],
            "ground": False,
        },
    ]
    # Seen whole: every tree its own shape, in one path.
    top = build_top(plan, outlines)
    svg = to_svg(top)
    assert svg.count('fill-rule="evenodd"') == 2 and svg.count(" Z M ") == 1
    assert top["reachM"] > 30 and "plants" in svg and "shell" in svg
    assert "間取り" not in "\n".join(top_words(top))
    # Cut as a floor plan: the walls in a heavy line, the drawing no further than the room.
    cut = {"floorM": 0.3, "ceilingM": 2.9, "cutM": 1.5, "roomReachM": 7.0}
    top = build_top(plan, outlines, cut)
    assert top["place"]["cut"] == cut and top["reachM"] < 10
    svg = to_svg(top)
    assert 'stroke="#222" stroke-width="2.2"' in svg
    assert "床から 1.2 m の高さで切った間取り" in "\n".join(top_words(top))
    # North and the world's axes are on the drawing, the camera's place in its words.
    assert top["north"]["axis"] in ("+X", "-X", "+Y", "-Y") and ("北" in svg)
    assert f"位置 ({cam[0]:.1f}, {cam[1]:.1f})" in top_words(top)[0]


def test_names_keep_clear_of_each_other():
    plan = copy.deepcopy(_plan())
    plan["place"] = {"name": "家", "file": "x.blend"}
    cam = plan["camera"]["positionM"]
    level = build_top(plan)["camera"]["levelDir"]
    centre = [cam[0] + level[0] * 10, cam[1] + level[1] * 10]
    ring = [[centre[0] + x, centre[1] + y] for x, y in ((-3, -3), (3, -3), (3, 3), (-3, 3))]
    outlines = [{"name": f"thing_{i}", "footprintM": ring, "ringsM": [ring], "heightM": [0, 2], "ground": False} for i in range(8)]
    svg = to_svg(build_top(plan, outlines))
    spots = set()
    for i in range(8):
        if f">thing_{i}<" in svg:
            line = next(row for row in svg.splitlines() if f">thing_{i}<" in row)
            spots.add(line.split('y="')[1].split('"')[0])
    # Eight names on one spot: the ones with room are each on their own line, the rest left out.
    assert 2 <= len(spots) <= 5 and len(spots) == sum(f">thing_{i}<" in svg for i in range(8))
