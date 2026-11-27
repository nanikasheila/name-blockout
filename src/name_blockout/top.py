# SPDX-License-Identifier: GPL-3.0-or-later
"""俯瞰図 (the top view): a shot's place seen from straight above, to scale, before anything is built in 3D.

A panel is a picture in perspective: one can look at it, but not measure it. The top view is the same layout
as numbers one can check at a glance: where the camera stands and what it sees (its angle of view, the ground
that shows in the panel), where each thing stands and how large it is in metres, the room's walls and windows,
what a place (.blend) holds. A layout that is wrong shows here in a second, before any 3D is built on it.

The drawing is turned so that the camera looks up the page: left and right are the panel's left and right.
Made from the plan alone (no Blender); a place's contents come as outlines measured from its .blend
(blender/measure.py: footprints), when there are any.

  俯瞰図/<コマ>.svg    the drawing (1 grid cell = 1 m, or 5 / 10 / 50 m for large places)
  俯瞰図/<コマ>.json   the same as numbers (metres, the world's coordinates)
"""

from __future__ import annotations

import json
import math
from html import escape
from pathlib import Path

from .sizes import usual_size

FORMAT = "name-blockout/top"
TOP_DIR = "俯瞰図"
#: Distances from the camera that get an arc (those within reach).
RINGS = (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000)
#: How far the drawing reaches when nothing stands in the shot, the least and the most (metres from the camera).
DEFAULT_REACH = 20.0
MIN_REACH = 6.0
MAX_REACH = 400.0
BEYOND = 1.2
#: The drawing's width in px, and its height at most.
WIDTH = 1000
MAX_HEIGHT = 1300
MARGIN = 0.08
BORDER_STEPS = 12
BAND_WORDS = {"near": "近景", "middle": "中景", "far": "遠景"}
BAND_FILL = {"near": "#ffd9a8", "middle": "#cfe8c9", "far": "#d9d9f2"}
WALL_WORDS = {"back": "奥", "left": "左", "right": "右", "front": "手前"}
#: A thing this many times taller (or this small a part) than things of its name usually are is doubted.
UNUSUAL = 3.0
#: Which way north is, by its axis.
NORTH_DIR = {"+X": (1.0, 0.0), "-X": (-1.0, 0.0), "+Y": (0.0, 1.0), "-Y": (0.0, -1.0)}
#: A place's things are named on the drawing when they are at least this wide on it (px).
NAME_FROM_PX = 36


def _unit2(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-9 else None


def _camera(plan: dict) -> dict:
    cam = plan["camera"]
    m = cam["matrixWorld"]
    right, up, back = ((m[0][i], m[1][i], m[2][i]) for i in range(3))
    pos = tuple(cam["positionM"])
    f = cam["focalPx"]
    px, py = cam["principalPx"]

    def ray(u: float, v: float):
        a, b = (u - px) / f, -(v - py) / f
        return tuple(right[i] * a + up[i] * b - back[i] for i in range(3))

    level = _unit2((-back[0], -back[1])) or _unit2((up[0], up[1])) or (0.0, 1.0)
    return {"position": pos, "ray": ray, "level": level, "size": tuple(cam["sizePx"]), "right": right, "up": up, "back": back}


def _horizon_ray(c: dict, u: float):
    """The level direction of the ray through column u where it runs level (on the horizon); the column's middle
    row when the camera has no horizon to speak of (looking straight down)."""
    right, up, back = c["right"], c["up"], c["back"]
    a = (u - c["px"]) / c["f"] if "px" in c else None
    if a is not None and abs(up[2]) > 1e-6:
        b = (back[2] - right[2] * a) / up[2]
        d = tuple(right[i] * a + up[i] * b - back[i] for i in range(3))
        return _unit2(d)
    return _unit2(c["ray"](u, c["size"][1] / 2))


def _rect(centre, size, along: str):
    w, d = size[0], size[1]
    if along == "Y":
        w, d = d, w
    x, y = centre[0], centre[1]
    return [[x - w / 2, y - d / 2], [x + w / 2, y - d / 2], [x + w / 2, y + d / 2], [x - w / 2, y + d / 2]]


def _name_word(label: str) -> str:
    return label if len(label) <= 8 else "物"


def _thing(item: dict, kind: str, camera_at) -> dict:
    p = item["placed"]
    centre, size = p["centreM"], p["sizeM"]
    entry = {
        "id": item["id"],
        "kind": kind,
        "label": item.get("label") or item.get("name") or item["id"],
        "centreM": [round(centre[0], 3), round(centre[1], 3)],
        "baseM": round(centre[2], 3),
        "sizeM": [round(v, 3) for v in size],
        "along": p.get("along", "X"),
        "footprintM": [[round(v, 3) for v in q] for q in _rect(centre, size, p.get("along", "X"))],
        "distanceM": round(math.hypot(centre[0] - camera_at[0], centre[1] - camera_at[1]), 2),
        "band": item.get("band", "near"),
    }
    if p.get("iou") is not None:
        entry["panelOverlap"] = round(p["iou"], 3)
    usual = usual_size(entry["label"]) if kind == "object" else None
    if usual and not UNUSUAL > size[2] / usual[2] > 1 / UNUSUAL:
        times = size[2] / usual[2]
        entry["doubt"] = (
            f"高さ {size[2]:.1f} m は、ふつうの{_name_word(entry['label'])}（{usual[2]:g} m）の {times:.1f} 倍"
            if times > 1
            else (f"高さ {size[2]:.2f} m は、ふつうの{_name_word(entry['label'])}（{usual[2]:g} m）の {1 / times:.1f} 分の 1")
        )
    if item.get("shape"):
        entry["shape"] = item["shape"] if isinstance(item["shape"], str) else item["shape"].get("kind") or "parts"
    if item.get("asset"):
        entry["asset"] = item["asset"] if isinstance(item["asset"], str) else item["asset"].get("name")
    return entry


def _outline_points(o: dict) -> list:
    """The points of a place's thing as drawn: its rings, else the convex outline around it."""
    rings = o.get("ringsM")
    return [q for ring in rings for q in ring] if rings else o["footprintM"]


def build_top(plan: dict, outlines: list[dict] | None = None, cut: dict | None = None) -> dict:
    """The top view of a plan as data. `outlines`: what a place holds (measure.footprints: "name", "footprintM",
    "ringsM", "sectionM", "heightM", "ground"); `cut`: where the place is cut as a floor plan (measure.indoor_cut),
    None for a place seen whole from above."""
    c = _camera(plan)
    cam = plan["camera"]
    c["px"], c["py"] = cam["principalPx"]
    c["f"] = cam["focalPx"]
    pos = c["position"]
    w, h = c["size"]
    things = [_thing(o, "object", pos) for o in plan.get("objects", [])] + [_thing(f, "figure", pos) for f in plan.get("figures", [])]
    room = plan.get("room")
    outlines = outlines or []

    left, right = _horizon_ray(c, 0.0), _horizon_ray(c, float(w))
    level = c["level"]

    def in_view(q) -> bool:
        d = (q[0] - pos[0], q[1] - pos[1])
        if not left or not right:
            return True
        # Between the two edges' level directions (the angle of view is under 180°).
        cross_l = left[0] * d[1] - left[1] * d[0]
        cross_r = right[0] * d[1] - right[1] * d[0]
        return cross_l <= 1e-9 and cross_r >= -1e-9 and d[0] * level[0] + d[1] * level[1] > 0

    far = [t["distanceM"] + math.hypot(t["sizeM"][0], t["sizeM"][1]) / 2 for t in things]
    if room:
        x0, y0, x1, y1 = room["rectM"]
        far += [math.hypot(x - pos[0], y - pos[1]) for x in (x0, x1) for y in (y0, y1)]
    for o in outlines:
        seen = [math.hypot(q[0] - pos[0], q[1] - pos[1]) for q in _outline_points(o) if in_view(q)]
        if seen and not o.get("ground"):
            far.append(min(max(seen), MAX_REACH / BEYOND))
    reach = min(MAX_REACH, max(MIN_REACH, max(far) * BEYOND)) if far else DEFAULT_REACH
    if cut and cut.get("roomReachM"):
        # Indoors the drawing is of the room: as far as its furthest wall, not the garden beyond it.
        reach = min(reach, max(MIN_REACH, cut["roomReachM"] * BEYOND))

    ground_z = (plan.get("ground") or {}).get("z", 0.0)
    seen_ground = []
    border = (
        [(w * i / BORDER_STEPS, 0.0) for i in range(BORDER_STEPS)]
        + [(float(w), h * i / BORDER_STEPS) for i in range(BORDER_STEPS)]
        + [(w - w * i / BORDER_STEPS, float(h)) for i in range(BORDER_STEPS)]
        + [(0.0, h - h * i / BORDER_STEPS) for i in range(BORDER_STEPS)]
    )
    for u, v in border:
        r = c["ray"](u, v)
        along = _unit2(r)
        if along is None:
            if r[2] < 0 and pos[2] > ground_z:
                seen_ground.append([round(pos[0], 3), round(pos[1], 3)])
            continue
        t = (ground_z - pos[2]) / r[2] if r[2] < -1e-9 else None
        d = math.hypot(r[0], r[1]) * t if t is not None and t > 0 else reach
        d = min(d, reach)
        seen_ground.append([round(pos[0] + along[0] * d, 3), round(pos[1] + along[1] * d, 3)])

    def bearing(d):
        return round(math.degrees(math.atan2(d[1], d[0])) % 360, 2) if d else None

    view = None
    if left and right:
        view = round(math.degrees(math.acos(max(-1.0, min(1.0, left[0] * right[0] + left[1] * right[1])))), 2)
    light = (plan.get("develop") or {}).get("lighting") or {}
    sun = light.get("sun") or {}
    toward_sun = _unit2(sun["direction"]) if sun.get("strength") and sun.get("direction") else None
    place = plan.get("place")
    assumed = [a["path"] for a in plan.get("assumptions", [])]
    top = {
        "format": FORMAT,
        "formatVersion": 1,
        "shot": plan["shot"],
        "label": plan.get("label", plan["shot"]),
        "camera": {
            "positionM": [round(pos[0], 3), round(pos[1], 3)],
            "heightM": round(pos[2] - ground_z, 3),
            "headingDeg": round(cam["headingDeg"], 2),
            "tiltDeg": round(cam["tiltDeg"], 2),
            "lensMm": round(cam["lensMm"], 1),
            "viewDeg": view,
            "edgesDeg": [bearing(left), bearing(right)],
            "levelDir": [round(level[0], 5), round(level[1], 5)],
        },
        "reachM": round(reach, 2),
        "groundSeenM": seen_ground,
        "things": things,
        "room": (
            {
                "rectM": room["rectM"],
                "heightM": room["heightM"],
                "sides": room["sides"],
                "windows": [{k: w[k] for k in ("wall", "fromM", "toM", "sillM", "headM")} for w in room.get("windows", [])],
            }
            if room
            else None
        ),
        "place": ({"asset": place.get("name"), "outlines": outlines, "outlinesKnown": bool(outlines), "cut": cut} if place else None),
        "sun": {"towardDeg": bearing(toward_sun), "elevationDeg": sun.get("elevationDeg")} if toward_sun else None,
        "north": {"axis": light["north"], "assumed": "look.north" in assumed} if light.get("north") in NORTH_DIR else None,
        "assumptions": assumed,
    }
    return top


# --- words ----------------------------------------------------------------------------------------


def camera_words(top: dict) -> str:
    cam = top["camera"]
    tilt = cam["tiltDeg"]
    look = "水平" if abs(tilt) < 0.5 else (f"見下ろし {tilt:.0f}°" if tilt > 0 else f"見上げ {-tilt:.0f}°")
    view = f"・横の画角 {cam['viewDeg']:.0f}°" if cam.get("viewDeg") else ""
    x, y = cam["positionM"]
    return (
        f"カメラ: 位置 ({x:.1f}, {y:.1f})・向き {cam['headingDeg']:.0f}°・高さ {cam['heightM']:.2f} m・{cam['lensMm']:.0f} mm・{look}{view}"
    )


def thing_words(t: dict) -> str:
    w, d, h = t["sizeM"]
    if t["along"] == "Y":
        w, d = d, w
    if t["kind"] == "figure":
        size = f"身長 {h:.2f} m"
    else:
        size = f"{w:.1f}×{d:.1f} m・高さ {h:.1f} m"
    words = f"{t['label']}: {size}・カメラから {t['distanceM']:.1f} m（{BAND_WORDS.get(t['band'], t['band'])}）"
    if t.get("baseM"):
        words += f"・床から {t['baseM']:.2f} m"
    if t.get("panelOverlap") is not None:
        words += f"・ネームの範囲との重なり {t['panelOverlap'] * 100:.0f}%"
    if t.get("doubt"):
        words += f"　！ {t['doubt']}（カメラの高さか、ネームの範囲を確かめる）"
    return words


def top_words(top: dict) -> list[str]:
    out = [camera_words(top)]
    room = top.get("room")
    if room:
        x0, y0, x1, y1 = room["rectM"]
        wins = "・".join(WALL_WORDS[w["wall"]] for w in room["windows"])
        out.append(f"部屋: {x1 - x0:.1f}×{y1 - y0:.1f} m・天井 {room['heightM']:.1f} m" + (f"・窓 {wins}" if wins else "・窓なし"))
    place = top.get("place")
    if place:
        known = f"物 {len(place['outlines'])} 個" if place["outlinesKnown"] else "中身は Blender で読むと入ります"
        cut = place.get("cut")
        if cut and place["outlinesKnown"]:
            known += f"・床から {cut['cutM'] - cut['floorM']:.1f} m の高さで切った間取り。太い線が壁、それより上の屋根・天井は描いていない"
        out.append(f"場所: {place['asset']}（{known}）")
    out += [thing_words(t) for t in top["things"]]
    if top.get("sun"):
        out.append(
            f"日差し: 矢印の向きへ・高さ {top['sun']['elevationDeg']:.0f}°"
            if top["sun"].get("elevationDeg") is not None
            else "日差し: 矢印の向きへ"
        )
    return out


# --- drawing --------------------------------------------------------------------------------------


def _grid_step(span: float) -> float:
    for limit, step in ((30.0, 1.0), (150.0, 5.0), (400.0, 10.0)):
        if span <= limit:
            return step
    return 50.0


def to_svg(top: dict) -> str:
    """The top view as an SVG drawing: the camera at the bottom looking up the page."""
    cam = top["camera"]
    cx, cy = cam["positionM"]
    lx, ly = cam["levelDir"]
    rx, ry = ly, -lx  # the camera's right, level

    def page(q):
        dx, dy = q[0] - cx, q[1] - cy
        return (dx * rx + dy * ry, -(dx * lx + dy * ly))

    points = [(0.0, 0.0)] + [page(q) for q in top["groundSeenM"]]
    for t in top["things"]:
        points += [page(q) for q in t["footprintM"]]
    if top.get("room"):
        x0, y0, x1, y1 = top["room"]["rectM"]
        points += [page(q) for q in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    pad = span * MARGIN
    bx0, bx1, by0, by1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    scale = min(WIDTH / (bx1 - bx0), MAX_HEIGHT / (by1 - by0))
    width, height = (bx1 - bx0) * scale, (by1 - by0) * scale

    def px(q):
        x, y = page(q)
        return ((x - bx0) * scale, (y - by0) * scale)

    def pts(poly) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in (px(q) for q in poly))

    def text(x, y, words, size=13, anchor="middle", fill="#222", weight="normal") -> str:
        return (
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" font-weight="{weight}" '
            f'stroke="#fff" stroke-width="3" paint-order="stroke" stroke-linejoin="round">{escape(words)}</text>'
        )

    taken: list[tuple[float, float, float, float]] = []

    def name(x, y, label, size=10, fill="#777", must=False) -> str:
        """A label that keeps clear of the ones before it (moved down or up a line or two; left out when there is
        no room and it need not be there)."""
        half, tall = len(label) * size * 0.34 + 3, size + 2
        for shift in (0, 1, -1, 2, -2):
            box = (x - half, y + shift * tall - tall, x + half, y + shift * tall + 2)
            if all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3] for b in taken):
                taken.append(box)
                return text(x, y + shift * tall, label, size, fill=fill)
        if must:
            return text(x, y, label, size, fill=fill)
        return ""

    def rings_path(rings) -> str:
        return " ".join("M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in (px(q) for q in ring)) + " Z" for ring in rings if len(ring) >= 3)

    words = top_words(top)
    line_h = 20
    legend_h = 44 + line_h * len(words)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height + legend_h:.0f}" '
        f"viewBox=\"0 0 {width:.0f} {height + legend_h:.0f}\" font-family=\"'Noto Sans JP', 'Yu Gothic', 'Hiragino Sans', sans-serif\">",
        f'<rect width="{width:.0f}" height="{height + legend_h:.0f}" fill="#fff"/>',
        f'<clipPath id="map"><rect width="{width:.0f}" height="{height:.0f}"/></clipPath>',
        '<g clip-path="url(#map)">',
    ]

    # The grid along the world's axes (they run to the ruler's vanishing points).
    step = _grid_step(span)
    corners = []
    for x, y in ((bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)):
        corners.append((cx + x * rx - y * lx, cy + x * ry - y * ly))
    wx0, wx1 = min(q[0] for q in corners), max(q[0] for q in corners)
    wy0, wy1 = min(q[1] for q in corners), max(q[1] for q in corners)
    grid = []
    k = math.floor(wx0 / step)
    while k * step <= wx1:
        (x1, y1), (x2, y2) = px((k * step, wy0)), px((k * step, wy1))
        grid.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
        k += 1
    k = math.floor(wy0 / step)
    while k * step <= wy1:
        (x1, y1), (x2, y2) = px((wx0, k * step)), px((wx1, k * step))
        grid.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
        k += 1
    out.append(f'<g stroke="#e3e3e3" stroke-width="1">{"".join(grid)}</g>')

    # What a place holds: under everything else. Seen whole from above, each thing by its outline; cut as a floor
    # plan, what stands below the cut by its outline and the cut itself (the walls) in a heavy line.
    place = top.get("place")
    cut = place.get("cut") if place else None
    if place:
        walls = []
        for o in place["outlines"]:
            if o.get("ground"):
                if len(o["footprintM"]) >= 3:
                    out.append(
                        f'<polygon points="{pts(o["footprintM"])}" fill="none" stroke="#b5b5b5" stroke-width="1" stroke-dasharray="6 4"/>'
                    )
                continue
            rings = o.get("ringsM") or ([o["footprintM"]] if len(o["footprintM"]) >= 3 else [])
            if rings:
                look = 'fill="#fafafa" stroke="#a8a8a8" stroke-width="0.8"' if cut else 'fill="#ececec" stroke="#7d7d7d" stroke-width="1"'
                out.append(f'<path d="{rings_path(rings)}" fill-rule="evenodd" {look}/>')
            for line in o.get("sectionM") or []:
                if len(line) >= 2:
                    walls.append("M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in (px(q) for q in line)))
        if walls:
            out.append(
                f'<path d="{" ".join(walls)}" fill="none" stroke="#222" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
            )

    # The ground that shows in the panel.
    if len(top["groundSeenM"]) >= 3:
        out.append(f'<polygon points="{pts(top["groundSeenM"])}" fill="#4c8dff" fill-opacity="0.10" stroke="#4c8dff" stroke-width="1.2"/>')

    # Arcs of distance from the camera, across the angle of view.
    ox, oy = px((cx, cy))
    edges = cam.get("edgesDeg") or [None, None]
    if edges[0] is not None and edges[1] is not None:
        for ring in RINGS:
            if ring > top["reachM"] or ring * scale < 28:
                continue
            ends = []
            for deg in edges:
                a = math.radians(deg)
                ends.append(px((cx + math.cos(a) * ring, cy + math.sin(a) * ring)))
            r = ring * scale
            out.append(
                f'<path d="M {ends[0][0]:.1f} {ends[0][1]:.1f} A {r:.1f} {r:.1f} 0 0 1 {ends[1][0]:.1f} {ends[1][1]:.1f}" '
                'fill="none" stroke="#4c8dff" stroke-width="1" stroke-dasharray="3 5"/>'
            )
            # Its distance at its right end, outside the angle of view (clear of what stands in it).
            label = f"{ring:g} m" + ("（ここまで近景）" if ring == 25 else "")
            taken.append((ends[1][0] + 4, ends[1][1] - 12, ends[1][0] + 10 + len(label) * 7.5, ends[1][1] + 4))
            out.append(text(ends[1][0] + 6, ends[1][1] + 2, label, 11, anchor="start", fill="#2f6fe0"))

    room = top.get("room")
    if room:
        x0, y0, x1, y1 = room["rectM"]
        out.append(
            f'<polygon points="{pts(((x0, y0), (x1, y0), (x1, y1), (x0, y1)))}" fill="#fffbe9" fill-opacity="0.6" stroke="#333" stroke-width="5" stroke-linejoin="miter"/>'
        )
        for win in room["windows"]:
            (ax, ay), (bx, by) = px(win["fromM"]), px(win["toM"])
            out.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="#fff" stroke-width="7"/>')
            out.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="#2a9d8f" stroke-width="2.5"/>')
            out.append(
                text(
                    (ax + bx) / 2,
                    (ay + by) / 2 - 8,
                    f"窓 {math.hypot(win['toM'][0] - win['fromM'][0], win['toM'][1] - win['fromM'][1]):.1f} m",
                    11,
                    fill="#1d7268",
                )
            )
        mid = {"+X": (x1, (y0 + y1) / 2), "-X": (x0, (y0 + y1) / 2), "+Y": ((x0 + x1) / 2, y1), "-Y": ((x0 + x1) / 2, y0)}
        for wall, side in room["sides"].items():
            mx, my = px(mid[side])
            length = (y1 - y0) if side[1] == "X" else (x1 - x0)
            dx, dy = mx - (px(((x0 + x1) / 2, (y0 + y1) / 2))[0]), my - (px(((x0 + x1) / 2, (y0 + y1) / 2))[1])
            n = math.hypot(dx, dy) or 1.0
            out.append(text(mx + dx / n * 16, my + dy / n * 16 + 4, f"{WALL_WORDS[wall]}の壁 {length:.1f} m", 11, fill="#555"))

    for t in top["things"]:
        fill = BAND_FILL.get(t["band"], "#ddd")
        mx, my = px(t["centreM"])
        if t["kind"] == "figure":
            out.append(
                f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="{max(5.0, 0.25 * scale):.1f}" fill="#f4a6b8" stroke="#8a2846" stroke-width="1.5"/>'
            )
            out.append(text(mx, my - max(5.0, 0.25 * scale) - 5, t["label"] or "人物", 12, fill="#8a2846"))
            continue
        out.append(f'<polygon points="{pts(t["footprintM"])}" fill="{fill}" fill-opacity="0.85" stroke="#333" stroke-width="1.8"/>')
        w, d = t["sizeM"][0], t["sizeM"][1]
        if t["along"] == "Y":
            w, d = d, w
        taken.append((mx - len(t["label"]) * 7 - 4, my - 16, mx + len(t["label"]) * 7 + 4, my + 16))
        out.append(text(mx, my - 2, t["label"], 13, weight="bold"))
        out.append(text(mx, my + 13, f"{w:.1f}×{d:.1f}・高さ {t['sizeM'][2]:.1f} m", 10, fill="#444"))

    if place:
        # Each of the place's things by its name in the place's file, on its largest shape that is on the page.
        for o in place["outlines"]:
            if o.get("ground"):
                continue
            for ring in o.get("ringsM") or [o["footprintM"]]:
                on = [px(q) for q in ring]
                x0, x1 = min(q[0] for q in on), max(q[0] for q in on)
                y0, y1 = min(q[1] for q in on), max(q[1] for q in on)
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                if max(x1 - x0, y1 - y0) < NAME_FROM_PX:
                    break  # the rings come largest first
                if 0 <= mx <= width and 0 <= my <= height:
                    out.append(name(mx, my + 4, o["name"]))
                    break

    # The camera: where it stands, and its angle of view.
    if edges[0] is not None and edges[1] is not None:
        for deg in edges:
            a = math.radians(deg)
            ex, ey = px((cx + math.cos(a) * top["reachM"], cy + math.sin(a) * top["reachM"]))
            out.append(f'<line x1="{ox:.1f}" y1="{oy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="#2f6fe0" stroke-width="1.5"/>')
    out.append(
        f'<polygon points="{ox:.1f},{oy - 14:.1f} {ox - 8:.1f},{oy + 6:.1f} {ox + 8:.1f},{oy + 6:.1f}" fill="#2f6fe0" stroke="#fff" stroke-width="1.5"/>'
    )
    out.append(text(ox, oy + 22, "カメラ", 12, fill="#2f6fe0", weight="bold"))

    # The sun: the way its light runs.
    sun = top.get("sun")
    if sun and sun.get("towardDeg") is not None:
        a = math.radians(sun["towardDeg"])
        dx, dy = -(math.cos(a) * rx + math.sin(a) * ry), (math.cos(a) * lx + math.sin(a) * ly)
        sx, sy = width - 60, 60
        out.append(f'<circle cx="{sx - dx * 26:.1f}" cy="{sy - dy * 26:.1f}" r="7" fill="#f6b73c" stroke="#b97d0a" stroke-width="1.5"/>')
        out.append(
            f'<line x1="{sx - dx * 18:.1f}" y1="{sy - dy * 18:.1f}" x2="{sx + dx * 26:.1f}" y2="{sy + dy * 26:.1f}" stroke="#b97d0a" stroke-width="2.5" marker-end="url(#arrow)"/>'
        )
        out.append(text(sx, sy + 46, "日差し", 11, fill="#8a5d05"))
        out.insert(
            3,
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#b97d0a"/></marker></defs>',
        )

    # The world's axes (the grid runs along them) and north, to read one panel's drawing against another's.
    kx, ky = 52, 58
    out.append(f'<circle cx="{kx}" cy="{ky}" r="34" fill="#fff" fill-opacity="0.85" stroke="#ccc"/>')
    for axis, (ax, ay) in (("X", (1.0, 0.0)), ("Y", (0.0, 1.0))):
        dx, dy = ax * rx + ay * ry, -(ax * lx + ay * ly)
        out.append(f'<line x1="{kx}" y1="{ky}" x2="{kx + dx * 22:.1f}" y2="{ky + dy * 22:.1f}" stroke="#999" stroke-width="1.5"/>')
        out.append(text(kx + dx * 29, ky + dy * 29 + 4, axis, 10, fill="#777"))
    north = top.get("north")
    if north:
        ax, ay = NORTH_DIR[north["axis"]]
        dx, dy = ax * rx + ay * ry, -(ax * lx + ay * ly)
        out.append(
            f'<polygon points="{kx + dx * 26:.1f},{ky + dy * 26:.1f} {kx - dy * 6 - dx * 4:.1f},{ky + dx * 6 - dy * 4:.1f} '
            f'{kx + dy * 6 - dx * 4:.1f},{ky - dx * 6 - dy * 4:.1f}" fill="#333"/>'
        )
        out.append(text(kx, ky + 50, "北（仮）" if north["assumed"] else "北", 11, fill="#333"))

    # The scale: one grid cell.
    bar = step * scale
    out.append(f'<rect x="14" y="{height - 30:.1f}" width="{bar + 16:.1f}" height="24" fill="#fff" fill-opacity="0.85"/>')
    out.append(
        f'<path d="M 22 {height - 16:.1f} h {bar:.1f} M 22 {height - 21:.1f} v 10 M {22 + bar:.1f} {height - 21:.1f} v 10" stroke="#222" stroke-width="1.5" fill="none"/>'
    )
    out.append(text(22 + bar / 2, height - 20, f"{step:g} m", 11))
    out.append("</g>")

    y = height + 26
    out.append(f'<line x1="0" y1="{height:.1f}" x2="{width:.0f}" y2="{height:.1f}" stroke="#ccc"/>')
    out.append(text(16, y, f"俯瞰図 {top['label']}（上がカメラの向く先・1 マス {step:g} m）", 15, anchor="start", weight="bold"))
    for i, line in enumerate(words):
        out.append(text(16, y + 24 + line_h * i, line, 12.5, anchor="start", fill="#b3261e" if "！" in line else "#333"))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_top(folder: Path, plan: dict, outlines: list[dict] | None = None, also: Path | None = None, cut: dict | None = None) -> dict:
    """Write a shot's top view into the work folder's 俯瞰図/ (and a copy beside a take's files): its paths and data."""
    top = build_top(plan, outlines, cut)
    svg = to_svg(top)
    out = Path(folder) / TOP_DIR
    out.mkdir(parents=True, exist_ok=True)
    paths = {"svg": out / f"{plan['shot']}.svg", "json": out / f"{plan['shot']}.json"}
    paths["svg"].write_text(svg, encoding="utf-8")
    paths["json"].write_text(json.dumps(top, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if also is not None:
        also.mkdir(parents=True, exist_ok=True)
        (also / "俯瞰図.svg").write_text(svg, encoding="utf-8")
    return {"top": top, "svg": str(paths["svg"]), "json": str(paths["json"])}
