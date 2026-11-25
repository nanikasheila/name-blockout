# SPDX-License-Identifier: GPL-3.0-or-later
"""The room of an indoor shot: a floor, four walls and a ceiling around the
camera and what stands in it, with windows cut in the walls. Its corners run
to the vanishing points like the ground's grid (they are drawn), its walls
take the light and the tones, and through a window the sky (or the far
layers) shows. Nothing here needs Blender.

The walls are named as the camera sees them: back (the one it looks at),
left, right and front (behind it). A window is on one of them: as wide and as
tall as asked (else a waist-high window, 1.7 m by 1.1 m, its sill at 0.9 m),
its middle offsetM from the wall's middle, to the right as one faces the
wall from inside. When the light comes through a window (look.light.key
window) and none is asked for, one is put in the left wall, where that light
comes from.
"""

from __future__ import annotations

import math

from .look import setting_of

DEFAULT_HEIGHT_M = 2.4
WINDOW = {"widthM": 1.7, "heightM": 1.1, "sillM": 0.9}
WALLS = ("back", "left", "right", "front")
WALL_LABELS = {"back": "奥", "left": "左", "right": "右", "front": "手前"}
#: Room round the camera and the things: how far beyond them the walls stand, and the least room (a 6-mat room's side).
MARGIN_M = 0.5
LEAST_M = 2.7
#: Things farther than this (or in the far band) are outside: seen through a window, not in the room.
INSIDE_M = 25.0
#: How deep a window's reveal is (the wall's thickness at it).
REVEAL_M = 0.12
#: Each world side's outward normal (a wall on it faces the other way, into the room).
NORMALS = {"+X": (1.0, 0.0), "-X": (-1.0, 0.0), "+Y": (0.0, 1.0), "-Y": (0.0, -1.0)}


def room_of(shot: dict) -> dict | None:
    """The room asked for (indoors, unless room is false), its windows filled in; None outdoors."""
    given = shot.get("room")
    if given is False:
        return None
    setting, _ = setting_of(shot)
    if setting != "indoor" and not isinstance(given, dict):
        return None
    given = given if isinstance(given, dict) else {}
    windows = given.get("windows")
    auto = windows is None
    if auto:
        key = ((shot.get("look") or {}).get("light") or {}).get("key")
        windows = [{"wall": "left"}] if key == "window" else []
    filled = [{**WINDOW, "offsetM": 0.0, **w} for w in windows if w.get("wall") in WALLS]
    return {"heightM": float(given.get("heightM") or DEFAULT_HEIGHT_M), "windows": filled, "autoWindows": auto and bool(filled)}


def _sides(forward: tuple[float, float]) -> dict[str, str]:
    """Which world side (+X, −X, +Y, −Y: the wall's outward normal) each wall is, for a camera looking along `forward`."""
    normals = NORMALS
    right = (forward[1], -forward[0])

    def best(d):
        return max(normals, key=lambda k: normals[k][0] * d[0] + normals[k][1] * d[1])

    back = best(forward)
    across = [k for k in normals if k[1] != back[1]]
    side = max(across, key=lambda k: normals[k][0] * right[0] + normals[k][1] * right[1])
    flip = {"+": "-", "-": "+"}
    return {"back": back, "front": flip[back[0]] + back[1], "right": side, "left": flip[side[0]] + side[1]}


def build_room(spec: dict, camera, placed: list[dict]) -> tuple[dict, list[str]]:
    """The room in the world round the camera and the things in it (plan entries with placed boxes), and notes."""
    notes: list[str] = []
    cx, cy, cz = camera.position
    _, _, forward = camera.camera_axes_world()
    level = (forward[0], forward[1])
    n = math.hypot(*level)
    level = (level[0] / n, level[1] / n) if n > 1e-9 else (0.0, 1.0)
    xs, ys, tops = [cx - MARGIN_M, cx + MARGIN_M], [cy - MARGIN_M, cy + MARGIN_M], [cz + 0.3]
    outside = []
    for item in placed:
        p = item["placed"]
        if item.get("band") == "far" or item.get("distanceM", 0.0) > INSIDE_M:
            outside.append(item.get("label") or item.get("name") or item["id"])
            continue
        w, d, h = p["sizeM"]
        if p.get("along") == "Y":
            w, d = d, w
        x, y, z = p["centreM"]
        xs += [x - w / 2 - MARGIN_M, x + w / 2 + MARGIN_M]
        ys += [y - d / 2 - MARGIN_M, y + d / 2 + MARGIN_M]
        tops.append(z + h + 0.1)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sides = _sides(level)
    # The back wall at least LEAST_M ahead of the camera, and the room at least LEAST_M across.
    back = sides["back"]
    if back == "+X":
        x1 = max(x1, cx + LEAST_M)
    elif back == "-X":
        x0 = min(x0, cx - LEAST_M)
    elif back == "+Y":
        y1 = max(y1, cy + LEAST_M)
    else:
        y0 = min(y0, cy - LEAST_M)
    if x1 - x0 < LEAST_M:
        grow = (LEAST_M - (x1 - x0)) / 2
        x0, x1 = x0 - grow, x1 + grow
    if y1 - y0 < LEAST_M:
        grow = (LEAST_M - (y1 - y0)) / 2
        y0, y1 = y0 - grow, y1 + grow
    height = max(spec["heightM"], *tops)
    if height > spec["heightM"] + 1e-6:
        notes.append(f"部屋の天井を {height:.2f}m に上げた（カメラか物が {spec['heightM']:g}m の天井に届く）")
    rect = [round(v, 4) for v in (x0, y0, x1, y1)]
    windows = []
    for w in spec["windows"]:
        if spec.get("autoWindows"):
            w = {**w, **_seen_left(camera, rect, height, sides, level)}
        side = sides[w["wall"]]
        win = _window(rect, height, side, w, notes)
        if win:
            windows.append({"wall": w["wall"], **win})
    if outside:
        notes.append(f"部屋の外に置いた物: {'・'.join(outside)}（{INSIDE_M:g}m より先か遠景。窓から見えるなら窓を）")
    room = {"rectM": rect, "heightM": round(height, 4), "sides": sides, "windows": windows, "revealM": REVEAL_M}
    return room, notes


def _seen_left(camera, rect, height: float, sides: dict, level) -> dict:
    """For the window the light comes through: the wall seen on the picture's left (the left wall looking straight
    on, the left of the two seen looking across a corner), and the place on it seen a third of the way in."""
    left = (-level[1], level[0])
    toward = (0.6 * level[0] + left[0], 0.6 * level[1] + left[1])
    side = max(NORMALS, key=lambda k: NORMALS[k][0] * toward[0] + NORMALS[k][1] * toward[1])
    wall = next(name for name, s in sides.items() if s == side)
    (ax, ay), (bx, by) = _ends(rect, side)
    length = math.hypot(bx - ax, by - ay)
    best, best_d = 0.0, float("inf")
    for i in range(1, 20):
        u = length * i / 20
        p = camera.project((ax + (bx - ax) * u / length, ay + (by - ay) * u / length, 1.45))
        if p is None or not (0 <= p[0] <= camera.width and 0 <= p[1] <= camera.height):
            continue
        d = abs(p[0] - camera.width / 3)
        if d < best_d:
            best, best_d = u - length / 2, d
    return {"wall": wall, "offsetM": round(best, 3)}


def _ends(rect, side: str):
    """A wall's ends on the floor, left to right as seen from inside facing it."""
    x0, y0, x1, y1 = rect
    return {
        "+X": ((x1, y1), (x1, y0)),
        "-X": ((x0, y0), (x0, y1)),
        "+Y": ((x0, y1), (x1, y1)),
        "-Y": ((x1, y0), (x0, y0)),
    }[side]


def _window(rect, height: float, side: str, w: dict, notes: list[str]) -> dict | None:
    """A window on the wall at `side`: its two ends on the floor's line (from left to right seen from inside) and its
    sill and head heights, kept inside the wall."""
    (ax, ay), (bx, by) = _ends(rect, side)
    length = math.hypot(bx - ax, by - ay)
    width = min(float(w["widthM"]), length - 0.4)
    sill = max(0.0, float(w["sillM"]))
    head = min(height - 0.1, sill + float(w["heightM"]))
    if width < 0.3 or head - sill < 0.3:
        notes.append(f"{WALL_LABELS[w['wall']]}の壁に窓が入りません（壁 {length:.2f}m・天井 {height:.2f}m）")
        return None
    middle = length / 2 + float(w.get("offsetM") or 0.0)
    middle = min(max(middle, 0.2 + width / 2), length - 0.2 - width / 2)
    ux, uy = (bx - ax) / length, (by - ay) / length
    start, end = middle - width / 2, middle + width / 2
    return {
        "side": side,
        "fromM": [round(ax + ux * start, 4), round(ay + uy * start, 4)],
        "toM": [round(ax + ux * end, 4), round(ay + uy * end, 4)],
        "sillM": round(sill, 4),
        "headM": round(head, 4),
    }


def room_words(room: dict) -> str:
    """The room in a few words, for the plan's notes: 部屋 3.6×4.2m・天井 2.4m・窓 左."""
    x0, y0, x1, y1 = room["rectM"]
    wins = "・".join(WALL_LABELS[w["wall"]] for w in room["windows"])
    return f"部屋 {x1 - x0:.1f}×{y1 - y0:.1f}m・天井 {room['heightM']:.1f}m" + (f"・窓 {wins}" if wins else "")
