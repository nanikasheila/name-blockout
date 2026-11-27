# SPDX-License-Identifier: GPL-3.0-or-later
"""What lies round a place: a town (市街地), as data (nothing here needs Blender).

A place (a house on its lot, a street corner) ends somewhere, and a picture looking down on it shows the ground
beyond: white, unless the author says what is there. `shot.surroundings` {"kind": "town"} lays houses there, on
streets square to the world's axes (so their edges run to the picture's vanishing points), made from a seed: the
same instruction gives the same town.

- a street every BLOCK_DEEP_M (two rows of plots back to back, each plot's house facing its street) and a cross
  street at the end of each block (BLOCK_LONG_M, four to six plots);
- on a plot a house (two storeys with a gable roof; some of one storey, some flat-roofed, now and then a block of
  flats), sometimes a tree in its garden, now and then nothing (a car park, a field);
- utility poles along the streets.

The town never hides the place: along each direction from the camera it starts beyond the farthest thing the place
(and the author's own things) has there, a street's width farther, and nothing of it stands on the place's own
ground (`beyond`). What stands between the camera and the place is the author's to put.
"""

from __future__ import annotations

import math
import random

from .camera import Camera
from .far import FAR_M, view_azimuths

KINDS = ("town", "open")
KIND_LABELS = {"town": "市街地", "open": "何も置かない（白い地面）"}
#: A street's width, a plot's depth (street to back fence) and widths, and how many plots make a block.
STREET_M = 6.0
PLOT_DEEP_M = 13.0
BLOCK_LONG_M = 60.0
BLOCK_PLOTS = (4, 6)
BLOCK_DEEP_M = 2 * PLOT_DEEP_M + STREET_M
#: The town is laid out to here (the far band's layers take over beyond), and no more than this many houses,
#: the nearest first.
REACH_M = FAR_M
MAX_HOUSES = 160
#: Past where the picture's top edge meets the ground, a house this much farther could still show its roof.
REACH_BEYOND_SEEN_M = 20.0
#: Nothing of the town stands within this of the place's own ground (its lot, its lawn).
GROUND_CLEAR_M = 1.0
POLE_EVERY_M = 30.0
POLE_M = 9.5
#: Directions (degrees) a place's reach is spread over, so a thing's edge keeps a house off it on both sides.
SPREAD_DEG = 3


def seen_reach(camera: Camera) -> float:
    """How far off the ground the picture shows goes: to where its edges meet the ground (and a little more: a
    roof stands above its ground), or REACH_M when the horizon is in the picture."""
    far = 0.0
    w, h = camera.width, camera.height
    for i in range(9):
        for q in ((w * i / 8, 0.0), (0.0, h * i / 8), (float(w), h * i / 8)):
            p = camera.ground_point(q)
            if p is None:
                return REACH_M
            far = max(far, math.hypot(p[0] - camera.position[0], p[1] - camera.position[1]))
    return min(REACH_M, far + REACH_BEYOND_SEEN_M)


def _rng(seed: int, *keys: int) -> random.Random:
    value = seed & 0xFFFFFFFF
    for k in keys:
        value = (value * 1_000_003 + (k & 0xFFFFFFFF) + 0x9E3779B9) & 0xFFFFFFFFFFFF
    return random.Random(value)


def _row_blocks(seed: int, row: int, x0: float, x1: float):
    """The blocks of a row between x0 and x1: (block number, its west end, its plots' widths). Blocks stand at a
    fixed pitch from the row's own start, so a block is the same whatever part of the row is asked for."""
    # Each row's cross streets are shifted (a town's streets do not all run through), by a seeded amount.
    shift = _rng(seed, row, 7).uniform(0.0, BLOCK_LONG_M)
    pitch = BLOCK_LONG_M + STREET_M
    out = []
    for k in range(math.floor((x0 - shift) / pitch), math.floor((x1 - shift) / pitch) + 1):
        rng = _rng(seed, row, k)
        shares = [rng.uniform(1.0, 1.35) for _ in range(rng.randint(*BLOCK_PLOTS))]
        out.append((k, shift + k * pitch, [round(BLOCK_LONG_M * v / sum(shares), 2) for v in shares]))
    return out


def _house(rng: random.Random, x0: float, wide: float, street_y: float, faces: int) -> dict | None:
    """What stands on a plot `wide` across from x0, its street at street_y (to the south when faces is −1)."""
    roll = rng.random()
    if roll < 0.07:
        return None  # a car park, a field
    flats = roll > 0.93 and wide > 12.0
    if flats:
        w, d, floors = wide - 2.0, rng.uniform(7.5, 9.0), 3
        h = floors * 2.9 + 0.3
        roof = "flat"
    else:
        w = wide - rng.uniform(2.6, 4.4)
        d = rng.uniform(6.8, 9.2)
        floors = 1 if rng.random() < 0.15 else 2
        roof = "flat" if rng.random() < 0.12 else "gable"
        eaves = floors * 2.8 + 0.4
        h = eaves + (0.3 if roof == "flat" else rng.uniform(1.5, 2.3))
    back = rng.uniform(2.0, 3.6)  # the front garden
    cx = x0 + wide / 2 + rng.uniform(-0.5, 0.5)
    cy = street_y - faces * (back + d / 2)
    return {
        "centreM": [round(cx, 2), round(cy, 2), 0.0],
        "sizeM": [round(w, 2), round(d, 2), round(h, 2)],
        "front": "-Y" if faces < 0 else "+Y",
        "roof": roof,
        "ridge": "X" if w >= d else "Y",
        "floors": floors,
        "wall": rng.choice(("白壁", "白壁", "白壁", "コンクリート", "木")) if not flats else "コンクリート",
        "top": ("コンクリート" if roof == "flat" else rng.choice(("瓦", "瓦", "トタン"))),
        "balcony": (not flats) and floors == 2 and rng.random() < 0.45,
        "seed": rng.randrange(1 << 16),
    }


def town(camera: Camera, spec: dict | None = None, reach: float | None = None) -> dict:
    """A town round the camera's view: houses, garden trees and utility poles, within the directions the picture
    sees and `reach` (default: as far as the picture shows ground). Everything stands on the ground (z 0), square
    to the world's axes."""
    spec = spec or {}
    seed = int(spec.get("seed") or 0)
    reach = float(spec.get("reachM") or reach or seen_reach(camera))
    px, py = camera.position[0], camera.position[1]
    lo, hi = (math.radians(a) for a in view_azimuths(camera, margin_deg=6.0))
    all_round = hi - lo >= 2 * math.pi - 1e-6

    def within(x: float, y: float) -> float | None:
        dist = math.hypot(x - px, y - py)
        if dist > reach:
            return None
        if not all_round and dist > 1e-6:
            a = (math.atan2(y - py, x - px) - lo) % (2 * math.pi)
            if a > hi - lo:
                return None
        return dist

    houses, trees, poles = [], [], []
    row0 = math.floor((py - reach) / BLOCK_DEEP_M) - 1
    row1 = math.floor((py + reach) / BLOCK_DEEP_M) + 1
    for row in range(row0, row1 + 1):
        # The row's street runs along X at its south side; its two rows of plots face south and north (the next
        # row's street).
        south = row * BLOCK_DEEP_M + STREET_M / 2
        north = (row + 1) * BLOCK_DEEP_M - STREET_M / 2
        for block, x_start, plots in _row_blocks(seed, row, px - reach, px + reach):
            for side, (street_y, faces) in enumerate(((south, -1), (north, 1))):
                x = x_start
                for i, wide in enumerate(plots):
                    rng = _rng(seed, row, block, side * 100 + i)
                    house = _house(rng, x, wide, street_y, faces)
                    centre_y = street_y - faces * PLOT_DEEP_M / 2
                    if house is not None:
                        dist = within(house["centreM"][0], house["centreM"][1])
                        if dist is not None:
                            houses.append({"id": f"r{row}b{block}s{side}p{i}", **house, "distanceM": round(dist, 1)})
                    if rng.random() < (0.35 if house else 0.5):
                        # A garden tree at the back of the plot (or in the open plot).
                        tx = x + rng.uniform(1.5, wide - 1.5)
                        ty = street_y - faces * (PLOT_DEEP_M - rng.uniform(1.2, 2.2)) if house else centre_y
                        if within(tx, ty) is not None:
                            height = rng.uniform(3.0, 6.5)
                            form = "conifer" if rng.random() < 0.15 else "broad"
                            trees.append(
                                {
                                    "centreM": [round(tx, 2), round(ty, 2), 0.0],
                                    "heightM": round(height, 2),
                                    "radiusM": round(height * (0.2 if form == "conifer" else rng.uniform(0.3, 0.42)), 2),
                                    "form": form,
                                    "seed": rng.randrange(1 << 16),
                                }
                            )
                    x += wide
        # Poles along the street's north side.
        first = math.ceil((px - reach) / POLE_EVERY_M)
        for n in range(first, math.floor((px + reach) / POLE_EVERY_M) + 1):
            x, y = n * POLE_EVERY_M + (row % 3) * 4.0, south - 0.6
            if within(x, y) is not None:
                poles.append({"centreM": [round(x, 2), round(y, 2), 0.0], "heightM": POLE_M})
    houses.sort(key=lambda b: (b["distanceM"], b["id"]))
    return {
        "kind": "town",
        "seed": seed,
        "reachM": round(reach, 1),
        "streetM": STREET_M,
        "houses": houses[:MAX_HOUSES],
        "trees": trees[: MAX_HOUSES * 2],
        "poles": poles[:MAX_HOUSES],
    }


def rect(house: dict, margin: float = 0.0) -> list[list[float]]:
    """A house's footprint (its four corners), `margin` wider all round."""
    (x, y, _), (w, d, _) = house["centreM"], house["sizeM"]
    a, b = w / 2 + margin, d / 2 + margin
    return [[x - a, y - b], [x + a, y - b], [x + a, y + b], [x - a, y + b]]


def place_reach(points, origin) -> dict[int, float]:
    """How far the place goes, by direction from `origin` (whole degrees from +X): the farthest of its points
    there, spread over SPREAD_DEG to each side."""
    far: dict[int, float] = {}
    for x, y in points:
        dx, dy = x - origin[0], y - origin[1]
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            continue
        a = int(math.floor(math.degrees(math.atan2(dy, dx)))) % 360
        for k in range(a - SPREAD_DEG, a + SPREAD_DEG + 1):
            far[k % 360] = max(far.get(k % 360, 0.0), dist)
    return far


def _starts(far: dict[int, float], x: float, y: float, origin) -> float:
    """Where the town may start in the direction of (x, y): past the place there; where the place has nothing in
    that direction, past what it has in the nearest direction where it has something."""
    if not far:
        return 0.0
    a = int(math.floor(math.degrees(math.atan2(y - origin[1], x - origin[0])))) % 360
    for step in range(181):
        found = [far[k % 360] for k in (a - step, a + step) if k % 360 in far]
        if found:
            return max(found)
    return 0.0


def beyond(made: dict, points, origin, gap: float | None = None, grounds=()) -> dict:
    """The town with only what stands beyond the place (its things' `points`, x and y) as seen from `origin` (the
    camera): a house is kept when all its corners are past the place in their directions by `gap` (a street's
    width); trees and poles by where they stand. Nothing stands on the place's own `grounds` (its lot, its lawn:
    each as x0, y0, x1, y1). `dropped` counts what was left out."""
    gap = made.get("streetM", STREET_M) if gap is None else gap
    far = place_reach(points, origin)

    def past(x: float, y: float) -> bool:
        if any(
            x0 - GROUND_CLEAR_M < x < x1 + GROUND_CLEAR_M and y0 - GROUND_CLEAR_M < y < y1 + GROUND_CLEAR_M for x0, y0, x1, y1 in grounds
        ):
            return False
        return math.hypot(x - origin[0], y - origin[1]) > _starts(far, x, y, origin) + gap

    houses = [h for h in made["houses"] if all(past(x, y) for x, y in rect(h))]
    trees = [t for t in made["trees"] if past(t["centreM"][0], t["centreM"][1])]
    poles = [p for p in made["poles"] if past(p["centreM"][0], p["centreM"][1])]
    dropped = {
        "houses": made.get("dropped", {}).get("houses", 0) + len(made["houses"]) - len(houses),
        "trees": made.get("dropped", {}).get("trees", 0) + len(made["trees"]) - len(trees),
        "poles": made.get("dropped", {}).get("poles", 0) + len(made["poles"]) - len(poles),
    }
    return {**made, "houses": houses, "trees": trees, "poles": poles, "dropped": dropped}


def town_words(made: dict) -> str:
    """One line on the town as made."""
    if not made["houses"]:
        return "まわりは市街地: 絵に見える範囲に家は入りませんでした（場所の向こう側が絵に出ていないか、場所の地面が絵の端まで続いている）"
    near, far = made["houses"][0]["distanceM"], made["houses"][-1]["distanceM"]
    return (
        f"まわりは市街地: 家 {len(made['houses'])} 軒（カメラから {near:.0f}〜{far:.0f} m）"
        f"・庭木 {len(made['trees'])} 本・電柱 {len(made['poles'])} 本。場所の物より向こう、場所の地面の外にだけ置く（道幅 {made['streetM']:g} m あけて）"
    )
