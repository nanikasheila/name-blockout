# SPDX-License-Identifier: GPL-3.0-or-later
"""Detailed shapes for the development, made by the tool where a thing has
no 素材: a house gets its walls, roof, windows and door; a van its body,
windows, wheels and lights; a sofa its seat, cushions, back and arms. The
Blockout keeps the boxes (a Blockout is for deciding, fast); the development
draws what the finished picture needs, so the pen has edges to follow.

A shape is a list of parts, each a simple solid in the thing's own frame
(metres; the middle of its bottom at the origin, its front toward −Y, up +Z):

    {"name": "窓ガラス", "shape": "box", "c": [x, y, z], "s": [sx, sy, sz], "material": "ガラス"}

`shape` is box, cylinder (along `axis` X, Y or Z), sphere, or prism (a gable
roof: a triangle across X, its ridge along Y, or along X with "ridge": "X").
`c` is the part's middle, `s` its size. `material` is a material of the
library (materials.py); without one the part is the thing's own material.

The tool knows the kinds in KINDS by the words of the thing's name (or its
`shape`, a kind's name). For anything else the author (or an agent working
for them) can write the parts themselves: `shape` as {"unit": "box", "parts":
[...]} with `c` and `s` as fractions of the thing's box (0…1 across, deep and
up; c [0.5, 0.5, 0.5] is the middle), or {"unit": "m", ...} in metres. Then
nothing is guessed. Nothing here needs Blender.
"""

from __future__ import annotations

import math
import random

Part = dict

# Kinds and the words that name them (the longest word found wins).
KINDS: dict[str, tuple[str, ...]] = {
    "house": ("家", "住宅", "民家", "一軒家", "実家", "家屋"),
    "building": ("ビル", "建物", "マンション", "アパート", "団地", "学校", "校舎", "病院", "研究所", "ホテル", "店", "駅"),
    "shed": ("倉庫", "小屋", "物置", "車庫", "ガレージ"),
    "van": ("バン", "ワゴン", "ミニバン", "救急車"),
    "car": ("車", "自動車", "乗用車", "タクシー", "パトカー"),
    "truck": ("トラック", "軽トラ"),
    "bus": ("バス",),
    "sofa": ("ソファ", "ソファー", "長椅子"),
    "chair": ("椅子", "いす", "イス"),
    "table": ("テーブル", "机", "デスク", "ちゃぶ台", "食卓"),
    "bed": ("ベッド", "寝台"),
    "shelf": ("本棚", "棚", "書棚", "ラック"),
    "cabinet": ("冷蔵庫", "タンス", "箪笥", "ロッカー", "戸棚", "食器棚", "キャビネット"),
    "stairs": ("階段",),
    "fence": ("柵", "フェンス", "手すり", "ガードレール"),
    "wall": ("塀", "ブロック塀"),
    "pole": ("電柱", "街灯", "電灯", "ポール"),
    "tree": ("木", "樹", "大木", "街路樹"),
    "door": ("ドア", "扉"),
    "tv": ("テレビ", "モニター"),
    "bench": ("ベンチ",),
    "counter": ("カウンター", "レジ"),
}
KIND_LABELS = {
    "house": "家",
    "building": "ビル",
    "shed": "小屋",
    "van": "バン",
    "car": "車",
    "truck": "トラック",
    "bus": "バス",
    "sofa": "ソファ",
    "chair": "椅子",
    "table": "テーブル",
    "bed": "ベッド",
    "shelf": "棚",
    "cabinet": "戸棚",
    "stairs": "階段",
    "fence": "柵",
    "wall": "塀",
    "pole": "電柱",
    "tree": "木",
    "door": "ドア",
    "tv": "テレビ",
    "bench": "ベンチ",
    "counter": "カウンター",
}
#: A few words hold a shorter kind's word but mean something else (木 in 木造 is wood, not a tree).
NOT_KINDS = ("木造", "木製", "木目", "車輪", "車椅子", "電車", "列車", "家具")


def kind_of(obj: dict) -> str | None:
    """The kind of shape a thing gets: its `shape` when that names a kind, else the words of its name."""
    shape = obj.get("shape")
    if isinstance(shape, str):
        return shape if shape in KINDS else None
    words = f"{obj.get('label') or ''} {obj.get('name') or ''}"
    for word in NOT_KINDS:
        words = words.replace(word, " ")
    found = [(len(w), kind) for kind, ws in KINDS.items() for w in ws if w in words]
    return max(found)[1] if found else None


def shape_of(obj: dict, size) -> tuple[list[Part], str | None]:
    """A thing's parts for its box `size` (w across, d deep, h up; metres), and how they were found:
    "own" (the author's parts), a kind's name, or None (no shape: the box stays)."""
    w, d, h = (float(v) for v in size)
    shape = obj.get("shape")
    if isinstance(shape, dict) and shape.get("parts"):
        return _own(shape, w, d, h), "own"
    kind = kind_of(obj)
    if not kind:
        return [], None
    seed = sum(ord(ch) for ch in str(obj.get("id") or obj.get("label") or kind))
    return fit(BUILDERS[kind](w, d, h, random.Random(seed)), w, d, h), kind


def fit(parts: list[Part], w: float, d: float, h: float) -> list[Part]:
    """The parts stretched and moved so together they fill the box exactly (bottom centre at the origin): the
    author's range is the thing's outline, eaves and crowns included."""
    if not parts:
        return parts
    lo, hi = bounds(parts)
    want_lo, want = (-w / 2, -d / 2, 0.0), (w, d, h)
    k = [want[i] / (hi[i] - lo[i]) if hi[i] - lo[i] > 1e-9 else 1.0 for i in range(3)]
    out = []
    for p in parts:
        c = [round(want_lo[i] + (p["c"][i] - lo[i]) * k[i], 4) for i in range(3)]
        sz = [round(p["s"][i] * k[i], 4) for i in range(3)]
        out.append({**p, "c": c, "s": sz})
    return out


def _own(shape: dict, w: float, d: float, h: float) -> list[Part]:
    """The author's parts, scaled from fractions of the box (unit "box") or as they are (unit "m")."""
    parts = []
    for p in shape["parts"]:
        c, s = list(p.get("c") or (0.5, 0.5, 0.5)), list(p.get("s") or (1, 1, 1))
        if shape.get("unit", "box") == "box":
            c = [(c[0] - 0.5) * w, (c[1] - 0.5) * d, c[2] * h]
            s = [s[0] * w, s[1] * d, s[2] * h]
        parts.append({**p, "c": c, "s": s, "shape": p.get("shape", "box"), "name": p.get("name") or "部品"})
    return parts


def bounds(parts: list[Part]) -> tuple[list[float], list[float]]:
    """The lowest and highest corner of the parts (cylinders and spheres by their boxes)."""
    lo = [min(p["c"][i] - p["s"][i] / 2 for p in parts) for i in range(3)]
    hi = [max(p["c"][i] + p["s"][i] / 2 for p in parts) for i in range(3)]
    return lo, hi


def _box(name, c, s, material=None, **extra) -> Part:
    out = {"name": name, "shape": "box", "c": [round(v, 4) for v in c], "s": [round(max(v, 0.002), 4) for v in s]}
    if material:
        out["material"] = material
    return {**out, **extra}


def _cyl(name, c, s, axis, material=None) -> Part:
    return {**_box(name, c, s, material), "shape": "cylinder", "axis": axis}


def _turned(parts: list[Part]) -> list[Part]:
    """Parts made with their long side along X, turned a quarter so it runs along Y (front still −Y)."""
    out = []
    swap = {"X": "Y", "Y": "X", "Z": "Z"}
    for p in parts:
        q = {**p, "c": [p["c"][1], p["c"][0], p["c"][2]], "s": [p["s"][1], p["s"][0], p["s"][2]]}
        if "axis" in p:
            q["axis"] = swap[p["axis"]]
        if "ridge" in p:
            q["ridge"] = swap[p["ridge"]]
        out.append(q)
    return out


def _windows_on(face: str, w: float, d: float, z0: float, z1: float, count: int, win_w: float, win_h: float, sill: float):
    """A row of windows (frame, glass, sill) on a face of a w×d block, between heights z0 and z1."""
    parts = []
    along = w if face in ("front", "back") else d
    count = max(0, min(count, int((along - 0.6) / (win_w + 0.4))))
    if count <= 0 or z1 - z0 < win_h + 0.2:
        return parts
    pitch = along / count
    z = z0 + min(sill, z1 - z0 - win_h - 0.1) + win_h / 2
    for i in range(count):
        u = -along / 2 + pitch * (i + 0.5)
        if face == "front":
            c = (u, -d / 2, z)
        elif face == "back":
            c = (u, d / 2, z)
        elif face == "left":
            c = (-w / 2, u, z)
        else:
            c = (w / 2, u, z)
        across_x = face in ("front", "back")
        sign = -1 if face in ("front", "left") else 1

        def at(depth, _c=c, _sign=sign, _x=across_x):
            return (_c[0], _c[1] + _sign * depth, _c[2]) if _x else (_c[0] + _sign * depth, _c[1], _c[2])

        def sized(a, b, t, _x=across_x):
            return (a, t, b) if _x else (t, a, b)

        parts.append(_box("窓枠", at(0.03), sized(win_w + 0.12, win_h + 0.12, 0.06), "金属"))
        parts.append(_box("窓ガラス", at(0.045), sized(win_w, win_h, 0.06), "ガラス"))
        # The mullion (the middle bar) and the sill.
        parts.append(_box("窓枠", at(0.07), sized(0.05, win_h, 0.03), "金属"))
        sc = at(0.07)
        parts.append(_box("窓台", (sc[0], sc[1], c[2] - win_h / 2 - 0.06), sized(win_w + 0.2, 0.05, 0.1), "コンクリート"))
    return parts


def house(w, d, h, rnd) -> list[Part]:
    """A two-storey house (one when low): a footing, walls, a gable roof with eaves, windows on each side, a door and a step."""
    footing = min(0.45, h * 0.08)
    wall_top = h * (0.66 if h > 4.5 else 0.6)
    eave = min(0.6, w * 0.08)
    ridge = "X" if w >= d else "Y"
    parts = [
        _box("基礎", (0, 0, footing / 2), (w + 0.04, d + 0.04, footing), "コンクリート"),
        _box("外壁", (0, 0, (footing + wall_top) / 2), (w, d, wall_top - footing)),
        _box("軒", (0, 0, wall_top + 0.06), (w + 2 * eave, d + 2 * eave, 0.12), "木"),
        {
            **_box("屋根", (0, 0, wall_top + 0.12 + (h - wall_top - 0.12) / 2), (w + 2 * eave, d + 2 * eave, h - wall_top - 0.12), "瓦"),
            "shape": "prism",
            "ridge": ridge,
        },
    ]
    # Siding: boards across the walls, a line every 0.3 m (windows and the door stand in front of them).
    boards = int((wall_top - footing) / 0.3)
    for i in range(1, boards):
        z = footing + i * (wall_top - footing) / boards
        parts.append(_box("板張り", (0, -d / 2 - 0.006, z), (w, 0.012, 0.018)))
        parts.append(_box("板張り", (-w / 2 - 0.006, 0, z), (0.012, d, 0.018)))
        parts.append(_box("板張り", (w / 2 + 0.006, 0, z), (0.012, d, 0.018)))
    # Corner boards, a ridge cap and the barge boards of the gables.
    for x in (-w / 2, w / 2):
        parts.append(_box("隅板", (x, -d / 2, (footing + wall_top) / 2), (0.12, 0.12, wall_top - footing), "木"))
    roof_h = h - wall_top - 0.12
    span = (w if ridge == "Y" else d) + 2 * eave
    run = (d if ridge == "Y" else w) + 2 * eave
    cap = (0, 0, h + 0.04)
    parts.append(_box("棟", cap, (0.2, run, 0.12) if ridge == "Y" else (run, 0.2, 0.12), "瓦"))
    # Tile courses: lines across each slope, from the eave up to the ridge.
    rows = max(3, int(math.hypot(span / 2, roof_h) / 0.3))
    for i in range(1, rows):
        t = i / rows
        z = wall_top + 0.12 + roof_h * t
        off = span / 2 * (1 - t)
        for side in (-1, 1):
            if ridge == "Y":
                parts.append(_box("瓦の段", (side * off, 0, z + 0.01), (0.03, run, 0.03), "瓦"))
            else:
                parts.append(_box("瓦の段", (0, side * off, z + 0.01), (run, 0.03, 0.03), "瓦"))
    floors = max(1, min(3, round((wall_top - footing) / 2.6)))
    storey = (wall_top - footing) / floors
    for f in range(floors):
        z0, z1 = footing + f * storey, footing + (f + 1) * storey
        n = max(1, int(w / 2.4))
        parts += _windows_on("front", w, d, z0, z1, n if f else max(1, n - 1), 1.2, 1.0 if f else 1.1, 0.9)
        parts += _windows_on("left", w, d, z0, z1, max(1, int(d / 3.2)), 0.9, 1.0, 0.9)
        parts += _windows_on("right", w, d, z0, z1, max(1, int(d / 3.2)), 0.9, 1.0, 0.9)
        if f:
            # A floor band between the storeys.
            parts.append(_box("胴差し", (0, 0, z0), (w + 0.06, d + 0.06, 0.12), "木"))
    door_x = w / 2 - min(1.4, w * 0.25)
    door_h = min(2.1, storey - 0.2)
    parts += [
        _box("玄関の枠", (door_x, -d / 2 - 0.03, footing + door_h / 2 + 0.05), (1.1, 0.06, door_h + 0.1), "木"),
        _box("ドア", (door_x, -d / 2 - 0.05, footing + door_h / 2), (0.9, 0.04, door_h), "木"),
        _box("ドアノブ", (door_x - 0.32, -d / 2 - 0.09, footing + 1.0), (0.08, 0.05, 0.05), "金属"),
        _box("ひさし", (door_x, -d / 2 - 0.45, footing + door_h + 0.25), (1.5, 0.9, 0.08), "金属"),
        _box("ポーチ", (door_x, -d / 2 - 0.5, footing / 2), (1.6, 1.0, footing), "コンクリート"),
    ]
    # A gutter along the front eave and a down pipe at the corner.
    parts.append(_cyl("雨どい", (0, -d / 2 - eave + 0.05, wall_top), (w + 2 * eave, 0.1, 0.1), "X", "金属"))
    parts.append(_cyl("縦どい", (-w / 2 - 0.08, -d / 2 - 0.08, wall_top / 2), (0.08, 0.08, wall_top), "Z", "金属"))
    return parts


def building(w, d, h, rnd) -> list[Part]:
    """A block of floors: slabs showing on the faces, rows of windows, a parapet, a stair house on the roof, an entrance."""
    floors = max(1, round(h / 3.2))
    storey = h / floors
    parts = [_box("外壁", (0, 0, h / 2), (w, d, h))]
    for f in range(floors):
        z0, z1 = f * storey, (f + 1) * storey
        if f:
            parts.append(_box("床の帯", (0, 0, z0), (w + 0.16, d + 0.16, 0.2), "コンクリート"))
        if f == 0:
            continue
        parts += _windows_on("front", w, d, z0, z1, max(1, int(w / 2.2)), 1.5, 1.4, 0.8)
        parts += _windows_on("left", w, d, z0, z1, max(1, int(d / 2.6)), 1.2, 1.4, 0.8)
        parts += _windows_on("right", w, d, z0, z1, max(1, int(d / 2.6)), 1.2, 1.4, 0.8)
    t = 0.2
    parts += [
        _box("パラペット", (0, -d / 2 + t / 2, h + 0.5), (w, t, 1.0), "コンクリート"),
        _box("パラペット", (0, d / 2 - t / 2, h + 0.5), (w, t, 1.0), "コンクリート"),
        _box("パラペット", (-w / 2 + t / 2, 0, h + 0.5), (t, d, 1.0), "コンクリート"),
        _box("パラペット", (w / 2 - t / 2, 0, h + 0.5), (t, d, 1.0), "コンクリート"),
    ]
    if w > 6 and d > 5:
        sx, sy = min(4.0, w * 0.25), min(4.0, d * 0.3)
        parts.append(_box("塔屋", (w * 0.2, d * 0.1, h + 1.4), (sx, sy, 2.8), "コンクリート"))
    ew = min(3.6, w * 0.4)
    ground = min(storey, 3.4)
    parts += [
        _box("入口のガラス", (0, -d / 2 - 0.03, ground * 0.4), (ew, 0.06, ground * 0.8), "ガラス"),
        _box("入口の枠", (0, -d / 2 - 0.05, ground * 0.4), (0.06, 0.06, ground * 0.8), "金属"),
        _box("庇", (0, -d / 2 - 0.8, ground * 0.88), (ew + 1.2, 1.6, 0.18), "コンクリート"),
    ]
    for i in (-1, 1):
        parts.append(
            _box(
                "1階の窓",
                (i * (ew / 2 + (w / 2 - ew / 2) / 2), -d / 2 - 0.03, ground * 0.5),
                ((w - ew) / 2 - 0.8, 0.06, ground * 0.55),
                "ガラス",
            )
        )
    return parts


def shed(w, d, h, rnd) -> list[Part]:
    """A shed or warehouse: corrugated walls, a low roof, a roller shutter and a small window."""
    wall_top = h * 0.82
    ridge = "X" if w >= d else "Y"
    parts = [
        _box("基礎", (0, 0, 0.1), (w + 0.04, d + 0.04, 0.2), "コンクリート"),
        _box("外壁", (0, 0, (0.2 + wall_top) / 2), (w, d, wall_top - 0.2)),
        {
            **_box("屋根", (0, 0, wall_top + (h - wall_top) / 2), (w + 0.4, d + 0.4, h - wall_top), "トタン"),
            "shape": "prism",
            "ridge": ridge,
        },
    ]
    sw, sh = min(w * 0.55, 4.0), min(wall_top - 0.5, 3.2)
    sx = -w * 0.12
    parts.append(_box("シャッターの枠", (sx, -d / 2 - 0.03, 0.2 + sh / 2), (sw + 0.2, 0.06, sh + 0.15), "金属"))
    slats = max(4, int(sh / 0.25))
    for i in range(slats):
        z = 0.2 + sh * (i + 0.5) / slats
        parts.append(_box("シャッター", (sx, -d / 2 - 0.05, z), (sw, 0.04, sh / slats * 0.8), "金属"))
    parts.append(_box("シャッターボックス", (sx, -d / 2 - 0.12, 0.2 + sh + 0.2), (sw + 0.2, 0.24, 0.3), "金属"))
    if w - sw > 2.0:
        x = sx + sw / 2 + (w / 2 - sx - sw / 2) / 2
        parts += [
            _box("窓枠", (x, -d / 2 - 0.03, 1.6), (0.9, 0.06, 0.8), "金属"),
            _box("窓ガラス", (x, -d / 2 - 0.045, 1.6), (0.78, 0.06, 0.68), "ガラス"),
        ]
    # Corrugation: thin ribs up the front wall.
    ribs = max(6, int(w / 0.35))
    for i in range(ribs):
        x = -w / 2 + w * (i + 0.5) / ribs
        if abs(x - sx) < sw / 2 + 0.1:
            continue
        parts.append(_box("波板", (x, -d / 2 - 0.012, (0.2 + wall_top) / 2), (0.03, 0.024, wall_top - 0.25), "トタン"))
    return parts


def _vehicle(length, width, h, kind) -> list[Part]:
    """A road vehicle with its length along X and its front toward +X: body, glass, wheels, bumpers, lights, mirrors."""
    r = min(0.34 if kind != "bus" else 0.5, h * 0.22)
    clear = r * 0.55
    belt = h * (0.5 if kind == "car" else 0.55)
    parts = []
    if kind == "car":
        hood = length * 0.28
        trunk = length * 0.2
        cabin = length - hood - trunk
        cx = -length / 2 + trunk + cabin / 2
        parts += [
            _box("車体", (0, 0, (clear + belt) / 2), (length, width, belt - clear)),
            _box("車室", (cx, 0, (belt + h) / 2), (cabin, width * 0.9, h - belt)),
            _box("フロントガラス", (cx + cabin / 2 + 0.01, 0, (belt + h) / 2), (0.03, width * 0.8, (h - belt) * 0.8), "ガラス"),
            _box("リアガラス", (cx - cabin / 2 - 0.01, 0, (belt + h) / 2), (0.03, width * 0.8, (h - belt) * 0.75), "ガラス"),
        ]
        glass_x, glass_len = cx, cabin
    elif kind == "truck":
        cab = min(length * 0.3, 2.0)
        parts += [
            _box("運転台", (length / 2 - cab / 2, 0, (clear + h) / 2), (cab, width, h - clear)),
            _box("荷台", (-cab / 2, 0, (clear + h * 0.95) / 2), (length - cab - 0.1, width, h * 0.95 - clear), "金属"),
            _box("フロントガラス", (length / 2 + 0.01, 0, (belt + h) / 2), (0.03, width * 0.8, (h - belt) * 0.8), "ガラス"),
        ]
        glass_x, glass_len = length / 2 - cab / 2, cab * 0.7
    else:
        # A van or a bus: one box, the windscreen leaning at the front, windows down the side.
        nose = length * (0.12 if kind == "van" else 0.03)
        parts += [
            _box("車体", (-nose / 2, 0, (clear + h) / 2), (length - nose, width, h - clear)),
            _box("ボンネット", (length / 2 - nose / 2, 0, (clear + belt) / 2), (nose, width, belt - clear)),
            _box("フロントガラス", (length / 2 - nose + 0.01, 0, (belt + h) / 2), (0.03, width * 0.85, (h - belt) * 0.8), "ガラス"),
        ]
        glass_x, glass_len = -nose / 2, length - nose - 0.4
    # Side windows (both sides), split into panes by pillars.
    panes = 2 if kind in ("car", "truck") else max(3, int(glass_len / 1.0))
    pane = glass_len / panes
    top = h - (h - belt) * 0.15
    for side in (-1, 1):
        for i in range(panes):
            x = glass_x - glass_len / 2 + pane * (i + 0.5)
            parts.append(
                _box("窓ガラス", (x, side * (width / 2 + 0.005), (belt + 0.05 + top) / 2), (pane * 0.86, 0.02, top - belt - 0.08), "ガラス")
            )
        # Door seams: thin strips.
        for x in (glass_x - glass_len / 4, glass_x + glass_len / 4):
            parts.append(
                _box("ドアの継ぎ目", (x, side * (width / 2 + 0.008), (clear + belt) / 2 + 0.05), (0.015, 0.012, belt - clear - 0.1))
            )
        parts.append(
            _box("ドアミラー", (length / 2 - length * 0.22, side * (width / 2 + 0.12), belt + 0.12), (0.12, 0.18, 0.14), "黒い塗装")
        )
    # Wheels and their hubs, set into the body's sides.
    for x in (length / 2 - length * 0.18, -length / 2 + length * 0.18):
        for side in (-1, 1):
            parts.append(_cyl("タイヤ", (x, side * (width / 2 - 0.1), r), (2 * r, 0.24, 2 * r), "Y", "黒い塗装"))
            parts.append(_cyl("ホイール", (x, side * (width / 2 + 0.025), r), (r, 0.03, r), "Y", "金属"))
            parts.append(_box("フェンダー", (x, side * (width / 2 + 0.01), clear + r * 1.25), (2 * r + 0.2, 0.03, 0.06)))
    parts += [
        _box("バンパー", (length / 2 + 0.05, 0, clear + 0.12), (0.12, width + 0.04, 0.22), "黒い塗装"),
        _box("バンパー", (-length / 2 - 0.05, 0, clear + 0.12), (0.12, width + 0.04, 0.22), "黒い塗装"),
        _box("ナンバー", (length / 2 + 0.12, 0, clear + 0.18), (0.02, 0.4, 0.15), "白壁"),
        _box("グリル", (length / 2 + 0.01, 0, clear + 0.38), (0.03, width * 0.5, 0.16), "黒い塗装"),
    ]
    for side in (-1, 1):
        parts.append(_box("ライト", (length / 2 + 0.02, side * width * 0.36, clear + 0.42), (0.04, width * 0.18, 0.12), "ガラス"))
        parts.append(_box("テールランプ", (-length / 2 - 0.02, side * width * 0.4, clear + 0.45), (0.04, width * 0.12, 0.2), "ガラス"))
    return parts


def _vehicle_in(w, d, h, kind) -> list[Part]:
    if w >= d:
        return _vehicle(w, d, h, kind)
    # Seen front on: the length runs away from the camera; the front (toward +X when made) turned to face −Y.
    parts = _vehicle(d, w, h, kind)
    out = []
    for p in parts:
        q = {**p, "c": [-p["c"][1], -p["c"][0], p["c"][2]], "s": [p["s"][1], p["s"][0], p["s"][2]]}
        if "axis" in p:
            q["axis"] = {"X": "Y", "Y": "X", "Z": "Z"}[p["axis"]]
        out.append(q)
    return out


def sofa(w, d, h, rnd) -> list[Part]:
    seat = h * 0.5
    arm = min(0.22, w * 0.12)
    back = min(0.22, d * 0.25)
    legs = 0.1
    parts = [
        _box("台", (0, 0, legs + (seat * 0.55 - legs) / 2), (w, d, seat * 0.55 - legs)),
        _box("背もたれ", (0, d / 2 - back / 2, legs + (h - legs) / 2), (w - 2 * arm, back, h - legs)),
        _box("ひじ掛け", (-w / 2 + arm / 2, 0, legs + (h * 0.72 - legs) / 2), (arm, d, h * 0.72 - legs)),
        _box("ひじ掛け", (w / 2 - arm / 2, 0, legs + (h * 0.72 - legs) / 2), (arm, d, h * 0.72 - legs)),
    ]
    n = max(1, round((w - 2 * arm) / 0.65))
    cw = (w - 2 * arm) / n
    for i in range(n):
        x = -w / 2 + arm + cw * (i + 0.5)
        parts.append(_box("座面のクッション", (x, -back / 2, seat * 0.55 + (seat * 0.45) / 2), (cw - 0.02, d - back - 0.02, seat * 0.45)))
        parts.append(_box("背のクッション", (x, d / 2 - back - 0.08, seat + (h - seat) * 0.45), (cw - 0.03, 0.16, (h - seat) * 0.8)))
    for x in (-w / 2 + 0.08, w / 2 - 0.08):
        for y in (-d / 2 + 0.08, d / 2 - 0.08):
            parts.append(_box("脚", (x, y, legs / 2), (0.05, 0.05, legs), "木"))
    return parts


def chair(w, d, h, rnd) -> list[Part]:
    seat = min(0.46, h * 0.52)
    t = 0.04
    parts = [_box("座面", (0, 0, seat - t / 2), (w, d, t))]
    for x in (-w / 2 + 0.03, w / 2 - 0.03):
        for y in (-d / 2 + 0.03, d / 2 - 0.03):
            parts.append(_box("脚", (x, y, (seat - t) / 2), (0.035, 0.035, seat - t)))
        parts.append(_box("背の柱", (x, d / 2 - 0.03, seat + (h - seat) / 2), (0.035, 0.035, h - seat)))
    parts.append(_box("背もたれ", (0, d / 2 - 0.03, seat + (h - seat) * 0.7), (w - 0.06, 0.025, (h - seat) * 0.45)))
    parts.append(_box("貫", (0, -d / 2 + 0.03, seat * 0.3), (w - 0.06, 0.02, 0.03)))
    return parts


def table(w, d, h, rnd) -> list[Part]:
    t = 0.04
    leg = 0.05
    parts = [_box("天板", (0, 0, h - t / 2), (w, d, t)), _box("幕板", (0, 0, h - t - 0.05), (w - 0.1, d - 0.1, 0.1))]
    for x in (-w / 2 + 0.06, w / 2 - 0.06):
        for y in (-d / 2 + 0.06, d / 2 - 0.06):
            parts.append(_box("脚", (x, y, (h - t) / 2), (leg, leg, h - t)))
    if w > 1.0 and d < 0.9:
        # A desk: a drawer under the top.
        parts.append(_box("引き出し", (w * 0.25, -0.02, h - t - 0.09), (w * 0.35, d - 0.12, 0.12)))
        parts.append(_box("取っ手", (w * 0.25, -d / 2 + 0.03, h - t - 0.09), (0.12, 0.02, 0.02), "金属"))
    return parts


def bed(w, d, h, rnd) -> list[Part]:
    """A bed with its head at the back (+Y)."""
    frame = h * 0.4
    return [
        _box("ベッドの枠", (0, 0, frame / 2), (w, d, frame), "木"),
        _box("マットレス", (0, -0.02, frame + 0.11), (w - 0.06, d - 0.12, 0.22), "布"),
        _box("掛け布団", (0, -d * 0.12, frame + 0.25), (w - 0.02, d * 0.7, 0.08), "布"),
        _box("枕", (0, d / 2 - 0.35, frame + 0.29), (min(0.7, w * 0.6), 0.4, 0.14), "布"),
        _box("ヘッドボード", (0, d / 2 - 0.03, h / 2), (w, 0.06, h), "木"),
    ]


def shelf(w, d, h, rnd) -> list[Part]:
    t = 0.025
    parts = [
        _box("側板", (-w / 2 + t / 2, 0, h / 2), (t, d, h)),
        _box("側板", (w / 2 - t / 2, 0, h / 2), (t, d, h)),
        _box("天板", (0, 0, h - t / 2), (w, d, t)),
        _box("背板", (0, d / 2 - 0.005, h / 2), (w, 0.01, h)),
    ]
    rows = max(2, round(h / 0.33))
    pitch = (h - t) / rows
    for i in range(rows):
        z = i * pitch
        parts.append(_box("棚板", (0, 0, z + t / 2), (w - 2 * t, d, t)))
        x = -w / 2 + t
        # Books, leaning against each other, of a few heights.
        while x < w / 2 - t - 0.03:
            bw = rnd.uniform(0.02, 0.05)
            bh = min(pitch - t - 0.02, rnd.uniform(0.17, 0.28))
            if rnd.random() < 0.12:
                x += bw * 2
                continue
            parts.append(_box("本", (x + bw / 2, -0.02, z + t + bh / 2), (bw - 0.002, d * 0.75, bh), "布"))
            x += bw
    return parts


def cabinet(w, d, h, rnd) -> list[Part]:
    parts = [_box("本体", (0, 0, h / 2), (w, d, h))]
    doors = 1 if w < 0.7 else 2
    split = h * 0.62 if h > 1.4 else h
    for i in range(doors):
        x = -w / 2 + w * (i + 0.5) / doors
        parts.append(_box("扉", (x, -d / 2 - 0.01, split / 2 + (h - split)), (w / doors - 0.02, 0.02, split - 0.02)))
        parts.append(
            _box(
                "取っ手",
                (
                    x + (0.4 - i * 0.8) * w / doors * (0 if doors == 1 else 1) - (0 if doors > 1 else w * 0.35),
                    -d / 2 - 0.035,
                    h - split / 2,
                ),
                (0.02, 0.03, 0.18),
                "金属",
            )
        )
    if split < h:
        parts.append(_box("引き出し", (0, -d / 2 - 0.01, (h - split) / 2), (w - 0.02, 0.02, h - split - 0.02)))
        parts.append(_box("取っ手", (0, -d / 2 - 0.035, (h - split) / 2), (0.2, 0.03, 0.02), "金属"))
    return parts


def stairs(w, d, h, rnd) -> list[Part]:
    """Steps going up away from the camera (toward +Y), with a side wall and a handrail."""
    steps = max(2, round(h / 0.18))
    rise, run = h / steps, d / steps
    parts = []
    for i in range(steps):
        y = -d / 2 + run * (i + 0.5)
        parts.append(_box("段", (0, y, rise * (i + 1) / 2), (w, run, rise * (i + 1)), "コンクリート"))
        parts.append(_box("段鼻", (0, y - run / 2 + 0.01, rise * (i + 1) - 0.01), (w, 0.03, 0.02), "金属"))
    for side in (-1, 1):
        parts.append(_cyl("手すり", (side * (w / 2 - 0.05), 0, h / 2 + 0.85), (0.05, math.hypot(d, h), 0.05), "Y", "金属"))
        for i in range(0, steps, max(1, steps // 4)):
            y = -d / 2 + run * (i + 0.5)
            parts.append(_cyl("手すりの柱", (side * (w / 2 - 0.05), y, rise * (i + 1) + 0.42), (0.04, 0.04, 0.85), "Z", "金属"))
    return parts


def fence(w, d, h, rnd) -> list[Part]:
    along_x = w >= d
    length = max(w, d)
    posts = max(2, int(length / 1.8) + 1)
    parts = []
    for i in range(posts):
        u = -length / 2 + length * i / (posts - 1)
        parts.append(_box("支柱", (u, 0, h / 2) if along_x else (0, u, h / 2), (0.06, 0.06, h), "金属"))
    for z in (h * 0.15, h * 0.55, h - 0.03):
        parts.append(_box("横桟", (0, 0, z), (length, 0.04, 0.04) if along_x else (0.04, length, 0.04), "金属"))
    return parts


def wall(w, d, h, rnd) -> list[Part]:
    """A block wall: the courses of blocks as lines, a coping on top."""
    parts = [
        _box("塀", (0, 0, h / 2), (w, d, h), "コンクリート"),
        _box("笠木", (0, 0, h + 0.03), (w + 0.04, d + 0.04, 0.06), "コンクリート"),
    ]
    courses = max(1, int(h / 0.2))
    along_x = w >= d
    for i in range(1, courses):
        z = i * h / courses
        parts.append(
            _box(
                "目地",
                (0, -d / 2 - 0.004, z) if along_x else (-w / 2 - 0.004, 0, z),
                (w, 0.01, 0.012) if along_x else (0.01, d, 0.012),
                "コンクリート",
            )
        )
    return parts


def pole(w, d, h, rnd) -> list[Part]:
    r = max(0.12, min(w, d) / 2)
    return [
        _cyl("柱", (0, 0, h / 2), (2 * r, 2 * r, h), "Z", "コンクリート"),
        _box("腕金", (0, 0, h * 0.9), (1.8, 0.08, 0.08), "金属"),
        _box("腕金", (0, 0, h * 0.82), (1.4, 0.08, 0.08), "金属"),
        _cyl("変圧器", (0.35, 0, h * 0.7), (0.4, 0.4, 0.7), "Z", "金属"),
        _box("足場ボルト", (0, -r, h * 0.5), (0.02, 0.2, 0.02), "金属"),
    ]


def tree(w, d, h, rnd) -> list[Part]:
    """A broadleaf tree: a tapering trunk with a few boughs, and a crown of many lumpy clusters of leaves
    (faceted, so the pen draws their outlines like a hand-drawn crown)."""
    trunk = h * 0.42
    r = max(0.1, min(w, d) * 0.06)
    parts = [
        _cyl("幹", (0, 0, trunk * 0.55 / 2), (2 * r, 2 * r, trunk * 0.55), "Z", "木"),
        _cyl("幹", (0, 0, trunk * 0.55 + trunk * 0.45 / 2), (1.5 * r, 1.5 * r, trunk * 0.45), "Z", "木"),
    ]
    for i in range(3):
        a = i * 2.1 + rnd.uniform(-0.4, 0.4)
        reach = min(w, d) * 0.22
        parts.append(
            {
                **_cyl(
                    "枝",
                    (math.cos(a) * reach / 2, math.sin(a) * reach / 2, trunk * rnd.uniform(0.85, 1.05)),
                    (r, r, reach * 1.2),
                    "Z",
                    "木",
                ),
                "tilt": [math.cos(a), math.sin(a)],
            }
        )
    crown = h - trunk * 0.75
    middle = trunk * 0.75 + crown * 0.5
    rx, ry, rz = w / 2, d / 2, crown / 2
    # A core that closes the crown (no sky through its middle), then clusters over its shell, overlapping, the
    # lower ones a little smaller (a crown is fuller on top and in the light).
    parts.append(_leaves((0, 0, middle), (rx * 1.3, ry * 1.3, rz * 1.3), rnd))
    clusters = 20 + rnd.randrange(8)
    for i in range(clusters):
        a = (i * 2.39996 + rnd.uniform(-0.3, 0.3)) % (2 * math.pi)  # golden angle: spread evenly round
        up = rnd.uniform(-0.6, 0.95)
        out = math.sqrt(max(0.0, 1 - up * up)) * rnd.uniform(0.55, 0.8)
        k = rnd.uniform(0.38, 0.55) * (0.85 if up < 0 else 1.0)
        parts.append(
            _leaves((math.cos(a) * out * rx, math.sin(a) * out * ry, middle + up * rz * 0.7), (rx * k * 2, ry * k * 2, rz * k * 1.6), rnd)
        )
    return parts


def _leaves(c, s, rnd) -> Part:
    """A cluster of leaves: a lumpy ball (its corners pushed in or out, seeded)."""
    return {**_box("葉", c, s, "草"), "shape": "sphere", "lumpy": round(rnd.uniform(0.08, 0.16), 3), "seed": rnd.randrange(1 << 16)}


def door(w, d, h, rnd) -> list[Part]:
    return [
        _box("ドア枠", (0, 0, h / 2), (w, d, h), "木"),
        _box("ドア", (0, -d / 2 - 0.01, (h - 0.06) / 2), (w - 0.12, 0.03, h - 0.06), "木"),
        _box("ドアノブ", (w / 2 - 0.15, -d / 2 - 0.05, h * 0.45), (0.1, 0.05, 0.04), "金属"),
    ]


def tv(w, d, h, rnd) -> list[Part]:
    screen_h = h * 0.75
    return [
        _box("画面の枠", (0, 0, h - screen_h / 2), (w, min(d, 0.06), screen_h), "黒い塗装"),
        _box("画面", (0, -min(d, 0.06) / 2 - 0.003, h - screen_h / 2), (w - 0.04, 0.006, screen_h - 0.04), "ガラス"),
        _box("スタンド", (0, 0, (h - screen_h) / 2), (0.06, 0.06, h - screen_h), "金属"),
        _box("台座", (0, 0, 0.01), (w * 0.4, d, 0.02), "金属"),
    ]


def bench(w, d, h, rnd) -> list[Part]:
    seat = min(0.45, h * 0.55)
    parts = []
    for i in range(3):
        parts.append(_box("座板", (0, -d / 2 + d * (i + 0.5) / 3, seat), (w, d / 3 - 0.02, 0.035), "木"))
    for i in range(2):
        parts.append(_box("背板", (0, d / 2 - 0.03, seat + 0.15 + i * 0.18), (w, 0.03, 0.12), "木"))
    for x in (-w / 2 + 0.1, w / 2 - 0.1):
        parts.append(_box("脚", (x, 0, seat / 2), (0.05, d, seat), "金属"))
        parts.append(_box("背の支え", (x, d / 2 - 0.05, seat + (h - seat) / 2), (0.05, 0.04, h - seat), "金属"))
    return parts


def counter(w, d, h, rnd) -> list[Part]:
    return [
        _box("本体", (0, 0, (h - 0.04) / 2), (w, d, h - 0.04)),
        _box("天板", (0, -0.03, h - 0.02), (w + 0.04, d + 0.06, 0.04), "木"),
        _box("幅木", (0, -d / 2 - 0.005, 0.05), (w, 0.01, 0.1), "木"),
        *[_box("腰板の目地", (-w / 2 + w * (i + 1) / 4, -d / 2 - 0.005, (h - 0.04) / 2), (0.01, 0.01, h - 0.2)) for i in range(3)],
    ]


BUILDERS = {
    "house": house,
    "building": building,
    "shed": shed,
    "van": lambda w, d, h, rnd: _vehicle_in(w, d, h, "van"),
    "car": lambda w, d, h, rnd: _vehicle_in(w, d, h, "car"),
    "truck": lambda w, d, h, rnd: _vehicle_in(w, d, h, "truck"),
    "bus": lambda w, d, h, rnd: _vehicle_in(w, d, h, "bus"),
    "sofa": sofa,
    "chair": chair,
    "table": table,
    "bed": bed,
    "shelf": shelf,
    "cabinet": cabinet,
    "stairs": stairs,
    "fence": fence,
    "wall": wall,
    "pole": pole,
    "tree": tree,
    "door": door,
    "tv": tv,
    "bench": bench,
    "counter": counter,
}
