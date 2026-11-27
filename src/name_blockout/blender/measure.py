# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure a built scene with Blender's own projection (runs inside Blender).

Independent of name_blockout.camera: the picture positions come from
bpy_extras.object_utils.world_to_camera_view on the camera as Blender holds
it, and the vanishing points also from the scene's real edges (where the
projected edges of the ground grid and the boxes meet), so a wrong axis, lens,
shift or matrix shows as a difference from the instruction's targets.
"""

from __future__ import annotations

import math

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from .. import outline as plan_outline

FAR = 1.0e5
AXIS = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}
MAX_EDGES = 400
#: An edge counts as running along an axis within this cosine (about 0.26°).
ALIGNED = 0.99999


class Projector:
    def __init__(self, width: int, height: int):
        self.scene = bpy.context.scene
        self.cam = self.scene.camera
        self.width, self.height = width, height
        # Measure in the instruction's pixels: the render size only scales them, but its rounding would show.
        self._saved = (self.scene.render.resolution_x, self.scene.render.resolution_y)
        self.scene.render.resolution_x, self.scene.render.resolution_y = width, height

    def close(self):
        self.scene.render.resolution_x, self.scene.render.resolution_y = self._saved

    def px(self, co):
        v = world_to_camera_view(self.scene, self.cam, Vector(co))
        if v.z <= 1e-6:
            return None
        return (v.x * self.width, (1.0 - v.y) * self.height)

    @property
    def origin(self) -> Vector:
        return self.cam.matrix_world.translation.copy()


def horizon_rows(p: Projector):
    forward = -(p.cam.matrix_world.to_3x3() @ Vector((0, 0, 1)))
    level = Vector((forward.x, forward.y, 0))
    if level.length < 1e-6:
        level = p.cam.matrix_world.to_3x3() @ Vector((0, 1, 0))
        level.z = 0
    level.normalize()
    side = Vector((-level.y, level.x, 0))
    a = p.px(p.origin + (level + side * 0.3) * FAR)
    b = p.px(p.origin + (level - side * 0.3) * FAR)
    if a is None or b is None or abs(b[0] - a[0]) < 1e-9:
        return None
    slope = (b[1] - a[1]) / (b[0] - a[0])
    return [a[1] - a[0] * slope, a[1] + (p.width - a[0]) * slope]


def world_edges(objects, direction: Vector, limit: int = MAX_EDGES):
    """Edges of the objects (as evaluated, in the world) running along `direction`."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    out = []
    for obj in objects:
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        mw = ev.matrix_world
        co = [mw @ v.co for v in mesh.vertices]
        for e in mesh.edges:
            a, b = co[e.vertices[0]], co[e.vertices[1]]
            d = b - a
            if d.length < 1e-6:
                continue
            if abs(d.normalized().dot(direction)) > ALIGNED:
                out.append((a.copy(), b.copy()))
        ev.to_mesh_clear()
    if len(out) > limit:
        step = len(out) / limit
        out = [out[int(i * step)] for i in range(limit)]
    return out


def meet(lines):
    """Where picture lines meet (least squares, in homogeneous coordinates; far away when they are parallel)."""
    rows = []
    for (x0, y0), (x1, y1) in lines:
        l = np.cross([x0, y0, 1.0], [x1, y1, 1.0])
        n = np.hypot(l[0], l[1])
        if n > 1e-9:
            rows.append(l / n)
    if len(rows) < 2:
        return None
    _, _, vt = np.linalg.svd(np.array(rows))
    x, y, w = vt[-1]
    if abs(w) < 1e-12:
        w = 1e-12 if w >= 0 else -1e-12
    return [float(x / w), float(y / w)]


def edge_vanishing(p: Projector, objects, axis: str):
    lines = []
    for a, b in world_edges(objects, Vector(AXIS[axis])):
        pa, pb = p.px(a), p.px(b)
        if pa and pb and abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) > 2:
            lines.append((pa, pb))
    if len(lines) < 2:
        return None
    point = meet(lines)
    if point and len(lines) >= 10:
        # A few edges of a piece set a little askew (a place's model) would pull the point: leave out the lines that
        # miss it most (the worst tenth, those over 0.1°) and meet the rest.
        errs = sorted(((_miss_deg(line, point), i) for i, line in enumerate(lines)), reverse=True)
        drop = {i for err, i in errs[: len(lines) // 10] if err > 0.1}
        if drop:
            kept = [line for i, line in enumerate(lines) if i not in drop]
            point = meet(kept) or point
            return {"point": point, "lines": len(kept), "leftOut": len(drop)}
    return {"point": point, "lines": len(lines)} if point else None


def _miss_deg(line, point) -> float:
    """The angle at a line's middle between the line and the way to `point`."""
    (x0, y0), (x1, y1) = line
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    a = math.atan2(y1 - y0, x1 - x0)
    b = math.atan2(point[1] - my, point[0] - mx)
    d = abs(math.degrees(a - b)) % 180
    return min(d, 180 - d)


def outline(p: Projector, objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    xs, ys = [], []
    for obj in objects:
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        mw = ev.matrix_world
        for v in mesh.vertices:
            q = p.px(mw @ v.co)
            if q is None:
                ev.to_mesh_clear()
                return None
            xs.append(q[0])
            ys.append(q[1])
        ev.to_mesh_clear()
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def box_outline(p: Projector, gauge: dict):
    """The outline of the box a shape was made in (its corners projected), as the Blockout's box would show."""
    (cx, cy, cz), (w, d, h) = gauge["centreM"], gauge["sizeM"]
    if gauge.get("along") == "Y":
        w, d = d, w
    xs, ys = [], []
    for dx in (-w / 2, w / 2):
        for dy in (-d / 2, d / 2):
            for z in (cz, cz + h):
                q = p.px(Vector((cx + dx, cy + dy, z)))
                if q is None:
                    return None
                xs.append(q[0])
                ys.append(q[1])
    return [min(xs), min(ys), max(xs), max(ys)]


#: Footprints are measured to this grid (m), and things smaller than this from above are left out (m²).
FOOTPRINT_GRID = 0.05
FOOTPRINT_MIN_AREA = 0.02


def hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The convex outline of points on the ground, counter-clockwise (Andrew's monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for q in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list = []
    for q in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


#: A floor plan is cut this high above the floor (m), as an architect's is.
CUT_ABOVE_FLOOR = 1.2
#: The camera is indoors when something is over it, under it and around it within these distances (m).
CEILING_WITHIN = 12.0
WALLS_WITHIN = 40.0
WALLS_NEEDED = 3
ROOM_RAYS = 24
#: Where the floor is looked for around the camera: (how far, how many spots), and floors this close are one (m).
FLOOR_SPOTS = ((0.5, 4), (1.2, 8))
FLOOR_STEP = 0.05


def indoor_cut(position) -> dict | None:
    """Where to cut a floor plan for a camera that stands indoors: None when it stands in the open. Indoors is
    a floor below, something overhead and walls on at least three of four sides (a tree's crown or a carport over
    the camera is not a room)."""
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    at = Vector(position)

    def hit(direction, within, start=at):
        found, where, *_ = scene.ray_cast(depsgraph, start, Vector(direction), distance=within)
        return where if found else None

    ceiling = hit((0, 0, 1), CEILING_WITHIN)
    # The floor is what is under most of the spots around the camera: under the camera itself may be a table.
    spots = [at] + [
        at + Vector((math.cos(a) * r, math.sin(a) * r, 0.0)) for r, n in FLOOR_SPOTS for a in (math.tau * i / n for i in range(n))
    ]
    under = [h.z for h in (hit((0, 0, -1), 50.0, spot) for spot in spots) if h is not None]
    if not under or ceiling is None:
        return None
    levels: dict[float, int] = {}
    for z in under:
        levels[round(z / FLOOR_STEP) * FLOOR_STEP] = levels.get(round(z / FLOOR_STEP) * FLOOR_STEP, 0) + 1
    level = max(levels, key=lambda z: (levels[z], -z))
    floor = Vector((at.x, at.y, min((z for z in under if abs(z - level) <= FLOOR_STEP), key=lambda z: abs(z - level))))
    walls = sum(1 for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)) if hit(d, WALLS_WITHIN) is not None)
    if walls < WALLS_NEEDED:
        return None
    # How far the room reaches from the camera: the furthest wall around it (the plan is drawn that far).
    around = [hit((math.cos(a), math.sin(a), 0.0), WALLS_WITHIN) for a in (math.radians(360 * i / ROOM_RAYS) for i in range(ROOM_RAYS))]
    reach = max(((w - at).length for w in around if w is not None), default=None)
    return {
        "floorM": round(float(floor.z), 3),
        "ceilingM": round(float(ceiling.z), 3),
        "cutM": round(float(floor.z) + CUT_ABOVE_FLOOR, 3),
        "roomReachM": round(float(reach), 2) if reach else None,
    }


def footprints(objects, cut: float | None = None) -> list[dict]:
    """What a place holds, seen from straight above (for the top view): each mesh as the scene shows it
    (modifiers applied): its outline (rings: an L-shaped house stays an L, every tree is its own ring), the convex
    outline around it, how high it reaches, and whether it is a ground (a lot, a lawn, a terrace).

    With `cut` (a height, m) the place is drawn as a floor plan: what is wholly above the cut is left out (roofs,
    ceilings, lamps), each mesh's outline is of its part that starts below the cut, and `sectionM` is the mesh cut
    at that height (the walls). The largest first."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    out = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        shown = obj.evaluated_get(depsgraph)
        mesh = shown.to_mesh()
        n = len(mesh.vertices)
        if n < 3:
            shown.to_mesh_clear()
            continue
        co = np.empty(n * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        mesh.calc_loop_triangles()
        tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", tris)
        tris = tris.reshape(-1, 3)
        shown.to_mesh_clear()
        m = np.array(obj.matrix_world, dtype=np.float64)
        world = co.reshape(n, 3).astype(np.float64) @ m[:3, :3].T + m[:3, 3]
        ground = bool(obj.get("nb_ground"))
        entry = {"name": obj.name, "heightM": [round(float(world[:, 2].min()), 2), round(float(world[:, 2].max()), 2)], "ground": ground}
        if cut is not None and not ground:
            if float(world[:, 2].min()) >= cut:
                continue
            tris = tris[world[tris][:, :, 2].min(axis=1) < cut]
            entry["sectionM"] = plan_outline.section(world, tris, cut)
            used = np.unique(tris)
        else:
            used = np.arange(n)
        if len(used) < 3:
            continue
        cells = np.unique(np.round(world[used, :2] / FOOTPRINT_GRID).astype(np.int64), axis=0)
        around = hull([(float(x) * FOOTPRINT_GRID, float(y) * FOOTPRINT_GRID) for x, y in cells])
        if len(around) < 3:
            continue
        area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(around, around[1:] + around[:1]))) / 2
        if area < FOOTPRINT_MIN_AREA:
            continue
        entry["footprintM"] = [[round(x, 2), round(y, 2)] for x, y in around]
        entry["areaM2"] = round(area, 2)
        if not ground:
            # A ground is drawn by its edge alone: its rings would be the whole lot.
            entry["ringsM"] = plan_outline.silhouette(world[:, :2], tris, FOOTPRINT_MIN_AREA)
        out.append(entry)
    out.sort(key=lambda o: -o["areaM2"])
    return out


def measure(plan: dict, built: dict) -> dict:
    width, height = plan["targets"]["sizePx"]
    p = Projector(width, height)
    try:
        out = {"horizonPx": horizon_rows(p), "vanishingPx": {}, "edgeVanishingPx": {}, "objectsPx": {}, "figuresPx": {}}
        for i, axis in enumerate(plan["camera"].get("vanishingAxes") or []):
            if not axis:
                continue
            q = p.px(p.origin + Vector(AXIS[axis]) * FAR)
            if q:
                out["vanishingPx"][str(i)] = list(q)
            e = edge_vanishing(p, built["edges"], axis)
            if e:
                out["edgeVanishingPx"][str(i)] = e
        gauges = built.get("gauges") or {}
        for key, kind in (("objects", "objectsPx"), ("figures", "figuresPx")):
            for ident, objs in built[key].items():
                gauge = gauges.get(ident) if key == "objects" else None
                box = box_outline(p, gauge) if gauge else outline(p, objs)
                if box:
                    out[kind][ident] = box
        cam = p.cam.data
        out["camera"] = {"lensMm": cam.lens, "shiftX": cam.shift_x, "shiftY": cam.shift_y, "location": list(p.origin)}
        return out
    finally:
        p.close()
