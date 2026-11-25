# SPDX-License-Identifier: GPL-3.0-or-later
"""The room of an indoor shot: round the camera and what stands in it, windows on the walls asked (or for the light)."""

import json
from pathlib import Path

from name_blockout.plan import build_plan
from name_blockout.room import room_of

ROOT = Path(__file__).resolve().parents[1]
INDOOR = ROOT / "examples" / "indoor" / "指示.json"


def example():
    data = json.loads(INDOOR.read_text(encoding="utf-8"))
    return data, data["shots"][0]


def inside(rect, x, y, margin=0.0):
    x0, y0, x1, y1 = rect
    return x0 + margin <= x <= x1 - margin and y0 + margin <= y <= y1 - margin


def test_room_holds_the_camera_and_the_things():
    data, shot = example()
    plan = build_plan(data, shot, INDOOR)
    room = plan["room"]
    cam = plan["camera"]["matrixWorld"]
    assert inside(room["rectM"], cam[0][3], cam[1][3], 0.4)
    for obj in plan["objects"]:
        x, y, _ = obj["placed"]["centreM"]
        assert inside(room["rectM"], x, y, 0.4), obj["label"]
    assert room["heightM"] == 2.4
    # The floor is the ground: a grid inside the walls, not rings out to the horizon.
    assert plan["ground"]["rectM"] == room["rectM"] and "rings" not in plan["ground"]
    assert plan["notes"][0].startswith("部屋 ")


def test_window_for_the_light_is_on_the_wall_seen_on_the_left():
    data, shot = example()
    plan = build_plan(data, shot, INDOOR)
    (window,) = plan["room"]["windows"]
    # Looking across a corner (to +X and −Y): the wall on the picture's left is +X.
    assert window["side"] == "+X" and window["sillM"] == 0.9 and window["headM"] == 2.0
    assert any(a["path"] == "room.windows" for a in plan["assumptions"])
    # Its middle is in the picture.
    from name_blockout.camera import fit_camera
    from name_blockout.instruction import frame_of

    frame = frame_of(shot["frame"])
    camera = fit_camera(shot, frame)
    mid = [(a + b) / 2 for a, b in zip(window["fromM"], window["toM"])]
    p = camera.project((*mid, 1.45))
    assert p and 0 <= p[0] <= frame.width and 0 <= p[1] <= frame.height


def test_windows_asked_and_none():
    data, shot = example()
    shot["room"] = {"heightM": 2.6, "windows": [{"wall": "right", "widthM": 1.2, "sillM": 0.0, "heightM": 2.0}]}
    plan = build_plan(data, shot, INDOOR)
    (window,) = plan["room"]["windows"]
    assert window["wall"] == "right" and window["side"] == "-Y" and window["sillM"] == 0.0 and window["headM"] == 2.0
    assert plan["room"]["heightM"] == 2.6
    assert not any(a["path"] == "room.windows" for a in plan["assumptions"])
    shot["room"] = {"windows": []}
    assert build_plan(data, shot, INDOOR)["room"]["windows"] == []
    shot["room"] = False
    plan = build_plan(data, shot, INDOOR)
    assert plan["room"] is None and "rings" in plan["ground"]


def test_no_room_outdoors_and_a_ceiling_over_what_is_tall():
    data, shot = example()
    shot["look"]["setting"] = "outdoor"
    assert room_of(shot) is None
    shot["look"]["setting"] = "indoor"
    shot["objects"][2]["sizeM"] = [0.9, 0.35, 2.8]  # a shelf taller than a 2.4 m ceiling
    plan = build_plan(data, shot, INDOOR)
    assert plan["room"]["heightM"] > 2.8 and any("天井を" in n for n in plan["notes"])


def test_window_light_comes_from_the_window():
    from name_blockout.plan import build_develop_plan

    data, shot = example()
    shot.setdefault("look", {})["light"] = {"key": "window"}
    shot["look"]["timeOfDay"] = "noon"
    plan = build_develop_plan(data, shot, INDOOR)
    (window,) = plan["room"]["windows"]
    sun = plan["develop"]["lighting"]["sun"]
    # Toward the window's middle from the things in the room, at the window light's height.
    xs = [o["placed"]["centreM"] for o in plan["objects"] + plan["figures"]]
    cx, cy = sum(c[0] for c in xs) / len(xs), sum(c[1] for c in xs) / len(xs)
    wx, wy = [(a + b) / 2 for a, b in zip(window["fromM"], window["toM"])]
    d = sun["direction"]
    n = (wx - cx, wy - cy)
    length = (n[0] ** 2 + n[1] ** 2) ** 0.5
    flat = (d[0] ** 2 + d[1] ** 2) ** 0.5
    assert abs(d[0] / flat - n[0] / length) < 1e-3 and abs(d[1] / flat - n[1] / length) < 1e-3
    assert sun["elevationDeg"] == 20.0 and d[2] > 0
    assert any(n.startswith("窓の光は") for n in plan["notes"])


def test_window_heading_without_windows():
    from name_blockout.room import window_heading

    assert window_heading(None, []) is None
    assert window_heading({"rectM": [0, 0, 3, 3], "windows": []}, []) is None
