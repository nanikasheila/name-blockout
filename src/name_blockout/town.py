# SPDX-License-Identifier: GPL-3.0-or-later
"""What lies round a place: a town (市街地), as data (nothing here needs Blender).

A place (a house on its lot, a street corner) ends somewhere, and a picture looking down on it shows the ground
beyond: white, unless the author says what is there. `shot.surroundings` {"kind": "town"} lays houses there, on
streets square to the world's axes (so their edges run to the picture's vanishing points), made from a seed: the
same instruction gives the same town.

- a street every BLOCK_DEEP_M (two rows of plots back to back, each plot's house facing its street) and a cross
  street at the end of each block (BLOCK_LONG_M, five to seven plots); the streets run along the world's X, or its
  Y, and one of them through a given place, as wide as given (`street`: {"axis", "atM", "widthM"}), so the
  town's streets carry on the place's own road;
- the town is a Japanese residential quarter (住宅街: the author's stories are set in Japan, and a townscape tells
  where a story is): narrow streets with no pavement, small plots walled to the street and to each other (block
  walls, hedges, gateposts), houses close together and close to the street (two storeys, tiled gable and hipped
  roofs, a lower roof over a wider ground floor, a balcony, wide sliding windows, a porch), a car in the plot's
  car space, now and then a block of flats (balconies along every floor) or a car park;
- utility poles along the streets' edges, with their cross-arms, transformers and the wires from pole to pole.

The town never hides the place: along each direction from the camera it starts beyond the farthest thing the place
(and the author's own things) has there, a street's width farther; nothing of it stands among the place's things
(within the outline drawn round them all, a street's width off) or on the place's own lot (`beyond`; a ground of
the place wider than LOT_MAX_M is land, not a lot: the town stands on it). Nor does it come into the near band
(NEAR_M from the camera): what stands near, and between the camera and the place, is the author's to put.
"""

from __future__ import annotations

import math
import random

from .camera import Camera
from .far import FAR_M, NEAR_M, view_azimuths

KINDS = ("town", "open")
KIND_LABELS = {"town": "市街地", "open": "何も置かない（白い地面）"}
#: A street's width (a residential street: two cars pass, no pavement), a plot's depth (street to back wall) and
#: how many plots make a block (each 8.5–12 m wide).
STREET_M = 5.0
PLOT_DEEP_M = 14.0
BLOCK_LONG_M = 60.0
BLOCK_PLOTS = (5, 7)
BLOCK_DEEP_M = 2 * PLOT_DEEP_M + STREET_M
#: A house: the footing below its ground floor, and a storey's height.
FOOTING_M = 0.4
STOREY_M = 2.8
#: A car space's width along the street, how far back a house stands behind one, and a gate's width.
CAR_SPACE_M = 2.9
CAR_DEEP_M = 5.3
GATE_M = 1.1
#: A boundary wall's thickness (a block wall), and a hedge's.
WALL_THICK_M = 0.12
HEDGE_THICK_M = 0.5
#: The cars that stand in a town: across, long, high (m).
CARS = {"kei": (1.48, 3.4, 1.72), "compact": (1.7, 4.0, 1.55), "minivan": (1.75, 4.7, 1.85), "sedan": (1.75, 4.6, 1.45)}
#: The town is laid out to here (the far band's layers take over beyond), and no more than this many houses,
#: the nearest first.
REACH_M = FAR_M
MAX_HOUSES = 220
#: Past where the picture's top edge meets the ground, a house this much farther could still show its roof.
REACH_BEYOND_SEEN_M = 20.0
#: Nothing of the town stands within this of the place's own lot (its ground, its lawn)…
GROUND_CLEAR_M = 1.0
#: …and a ground of the place longer than this is no lot but the land the place was modelled on (a plane out to
#: the horizon): the town stands on it.
LOT_MAX_M = 100.0
AXES = ("X", "Y")
#: Utility poles: one every so far along a street, standing in the street at its edge (before the plots' walls),
#: so high; the wires between them are drawn up to WIRE_REACH_M from the camera (farther off a wire is no line).
POLE_EVERY_M = 30.0
POLE_IN_STREET_M = 0.25
POLE_M = 10.0
WIRE_REACH_M = 100.0
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


def _plot(rng: random.Random, x0: float, wide: float, street_y: float, faces: int, back_wall: bool, last: bool) -> dict:
    """What stands on a plot `wide` across from x0, its street at street_y (to the south when faces is −1), in the
    town's own frame (its streets along x): its house (sizeM is the house's own: across its front, deep, high),
    the walls and hedges on its boundaries, its gateposts, the car in its car space, its trees and bushes.

    The plot's boundary to its left is its own, the one to its right when it is its block's `last`, the one at its
    back when `back_wall` (one of the two rows that stand back to back)."""

    def v(t: float) -> float:
        return street_y - faces * t

    deep = PLOT_DEEP_M
    out: dict = {"house": None, "walls": [], "hedges": [], "posts": [], "cars": [], "trees": []}

    def wall(a0: float, t0: float, a1: float, t1: float, high: float, kind: str = "block") -> None:
        item = {"fromM": [round(a0, 2), round(v(t0), 2)], "toM": [round(a1, 2), round(v(t1), 2)], "heightM": round(high, 2), "kind": kind}
        out["hedges" if kind == "hedge" else "walls"].append(item)

    def car(a: float, t: float, present: float) -> None:
        if rng.random() < present:
            kind = rng.choice(("kei", "kei", "compact", "compact", "minivan", "sedan"))
            out["cars"].append(
                {
                    "centreM": [round(a, 2), round(v(t), 2), 0.0],
                    "sizeM": list(CARS[kind]),
                    "kind": kind,
                    "paint": rng.choice(("白壁", "白壁", "金属", "金属", "黒い塗装")),
                }
            )

    def tree(a: float, t: float, form: str, height: float) -> None:
        spread = {"conifer": 0.2, "bush": rng.uniform(0.5, 0.7)}.get(form) or rng.uniform(0.3, 0.42)
        out["trees"].append(
            {
                "centreM": [round(a, 2), round(v(t), 2), 0.0],
                "heightM": round(height, 2),
                "radiusM": round(height * spread, 2),
                "form": form,
                "seed": rng.randrange(1 << 16),
            }
        )

    side_high = rng.uniform(1.2, 1.6)
    wall(x0, 0.0, x0, deep, side_high)
    if last:
        wall(x0 + wide, 0.0, x0 + wide, deep, side_high)
    if back_wall:
        wall(x0, deep, x0 + wide, deep, rng.uniform(1.4, 1.8))

    roll = rng.random()
    if roll < 0.06:
        # A car park (月極駐車場), open to the street; now and then an empty lot with a tree.
        if rng.random() < 0.7:
            for i in range(int((wide - 0.6) // 2.7)):
                car(x0 + 0.3 + 2.7 * (i + 0.5), 3.0, 0.6)
        else:
            tree(x0 + wide / 2, deep / 2, "broad", rng.uniform(3.0, 6.0))
        return out
    seed = rng.randrange(1 << 16)
    if roll > 0.92 and wide >= 9.5:
        # A block of flats (アパート・マンション): cars before it, balconies along every floor of its front, an open
        # corridor and its stairs behind.
        floors = rng.choice((2, 2, 3, 3, 4))
        back = rng.uniform(5.2, 5.6)
        w, d = wide - 2.0, deep - back - 2.2
        for i in range(int(wide // 2.8)):
            car(x0 + (wide - 2.8 * int(wide // 2.8)) / 2 + 2.8 * (i + 0.5), 2.8, 0.55)
        out["house"] = {
            "kind": "flats",
            "centreM": [round(x0 + wide / 2, 2), round(v(back + d / 2), 2), 0.0],
            "sizeM": [round(w, 2), round(d, 2), round(FOOTING_M + floors * STOREY_M + 0.3, 2)],
            "front": "-Y" if faces < 0 else "+Y",
            "roof": "flat",
            "ridge": "along",
            "floors": floors,
            "units": max(2, round(w / 5.5)),
            "stairs": rng.choice((-1, 1)),
            "wall": rng.choice(("白壁", "コンクリート")),
            "top": "コンクリート",
            "seed": seed,
        }
        return out

    # A house. With a car space the house stands back behind it; else close to the street behind its wall.
    has_car = wide >= 8.4 and rng.random() < 0.65
    back = rng.uniform(CAR_DEEP_M, CAR_DEEP_M + 0.6) if has_car else rng.uniform(1.3, 2.4)
    w = wide - rng.uniform(1.6, 2.6)
    d = min(rng.uniform(6.8, 8.8), deep - back - 1.0)
    floors = 1 if rng.random() < 0.08 else 2
    pick = rng.random()
    roof = "gable" if pick < 0.45 else ("hip" if pick < 0.88 else "flat")
    cx = x0 + wide / 2 + rng.uniform(-0.25, 0.25)
    # The upper storey over a part of the ground floor (at its back, to one side): the rest under a lower roof (下屋).
    upper = None
    uw, ud = w, d
    if floors == 2 and roof != "flat" and rng.random() < 0.5:
        uw, ud = round(w * rng.uniform(0.6, 0.8), 2), round(d * rng.uniform(0.72, 1.0), 2)
        upper = {"sizeM": [uw, ud], "side": rng.choice((-1, 1))}
    eaves = FOOTING_M + floors * STOREY_M
    high = eaves + (0.3 if roof == "flat" else min(uw, ud) / 2 * rng.uniform(0.38, 0.5))
    door = rng.uniform(-w / 2 + 0.9, w / 2 - 0.9)
    balcony = None
    if floors == 2 and rng.random() < 0.7:
        across = min(uw - 0.6, rng.uniform(2.7, 4.5))
        centre = (upper["side"] * (w - uw) / 2 if upper else 0.0) + rng.uniform(-(uw - across) / 2 + 0.2, (uw - across) / 2 - 0.2)
        balcony = {"wM": round(across, 2), "atM": round(centre, 2)}
    out["house"] = {
        "kind": "house",
        "centreM": [round(cx, 2), round(v(back + d / 2), 2), 0.0],
        "sizeM": [round(w, 2), round(d, 2), round(high, 2)],
        "front": "-Y" if faces < 0 else "+Y",
        "roof": roof,
        "ridge": "along" if uw >= ud else "across",  # along its front, or from front to back
        "floors": floors,
        "upper": upper,
        "balcony": balcony,
        "doorM": round(door, 2),
        "wall": rng.choice(("白壁", "白壁", "白壁", "白壁", "コンクリート", "木")),
        "top": "コンクリート" if roof == "flat" else rng.choice(("瓦", "瓦", "瓦", "トタン")),
        "seed": seed,
    }
    # The plot's front: a car space open to the street at one end, the rest walled (a block wall, a hedge, a low
    # kerb, now and then nothing), with a gate before the door.
    opens = []
    if has_car:
        at = x0 + 0.25 + CAR_SPACE_M / 2 if rng.random() < 0.5 else x0 + wide - 0.25 - CAR_SPACE_M / 2
        opens.append((at - CAR_SPACE_M / 2, at + CAR_SPACE_M / 2))
        car(at, back / 2 + 0.2, 0.7)
    kind = rng.choices(("block", "hedge", "low", "none"), (0.55, 0.15, 0.2, 0.1))[0]
    front_high = {"block": rng.uniform(1.1, 1.5), "hedge": rng.uniform(1.2, 1.7), "low": rng.uniform(0.4, 0.6), "none": 0.0}[kind]
    gate = cx - faces * door  # the house's own x runs along the town's when it faces −Y, against it when +Y
    gate = min(max(gate, x0 + GATE_M), x0 + wide - GATE_M)
    in_car_space = any(a0 - 0.3 < gate < a1 + 0.3 for a0, a1 in opens)
    if not in_car_space:
        opens.append((gate - GATE_M / 2, gate + GATE_M / 2))
    if kind != "none":
        at = x0
        for a0, a1 in sorted(opens) + [(x0 + wide, x0 + wide)]:
            if a0 - at > 0.4:
                wall(at, WALL_THICK_M / 2, a0, WALL_THICK_M / 2, front_high, "block" if kind == "low" else kind)
            at = max(at, a1)
        if kind in ("block", "hedge") and not in_car_space:
            for a in (gate - GATE_M / 2 - 0.2, gate + GATE_M / 2 + 0.2):
                out["posts"].append({"centreM": [round(a, 2), round(v(0.2), 2), 0.0], "sizeM": [0.4, 0.4, round(front_high + 0.15, 2)]})
    # A garden tree at the back of the plot, a bush or two in the front garden.
    if rng.random() < 0.35 and deep - back - d > 1.6:
        form = "conifer" if rng.random() < 0.1 else "broad"
        tree(x0 + rng.uniform(1.5, wide - 1.5), deep - rng.uniform(1.0, 1.4), form, rng.uniform(3.0, 5.5))
    for _ in range(rng.choice((0, 1, 1, 2))):
        a, t = x0 + rng.uniform(0.8, wide - 0.8), rng.uniform(0.7, max(0.8, back - 0.6))
        if not any(a0 - 0.6 < a < a1 + 0.6 for a0, a1 in opens):
            tree(a, t, "bush", rng.uniform(0.8, 1.5))
    return out


def street_of(spec: dict | None) -> tuple[str, float, float]:
    """The town's streets: the axis they run along, where one of them runs through (y for X, x for Y), and how wide
    they are (the cross streets keep STREET_M)."""
    street = (spec or {}).get("street") or {}
    axis = street.get("axis") if street.get("axis") in AXES else "X"
    return axis, float(street.get("atM") or 0.0), float(street.get("widthM") or STREET_M)


def town(camera: Camera, spec: dict | None = None, reach: float | None = None) -> dict:
    """A town round the camera's view: houses, garden trees and utility poles, within the directions the picture
    sees and `reach` (default: as far as the picture shows ground). Everything stands on the ground (z 0), square
    to the world's axes; the streets as `street_of(spec)` says."""
    spec = spec or {}
    seed = int(spec.get("seed") or 0)
    reach = float(spec.get("reachM") or reach or seen_reach(camera))
    axis, through, wide_street = street_of(spec)
    deep = 2 * PLOT_DEEP_M + wide_street  # from one street's middle to the next
    px, py = camera.position[0], camera.position[1]
    lo, hi = (math.radians(a) for a in view_azimuths(camera, margin_deg=6.0))
    all_round = hi - lo >= 2 * math.pi - 1e-6

    # The town is laid out in its own frame (u along its streets, v across them, a street's middle on v = 0) and
    # turned into the world's: u is x and v is y − through, or (streets along Y) u is y and v is x − through.
    def world(u: float, v: float) -> tuple[float, float]:
        return (u, v + through) if axis == "X" else (v + through, u)

    pu, pv = (px, py - through) if axis == "X" else (py, px - through)
    fronts = {-1: "-Y", 1: "+Y"} if axis == "X" else {-1: "-X", 1: "+X"}

    def within(u: float, v: float) -> float | None:
        x, y = world(u, v)
        dist = math.hypot(x - px, y - py)
        if dist > reach:
            return None
        if not all_round and dist > 1e-6:
            a = (math.atan2(y - py, x - px) - lo) % (2 * math.pi)
            if a > hi - lo:
                return None
        return dist

    def at(u: float, v: float) -> list[float]:
        x, y = world(u, v)
        return [round(x, 2), round(y, 2), 0.0]

    def clear_of_near(u: float, v: float) -> bool:
        # Not in the near band: what stands near is drawn in the name, and the author's.
        return (within(u, v) or 0.0) > NEAR_M

    houses, trees, poles, streets = [], [], [], []
    walls, hedges, posts, cars, wires = [], [], [], [], []
    toward_street = [0.0, -1.0] if axis == "X" else [-1.0, 0.0]
    row0 = math.floor((pv - reach) / deep) - 1
    row1 = math.floor((pv + reach) / deep) + 1
    other = "Y" if axis == "X" else "X"
    for row in range(row0, row1 + 1):
        # The row's street runs along u with its middle on the row's line; the row's two lines of plots face it
        # (from its far side) and the next row's street.
        south = row * deep + wide_street / 2
        north = (row + 1) * deep - wide_street / 2
        streets.append(
            {
                "axis": axis,
                "atM": round(row * deep + through, 2),
                "fromM": round(pu - reach, 1),
                "toM": round(pu + reach, 1),
                "widthM": wide_street,
            }
        )
        crossings = []
        for block, x_start, plots in _row_blocks(seed, row, pu - reach, pu + reach):
            # The cross street at the block's end, from this row's street to the next.
            crossings.append((x_start + BLOCK_LONG_M, x_start + BLOCK_LONG_M + STREET_M))
            streets.append(
                {
                    "axis": other,
                    "atM": round(x_start + BLOCK_LONG_M + STREET_M / 2, 2),
                    "fromM": round(row * deep + through, 2),
                    "toM": round((row + 1) * deep + through, 2),
                    "widthM": STREET_M,
                }
            )
            for side, (street_y, faces) in enumerate(((south, -1), (north, 1))):
                x = x_start
                for i, wide in enumerate(plots):
                    rng = _rng(seed, row, block, side * 100 + i)
                    plot = _plot(rng, x, wide, street_y, faces, back_wall=side == 0, last=i == len(plots) - 1)
                    x += wide
                    house = plot["house"]
                    if house is not None:
                        dist = within(house["centreM"][0], house["centreM"][1])
                        if dist is not None:
                            house = {**house, "centreM": at(*house["centreM"][:2]), "front": fronts[faces]}
                            if min(math.hypot(qx - px, qy - py) for qx, qy in rect(house)) > NEAR_M:
                                houses.append({"id": f"r{row}b{block}s{side}p{i}", **house, "distanceM": round(dist, 1)})
                    for kind, kept in (("walls", walls), ("hedges", hedges)):
                        for item in plot[kind]:
                            (u0, v0), (u1, v1) = item["fromM"], item["toM"]
                            if all(clear_of_near(*q) for q in ((u0, v0), (u1, v1), ((u0 + u1) / 2, (v0 + v1) / 2))):
                                kept.append({**item, "fromM": at(u0, v0)[:2], "toM": at(u1, v1)[:2]})
                    for kind, kept in (("posts", posts), ("cars", cars), ("trees", trees)):
                        for item in plot[kind]:
                            if clear_of_near(*item["centreM"][:2]):
                                item = {**item, "centreM": at(*item["centreM"][:2])}
                                # A car stands nose to its street.
                                kept.append({**item, "front": fronts[faces]} if kind == "cars" else item)
        # Poles along the street's far edge, in the street before the plots' walls (not in a cross street's mouth),
        # and the wires from each to the next.
        first = math.ceil((pu - reach) / POLE_EVERY_M) - 1
        line = []
        for n in range(first, math.floor((pu + reach) / POLE_EVERY_M) + 2):
            u, v = n * POLE_EVERY_M + (row % 3) * 4.0, south - POLE_IN_STREET_M
            for c0, c1 in crossings:
                if c0 - 0.5 < u < c1 + 0.5:
                    u = c0 - 0.9
            ok = clear_of_near(u, v)
            line.append((f"r{row}n{n}", u, v, ok))
            if ok:
                poles.append(
                    {
                        "id": f"r{row}n{n}",
                        "centreM": at(u, v),
                        "heightM": POLE_M,
                        "streetward": toward_street,
                        "transformer": (n + row) % 3 == 0,
                        "lamp": n % 2 == 0,
                    }
                )
        for (id0, u0, v0, ok0), (id1, u1, v1, ok1) in zip(line, line[1:]):
            x, y = world((u0 + u1) / 2, (v0 + v1) / 2)
            if ok0 and ok1 and math.hypot(x - px, y - py) <= WIRE_REACH_M:
                wires.append({"poles": [id0, id1], "fromM": at(u0, v0)[:2], "toM": at(u1, v1)[:2]})
    houses.sort(key=lambda b: (b["distanceM"], b["id"]))
    return {
        "kind": "town",
        "seed": seed,
        "reachM": round(reach, 1),
        "streetM": wide_street,
        "street": {"axis": axis, "atM": through, "widthM": wide_street},
        "streets": streets,
        "houses": houses[:MAX_HOUSES],
        "trees": trees[: MAX_HOUSES * 3],
        "poles": poles[:MAX_HOUSES],
        "walls": walls,
        "hedges": hedges,
        "posts": posts,
        "cars": cars,
        "wires": wires,
    }


def rect(house: dict, margin: float = 0.0) -> list[list[float]]:
    """A house's footprint (its four corners), `margin` wider all round."""
    (x, y, _), (w, d, _) = house["centreM"], house["sizeM"]
    if house["front"].endswith("X"):
        w, d = d, w
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


def outline(points) -> list[tuple[float, float]]:
    """The outline drawn round all of `points` (their convex hull, counter-clockwise; fewer than three corners for
    points in a line)."""
    pts = sorted({(float(x), float(y)) for x, y in points})
    if len(pts) < 3:
        return pts

    def turn(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for q in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list[tuple[float, float]] = []
    for q in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


def off_outline(hull: list[tuple[float, float]], x: float, y: float) -> float:
    """How far (x, y) is outside an outline (0 or less: inside it). Past a corner it is told a little nearer than
    it is (by the edges' lines), which errs to keeping clear."""
    if not hull:
        return math.inf
    if len(hull) < 3:
        (ax, ay), (bx, by) = hull[0], hull[-1]
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(x - ax - t * dx, y - ay - t * dy)
    far = -math.inf
    for (ax, ay), (bx, by) in zip(hull, hull[1:] + hull[:1]):
        dx, dy = bx - ax, by - ay
        far = max(far, ((x - ax) * dy - (y - ay) * dx) / math.hypot(dx, dy))
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
    width); trees and poles by where they stand. Nothing stands among the place's things (inside the outline round
    all its points, or within `gap` of it: a yard behind a wall is the place's, though it lies beyond the wall), nor
    on the place's own lots (`grounds`: its grounds, each as x0, y0, x1, y1; one longer than LOT_MAX_M is land the
    town may stand on). `dropped` counts what was left out."""
    gap = made.get("streetM", STREET_M) if gap is None else gap
    far = place_reach(points, origin)
    hull = outline(points)
    grounds = [g for g in grounds if max(g[2] - g[0], g[3] - g[1]) <= LOT_MAX_M]

    def past(x: float, y: float) -> bool:
        if any(
            x0 - GROUND_CLEAR_M < x < x1 + GROUND_CLEAR_M and y0 - GROUND_CLEAR_M < y < y1 + GROUND_CLEAR_M for x0, y0, x1, y1 in grounds
        ):
            return False
        if off_outline(hull, x, y) <= gap:
            return False
        return math.hypot(x - origin[0], y - origin[1]) > _starts(far, x, y, origin) + gap

    def clear(house: dict) -> bool:
        if not all(past(x, y) for x, y in rect(house)):
            return False
        # …and no corner of the place's outline inside the house's own plot (the house and `gap` round it).
        (x0, y0), _, (x1, y1), _ = rect(house, gap)
        return not any(x0 < x < x1 and y0 < y < y1 for x, y in hull)

    def along(item: dict) -> bool:
        (x0, y0), (x1, y1) = item["fromM"], item["toM"]
        return all(past(x, y) for x, y in ((x0, y0), (x1, y1), ((x0 + x1) / 2, (y0 + y1) / 2)))

    def standing(kind: str) -> list[dict]:
        return [t for t in made.get(kind) or [] if past(t["centreM"][0], t["centreM"][1])]

    houses = [h for h in made["houses"] if clear(h)]
    trees, poles = standing("trees"), standing("poles")
    left = {p["id"] for p in poles if "id" in p}
    dropped = {
        "houses": made.get("dropped", {}).get("houses", 0) + len(made["houses"]) - len(houses),
        "trees": made.get("dropped", {}).get("trees", 0) + len(made["trees"]) - len(trees),
        "poles": made.get("dropped", {}).get("poles", 0) + len(made["poles"]) - len(poles),
    }
    return {
        **made,
        "houses": houses,
        "trees": trees,
        "poles": poles,
        "walls": [w for w in made.get("walls") or [] if along(w)],
        "hedges": [w for w in made.get("hedges") or [] if along(w)],
        "posts": standing("posts"),
        "cars": standing("cars"),
        # A wire hangs between two poles: without one of them it is gone.
        "wires": [w for w in made.get("wires") or [] if left.issuperset(w["poles"])],
        "dropped": dropped,
    }


def town_words(made: dict) -> str:
    """One line on the town as made."""
    if not made["houses"]:
        return "まわりは市街地: 絵に見える範囲に家は入りませんでした（場所の向こう側が絵に出ていないか、場所の敷地が絵の端まで続いている）"
    near, far = made["houses"][0]["distanceM"], made["houses"][-1]["distanceM"]
    street = made.get("street") or {"axis": "X", "atM": 0.0}
    runs = f"道は {street['axis']} の向き（幅 {made['streetM']:g} m）で、{'y' if street['axis'] == 'X' else 'x'} = {street['atM']:g} を 1 本が通る"
    more = "".join(
        f"・{name} {len(made.get(key) or [])} {unit}"
        for key, name, unit in (("walls", "塀", "枚"), ("hedges", "生け垣", "本"), ("cars", "車", "台"))
        if made.get(key)
    )
    wires = f"（電線 {len(made['wires'])} 区間）" if made.get("wires") else ""
    return (
        f"まわりは市街地（日本の住宅街）: 家 {len(made['houses'])} 軒（カメラから {near:.0f}〜{far:.0f} m）"
        f"・庭木 {len(made['trees'])} 本・電柱 {len(made['poles'])} 本{wires}{more}。{runs}。場所の物より向こう、場所の物の囲みと敷地の外にだけ置く（道幅 {made['streetM']:g} m あけて、近景 {NEAR_M:g} m の中には置かない）"
    )
