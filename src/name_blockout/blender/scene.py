# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a Blockout plan in Blender (runs inside Blender: bpy).

Everything comes from the plan (plan.py): the camera's lens, shift and
matrix, the ground grid, the place (a .blend collection from 素材), boxes
for things, posts, and simple figures. Nothing is decided here.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

from ..far import BANDS, TONE_LIFT
from ..materials import CELL_WORDS, DEFAULT, FINE_WORDS, FOLIAGE, guess_part

PREFIX = "NB_"
#: Which light the tones take (from above, in front, a little left of the camera's usual view).
LIGHT = Vector((-0.45, -0.6, 0.66)).normalized()


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def collection(name: str):
    coll = bpy.data.collections.get(PREFIX + name)
    if coll is None:
        coll = bpy.data.collections.new(PREFIX + name)
        bpy.context.scene.collection.children.link(coll)
    return coll


def set_camera(plan: dict):
    scene = bpy.context.scene
    c = plan["camera"]
    data = bpy.data.cameras.new(PREFIX + "camera")
    data.sensor_fit = "AUTO"
    data.sensor_width = c.get("sensorMm", 36.0)
    data.lens = c["lensMm"]
    data.shift_x = c["shiftX"]
    data.shift_y = c["shiftY"]
    data.clip_start = 0.05
    data.clip_end = 1.0e5
    cam = bpy.data.objects.new(PREFIX + "camera", data)
    collection("camera").objects.link(cam)
    cam.matrix_world = Matrix(c["matrixWorld"])
    scene.camera = cam
    w, h = plan["render"]["sizePx"]
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.0
    return cam


def band_collection(band: str):
    """Where the things of a distance band go (one Freestyle line set each: their lines get thinner with distance)."""
    return collection("band_" + band)


def tone_material(name: str, base: float = 0.0, flat: float | None = None, lift: float = 0.0):
    """Grey by which way a face looks (three steps), as light from LIGHT; `flat` for one grey; `lift`: lighter (farther)."""
    mat = bpy.data.materials.get(PREFIX + name)
    if mat:
        return mat
    mat = bpy.data.materials.new(PREFIX + name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    links.new(emit.outputs[0], out.inputs[0])
    if flat is not None:
        emit.inputs["Color"].default_value = (flat, flat, flat, 1.0)
        return mat
    geo = nodes.new("ShaderNodeNewGeometry")
    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = LIGHT
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    els = ramp.color_ramp.elements
    steps = [min(0.97, v + lift) for v in (0.58 + base, 0.78 + base, 0.93)]
    els[0].position, els[0].color = 0.0, (steps[0], steps[0], steps[0], 1)
    els[1].position, els[1].color = 0.55, (steps[1], steps[1], steps[1], 1)
    third = els.new(0.8)
    third.color = (steps[2], steps[2], steps[2], 1)
    mapr = nodes.new("ShaderNodeMapRange")
    mapr.inputs["From Min"].default_value = -1.0
    mapr.inputs["From Max"].default_value = 1.0
    links.new(geo.outputs["True Normal"], dot.inputs[0])
    links.new(dot.outputs["Value"], mapr.inputs["Value"])
    links.new(mapr.outputs["Result"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], emit.inputs["Color"])
    return mat


def holdout_material():
    mat = bpy.data.materials.get(PREFIX + "holdout")
    if mat:
        return mat
    mat = bpy.data.materials.new(PREFIX + "holdout")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    hold = nodes.new("ShaderNodeHoldout")
    mat.node_tree.links.new(hold.outputs[0], out.inputs[0])
    return mat


def _mesh_object(name: str, bm: bmesh.types.BMesh, coll, material, mark_all: bool = False):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if mark_all:
        attr = mesh.attributes.get("freestyle_edge") or mesh.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
        attr.data.foreach_set("value", [True] * len(mesh.edges))
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def add_ground(ground: dict):
    """Level grids in rings (the plan's), each cell's edges marked so they are drawn: they run to the vanishing points.
    A room's floor is one grid inside its walls (rectM)."""
    z = ground.get("z", 0.0)
    if ground.get("rectM"):
        return _floor_grid(ground["rectM"], ground["spacingM"], z)
    cx, cy = ground.get("centreM", (0.0, 0.0))
    rings = ground.get("rings") or [{"spacingM": ground["spacingM"], "extentM": ground["extentM"]}]
    bm = bmesh.new()
    verts: dict = {}

    def vert(x, y):
        key = (round(x, 6), round(y, 6))
        if key not in verts:
            verts[key] = bm.verts.new((cx + x, cy + y, z))
        return verts[key]

    inner = 0.0
    for ring in rings:
        s = ring["spacingM"]
        n = max(1, int(round(ring["extentM"] / s)))
        for i in range(-n, n):
            for j in range(-n, n):
                x0, y0, x1, y1 = i * s, j * s, (i + 1) * s, (j + 1) * s
                if inner and max(abs(x0), abs(x1)) <= inner + 1e-9 and max(abs(y0), abs(y1)) <= inner + 1e-9:
                    continue
                bm.faces.new((vert(x0, y0), vert(x1, y0), vert(x1, y1), vert(x0, y1)))
        inner = n * s
    material = tone_material("ground", flat=0.95)
    return _mesh_object(PREFIX + "ground", bm, collection("ground"), material, mark_all=True)


def _breaks(start: float, end: float, step: float) -> list[float]:
    """start, end and the multiples of step between (a grid that lines up with the world's, cut at the walls)."""
    out = [start]
    k = math.floor(start / step) + 1
    while k * step < end - 1e-6:
        if k * step > start + 1e-6:
            out.append(k * step)
        k += 1
    return out + [end]


def _floor_grid(rect, spacing: float, z: float):
    x0, y0, x1, y1 = rect
    xs, ys = _breaks(x0, x1, spacing), _breaks(y0, y1, spacing)
    bm = bmesh.new()
    verts = [[bm.verts.new((x, y, z)) for y in ys] for x in xs]
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    material = tone_material("ground", flat=0.95)
    return _mesh_object(PREFIX + "ground", bm, collection("ground"), material, mark_all=True)


def _in_hole(holes, u: float, v: float) -> bool:
    return any(h[0] - 1e-6 <= u <= h[1] + 1e-6 and h[2] - 1e-6 <= v <= h[3] + 1e-6 for h in holes)


def _drawn(holes, length: float, height: float, p, q) -> bool:
    """A wall's edge from p to q (along the wall, up it) is drawn: on the wall's outline, or on a window's."""
    (u_a, v_a), (u_b, v_b) = p, q
    if u_a == u_b and u_a in (0.0, length) or v_a == v_b and v_a in (0.0, height):
        return True
    for h in holes:
        if u_a == u_b and u_a in (h[0], h[1]) and h[2] - 1e-6 <= min(v_a, v_b) and max(v_a, v_b) <= h[3] + 1e-6:
            return True
        if v_a == v_b and v_a in (h[2], h[3]) and h[0] - 1e-6 <= min(u_a, u_b) and max(u_a, u_b) <= h[1] + 1e-6:
            return True
    return False


def add_room(room: dict):
    """The room's walls and ceiling as one mesh facing in, windows cut through (with a reveal as deep as the wall), its
    corners and the windows' edges marked to be drawn. They take light and cast no shadow (the room's light is the
    key's, as the plan sets it); the shadow check looks through them the same way (nb_noshadow)."""
    x0, y0, x1, y1 = room["rectM"]
    height = room["heightM"]
    depth = room.get("revealM", 0.12)
    centre = Vector(((x0 + x1) / 2, (y0 + y1) / 2, height / 2))
    bm = bmesh.new()
    marked: set = set()

    def mark(p, q):
        marked.add(frozenset((tuple(round(c, 4) for c in p.co), tuple(round(c, 4) for c in q.co))))

    ends = {
        "+X": ((x1, y1), (x1, y0)),
        "-X": ((x0, y0), (x0, y1)),
        "+Y": ((x0, y1), (x1, y1)),
        "-Y": ((x1, y0), (x0, y0)),
    }
    outward = {"+X": Vector((1, 0, 0)), "-X": Vector((-1, 0, 0)), "+Y": Vector((0, 1, 0)), "-Y": Vector((0, -1, 0))}
    faces = []
    for side, ((ax, ay), (bx, by)) in ends.items():
        a, b = Vector((ax, ay, 0.0)), Vector((bx, by, 0.0))
        length = (b - a).length
        along = (b - a) / length
        holes = []
        for w in room.get("windows", []):
            if w["side"] != side:
                continue
            u0 = (Vector((*w["fromM"], 0.0)) - a).dot(along)
            u1 = (Vector((*w["toM"], 0.0)) - a).dot(along)
            holes.append((min(u0, u1), max(u0, u1), w["sillM"], w["headM"]))
        us = sorted({0.0, length, *[h[0] for h in holes], *[h[1] for h in holes]})
        vs = sorted({0.0, height, *[h[2] for h in holes], *[h[3] for h in holes]})
        grid = {(i, j): bm.verts.new(a + along * u + Vector((0, 0, v))) for i, u in enumerate(us) for j, v in enumerate(vs)}

        for i in range(len(us) - 1):
            for j in range(len(vs) - 1):
                if _in_hole(holes, (us[i] + us[i + 1]) / 2, (vs[j] + vs[j + 1]) / 2):
                    continue
                corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                faces.append(bm.faces.new([grid[c] for c in corners]))
                for k in range(4):
                    p, q = corners[k], corners[(k + 1) % 4]
                    if _drawn(holes, length, height, (us[p[0]], vs[p[1]]), (us[q[0]], vs[q[1]])):
                        mark(grid[p], grid[q])
        # Each window's reveal: the wall's thickness round the hole, its outer edge drawn too.
        out = outward[side] * depth
        for u0, u1, v0, v1 in holes:
            inner = [a + along * u0 + Vector((0, 0, v0)), a + along * u1 + Vector((0, 0, v0))]
            inner += [a + along * u1 + Vector((0, 0, v1)), a + along * u0 + Vector((0, 0, v1))]
            iv = [bm.verts.new(p) for p in inner]
            ov = [bm.verts.new(p + out) for p in inner]
            for k in range(4):
                n = (k + 1) % 4
                faces.append(bm.faces.new((iv[k], iv[n], ov[n], ov[k])))
                mark(ov[k], ov[n])
                mark(iv[k], ov[k])
    top = [bm.verts.new((x, y, height)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    faces.append(bm.faces.new(top))
    for k in range(4):
        mark(top[k], top[(k + 1) % 4])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    for f in bm.faces:
        f.normal_update()
        if f.normal.dot(centre - f.calc_center_median()) < 0:
            f.normal_flip()
    mesh = bpy.data.meshes.new(PREFIX + "room")
    bm.to_mesh(mesh)
    bm.free()
    attr = mesh.attributes.get("freestyle_edge") or mesh.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    values = []
    for e in mesh.edges:
        key = frozenset(tuple(round(c, 4) for c in mesh.vertices[i].co) for i in e.vertices)
        values.append(key in marked)
    attr.data.foreach_set("value", values)
    mesh.materials.append(tone_material("room", lift=0.08))
    obj = bpy.data.objects.new(PREFIX + "room", mesh)
    band_collection("near").objects.link(obj)
    obj.visible_shadow = False
    obj["nb_noshadow"] = True
    return obj


def add_box(name: str, centre, size, along: str, coll, material):
    w, d, h = size
    if along == "Y":
        w, d = d, w
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(w, d, h), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(centre[0], centre[1], centre[2] + h / 2), verts=bm.verts)
    return _mesh_object(name, bm, coll, material)


def add_figure(name: str, centre, height: float, coll, material):
    """A plain mannequin: a body and a head, its feet at `centre` (as tall as `height`)."""
    head_r = height * 0.075
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=height * 0.12, radius2=height * 0.1, depth=height - 2 * head_r)
    bmesh.ops.translate(bm, vec=(0, 0, (height - 2 * head_r) / 2), verts=bm.verts)
    head = bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=head_r)
    bmesh.ops.translate(bm, vec=(0, 0, height - head_r), verts=head["verts"])
    bmesh.ops.translate(bm, vec=tuple(centre), verts=bm.verts)
    return _mesh_object(name, bm, coll, material)


def add_skyline(layer: dict, coll, material):
    for i, b in enumerate(layer["boxes"]):
        add_box(f"{PREFIX}skyline_{i}", b["centreM"], b["sizeM"], "X", coll, material)


def add_mountains(layer: dict, coll, material):
    """The ridge as one strip from the ground up to it; only its outline is drawn (silhouette)."""
    bm = bmesh.new()
    top = [bm.verts.new(tuple(p)) for p in layer["ridge"]]
    foot = [bm.verts.new((p[0], p[1], 0.0)) for p in layer["ridge"]]
    for i in range(len(top) - 1):
        bm.faces.new((foot[i], foot[i + 1], top[i + 1], top[i]))
    return _mesh_object(PREFIX + "mountains", bm, coll, material)


def add_trees(layer: dict, coll, material):
    """The trees in one mesh: a short trunk, and a crown of a few lumpy balls (broadleaf) or a cone (conifer); the
    crowns' faces marked so only their outlines are drawn."""
    bm = bmesh.new()
    crown_faces = set()
    for t in layer["trees"]:
        h, r = t["heightM"], t["radiusM"]
        x, y, z = t["centreM"]
        trunk = h * (0.18 if t.get("form") == "conifer" else 0.3)
        stem = bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=r * 0.1, radius2=r * 0.08, depth=trunk)
        bmesh.ops.translate(bm, vec=(x, y, z + trunk / 2), verts=stem["verts"])
        before = set(bm.faces)
        if t.get("form") == "conifer":
            made = bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=r, radius2=0.0, depth=h - trunk)
            bmesh.ops.translate(bm, vec=(x, y, z + trunk + (h - trunk) / 2), verts=made["verts"])
        else:
            rng = random.Random(t.get("seed", 0))
            # The crown from a little under the trunk's top to the tree's height: a big middle lump and smaller ones
            # round it, overlapping (no gaps to the sky between them or above the trunk).
            crown = h - trunk * 0.8
            middle = z + h - crown / 2
            for i in range(4):
                k = 0.85 if i == 0 else rng.uniform(0.55, 0.7)
                off = 0.0 if i == 0 else 0.4
                centre = Vector((x + rng.uniform(-off, off) * r, y + rng.uniform(-off, off) * r, middle + rng.uniform(-0.15, 0.2) * crown))
                ball = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
                for v in ball["verts"]:
                    lump = 1.0 + rng.uniform(-0.1, 0.1)
                    v.co = centre + Vector((v.co.x * r * k, v.co.y * r * k, v.co.z * crown * k * 0.5)) * lump
        crown_faces |= set(bm.faces) - before
    bm.faces.index_update()
    marks = [f in crown_faces for f in bm.faces]
    obj = _mesh_object(PREFIX + "trees", bm, coll, material)
    mark_foliage(obj, marks)
    return obj


def panorama_world(layer: dict):
    """The 360° image as the world, in greys (its horizon, at the image's middle row, is the camera's horizon), turned
    by turnDeg (counter-clockwise from above). Bright skies are pressed under white (v / (1 + v) · 1.6)."""
    world = bpy.data.worlds.new(PREFIX + "panorama")
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    bg = nodes.get("Background")
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, -math.radians(layer.get("turnDeg", 0.0)))
    tex = nodes.new("ShaderNodeTexEnvironment")
    tex.image = bpy.data.images.load(layer["file"], check_existing=True)
    tex.image.colorspace_settings.name = "Linear Rec.709" if layer["file"].lower().endswith((".hdr", ".exr")) else "sRGB"
    grey = nodes.new("ShaderNodeRGBToBW")
    add = nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    add.inputs[1].default_value = 1.0
    div = nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    mul = nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 1.6
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], grey.inputs[0])
    links.new(grey.outputs[0], add.inputs[0])
    links.new(grey.outputs[0], div.inputs[0])
    links.new(add.outputs[0], div.inputs[1])
    links.new(div.outputs[0], mul.inputs[0])
    links.new(mul.outputs[0], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.0
    return world


def add_far(far: list[dict]) -> dict:
    """The far layers: made things go with the far band (thin lines, light tones); a panorama becomes a world."""
    coll = band_collection("far")
    material = tone_material("far_layers", lift=TONE_LIFT["far"])
    out = {"panorama": None}
    for layer in far:
        kind = layer["kind"]
        if kind == "panorama":
            out["panorama"] = panorama_world(layer)
        elif kind == "skyline":
            add_skyline(layer, coll, material)
        elif kind == "mountains":
            add_mountains(layer, coll, material)
        elif kind == "trees":
            add_trees(layer, coll, material)
    return out


def _append(path: Path, wanted: str):
    """A .blend's collection `wanted` (else all its objects), appended: the objects, cameras and lights left out."""
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        if wanted in src.collections:
            dst.collections = [wanted]
        else:
            dst.objects = list(src.objects)
    objects = []
    for c in getattr(dst, "collections", []) or []:
        if c is not None:
            objects += list(c.all_objects)
    objects += [o for o in getattr(dst, "objects", []) or [] if o is not None]
    return [o for o in dict.fromkeys(objects) if o.type not in ("CAMERA", "LIGHT")]


def add_thing(obj: dict, camera_at, coll):
    """A thing's 素材 (a .blend) in place of its box: turned so its first side runs along the box's (and its front,
    the 素材's −Y, toward the camera), scaled alike on all sides to fit in the box, standing on the box's bottom.
    Returns its mesh parts (each named as in the 素材)."""
    asset = obj["asset"]
    parts = _append(Path(asset["file"]), asset.get("collection") or asset["name"])
    meshes = [o for o in parts if o.type == "MESH"]
    if not meshes:
        return []
    for o in parts:
        coll.objects.link(o)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = []
    for o in meshes:
        ev = o.evaluated_get(depsgraph)
        points += [ev.matrix_world @ Vector(c) for c in ev.bound_box]
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    size = hi - lo
    base = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    p = obj["placed"]
    w, d, h = p["sizeM"]
    turn = 0.0 if p["along"] == "X" else math.pi / 2
    centre = Vector(p["centreM"])
    front = Matrix.Rotation(turn, 3, "Z") @ Vector((0, -1, 0))
    to_camera = Vector((camera_at[0] - centre.x, camera_at[1] - centre.y, 0.0))
    if front.dot(to_camera) < 0:
        turn += math.pi
    k = min(w / max(size.x, 1e-6), d / max(size.y, 1e-6), h / max(size.z, 1e-6))
    holder = bpy.data.objects.new(PREFIX + "thing_" + obj["id"], None)
    coll.objects.link(holder)
    holder.matrix_world = Matrix.Translation(centre) @ Matrix.Rotation(turn, 4, "Z") @ Matrix.Scale(k, 4) @ Matrix.Translation(-base)
    for o in parts:
        if o.parent is None:
            o.parent = holder
            o.matrix_parent_inverse = Matrix.Identity(4)
    for o in meshes:
        o["nb_label"] = obj["label"]
        o["nb_part"] = o.name
    return meshes


def _part_mesh(part: dict) -> bmesh.types.BMesh:
    """One part of a shape (shapes.py) as a mesh in the thing's own frame."""
    bm = bmesh.new()
    sx, sy, sz = part["s"]
    kind = part.get("shape", "box")
    if kind == "cylinder":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.5, radius2=0.5, depth=1.0)
        turn = {"X": Matrix.Rotation(math.pi / 2, 4, "Y"), "Y": Matrix.Rotation(math.pi / 2, 4, "X")}.get(part.get("axis", "Z"))
        if turn is not None:
            bmesh.ops.transform(bm, matrix=turn, verts=bm.verts)

    elif kind == "sphere":
        lumpy = float(part.get("lumpy") or 0.0)
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.5)
        if lumpy:
            # A cluster of leaves: each corner pushed in or out a little (seeded), so its outline is uneven.
            rng = random.Random(part.get("seed", 0))
            for v in bm.verts:
                v.co *= 1.0 + rng.uniform(-lumpy, lumpy)
    elif kind == "prism":
        # A gable: its ridge along Y (or X), the triangle's base the part's bottom.
        verts = [
            bm.verts.new(v)
            for v in ((-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.0, -0.5, 0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5), (0.0, 0.5, 0.5))
        ]
        a0, a1, a2, b0, b1, b2 = verts
        for face in ((a0, a2, a1), (b0, b1, b2), (a0, a1, b1, b0), (a1, a2, b2, b1), (a2, a0, b0, b2)):
            bm.faces.new(face)
        if part.get("ridge") == "X":
            bmesh.ops.transform(bm, matrix=Matrix.Rotation(math.pi / 2, 4, "Z"), verts=bm.verts)
            sx, sy = sx, sy
    else:
        bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    if part.get("tilt"):
        # A bough: leaning out from the trunk toward `tilt`.
        tx, ty = part["tilt"]
        bmesh.ops.transform(bm, matrix=Matrix.Rotation(math.radians(50), 4, Vector((-ty, tx, 0.0))), verts=bm.verts)
    bmesh.ops.translate(bm, vec=tuple(part["c"]), verts=bm.verts)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def add_shape(obj: dict, camera_at, coll, material):
    """A thing's detailed shape (plan's parts) in place of its box: its front (−Y) toward the camera, turned with the
    box, standing on the box's bottom. Returns its parts' objects (each named and given its material as made)."""
    p = obj["placed"]
    turn = 0.0 if p["along"] == "X" else math.pi / 2
    centre = Vector(p["centreM"])
    front = Matrix.Rotation(turn, 3, "Z") @ Vector((0, -1, 0))
    if front.dot(Vector((camera_at[0] - centre.x, camera_at[1] - centre.y, 0.0))) < 0:
        turn += math.pi
    holder = bpy.data.objects.new(PREFIX + "thing_" + obj["id"], None)
    coll.objects.link(holder)
    holder.matrix_world = Matrix.Translation(centre) @ Matrix.Rotation(turn, 4, "Z")
    out = []
    for i, part in enumerate(obj["parts"]):
        piece = _mesh_object(f"{part['name']}.{obj['id']}.{i:03d}", _part_mesh(part), coll, material)
        piece.parent = holder
        piece.matrix_parent_inverse = Matrix.Identity(4)
        piece["nb_label"] = obj["label"]
        piece["nb_part"] = part["name"]
        if part.get("material"):
            piece["nb_material"] = part["material"]
            if part["material"] in FOLIAGE and part.get("shape") == "sphere":
                mark_foliage(piece)
        out.append(piece)
    return out


#: Names of a place's stand-ins for people (mannequins the modeller left in): not drawn, the figures are the shot's.
DUMMY_WORDS = ("dummy", "mannequin", "人形", "ダミー")


def _is_dummy(name: str) -> bool:
    low = name.lower()
    return low.startswith("d_") or any(w in low for w in DUMMY_WORDS)


def _hidden(name: str, hide) -> bool:
    return any(name == h or name.startswith(h) for h in hide or [])


#: On a ベタ thing (a black van) the pen draws its folds sharper than this (degrees) in white: its windows' frames, its
#: roof's edge, its doors' seams; a box's corners alone would leave a black lump.
SHARP_ON_BETA_DEG = 35.0
SHARP_MIN_M = 0.08


def mark_sharp(obj) -> None:
    """The edges of a mesh folded sharper than SHARP_ON_BETA_DEG marked to be drawn (Freestyle's edge marks)."""
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    limit = math.radians(SHARP_ON_BETA_DEG)
    # Long folds only: a bolt's or a vent's tiny facets would make thousands of strokes for nothing (and slow
    # Freestyle down several times).
    scale = max(obj.matrix_world.to_scale())
    sharp = [
        e.calc_length() * scale >= SHARP_MIN_M and (e.is_boundary or (len(e.link_faces) == 2 and e.calc_face_angle(0.0) > limit))
        for e in bm.edges
    ]
    bm.free()
    attr = mesh.attributes.get("freestyle_edge") or mesh.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    attr.data.foreach_set("value", sharp)


#: A ground's faces of two materials lie against each other when they are within this (m): modelled as separate
#: pieces (a path laid on a lawn, a kerb set against paving), they share no edge.
BORDER_NEAR_M = 0.05


def mark_material_borders(obj) -> int:
    """On a ground (a lot, a terrace), the edges where two materials meet (a lawn against a path, paving against a
    kerb) marked to be drawn: the ground is left white whatever it is made of, so without a line the two would
    run into one. An edge between two faces of different materials; or, where the materials are separate pieces,
    the open edge of one piece lying against a face of another material (the lot's own outer edge, with nothing
    beside it, is not one). Returns how many edges were marked."""
    from mathutils.bvhtree import BVHTree

    mesh = obj.data
    if len(mesh.materials) < 2:
        return 0
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.transform(obj.matrix_world)
    bm.faces.ensure_lookup_table()
    border = [len({f.material_index for f in e.link_faces}) > 1 for e in bm.edges]
    taken: dict[tuple[float, float], list[float]] = {}

    def take(a, b) -> bool:
        """Whether no border is here yet (its middle, within BORDER_NEAR_M in height); if so, now there is."""
        mid = (a + b) / 2
        heights = taken.setdefault((round(mid.x, 2), round(mid.y, 2)), [])
        if any(abs(mid.z - z) <= BORDER_NEAR_M for z in heights):
            return False
        heights.append(mid.z)
        return True

    for e, shared in zip(bm.edges, border):
        if shared:
            take(e.verts[0].co, e.verts[1].co)
    others = {}
    for e in bm.edges:
        if len(e.link_faces) != 1:
            continue
        own = e.link_faces[0].material_index
        if own not in others:
            rest = [f for f in bm.faces if f.material_index != own]
            points = [v.co.copy() for v in bm.verts]
            others[own] = BVHTree.FromPolygons(points, [[v.index for v in f.verts] for f in rest]) if rest else None
        tree = others[own]
        if tree is None:
            continue
        a, b = e.verts[0].co, e.verts[1].co
        # Along its length, not at its ends alone: a corner touching another piece is not an edge lying against it.
        if not all(tree.find_nearest(a.lerp(b, t), BORDER_NEAR_M)[0] is not None for t in (0.25, 0.5, 0.75)):
            continue
        # Two pieces' open edges on the same line (the lawn's and the path's) are one border.
        if take(a, b):
            border[e.index] = True
    bm.free()
    if not any(border):
        return 0
    attr = mesh.attributes.get("freestyle_edge") or mesh.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    marks = [False] * len(mesh.edges)
    attr.data.foreach_get("value", marks)
    attr.data.foreach_set("value", [a or b for a, b in zip(marks, border)])
    return sum(border)


#: A solar cell (m²): a slot whose faces are no larger than a few of these has its cells modelled face by face.
CELL_AREA = 0.16 * 0.16


def mark_cells(obj, slots) -> None:
    """A solar panel's material slots (its or its material's name says so: nb_cell_slots). If their faces are the
    cells (small), each face gets its own number (the face attribute nb_cell, 0.1–1) for the joints between them."""
    import zlib

    name = obj.name.lower()
    chosen = [
        i
        for i, m in enumerate(slots)
        if any(w in name for w in CELL_WORDS) or (m is not None and any(w in m.name.lower() for w in CELL_WORDS))
    ]
    if not chosen:
        return
    obj["nb_cell_slots"] = chosen
    mesh = obj.data
    scale = obj.matrix_world.to_scale()
    factor = abs(scale[0] * scale[1] * scale[2]) ** (2 / 3)
    faces = [f for f in mesh.polygons if f.material_index in chosen]
    if not faces:
        return
    # Most of the panel's area in small faces: the cells are modelled (a panel of one face and thin sides is not).
    small = sum(f.area for f in faces if f.area * factor <= 16 * CELL_AREA)
    if small < 0.5 * sum(f.area for f in faces):
        return
    obj["nb_cell_faces"] = True
    attr = mesh.attributes.get("nb_cell") or mesh.attributes.new("nb_cell", "FLOAT", "FACE")
    for f in mesh.polygons:
        attr.data[f.index].value = (
            0.1 + 0.9 * (zlib.crc32(f"{obj.name}:{f.index}".encode()) % 997) / 997 if f.material_index in chosen else 0.0
        )


def mark_foliage(obj, faces=None) -> None:
    """The faces of a crown or a bush marked (all, or those `faces` says): they give no lines inside, only their
    outline (render.py)."""
    mesh = obj.data
    attr = mesh.attributes.get("freestyle_face") or mesh.attributes.new("freestyle_face", "BOOLEAN", "FACE")
    attr.data.foreach_set("value", faces if faces is not None else [True] * len(mesh.polygons))
    obj["nb_foliage"] = True


#: A material darker than this (its colour's brightness, 0…1 as shown on the screen) is drawn as ベタ: a black van's
#: paint is about 0.03 in light, 0.19 shown.
DARK_PAINT = 0.25


def _brightness(mat) -> float:
    """How bright a material's colour shows: the darker of its Principled BSDF's Base Color and its viewport colour
    (a .blend drawn with an emission shader keeps its real colour only in the viewport's)."""
    colours = [mat.diffuse_color]
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED" and not node.inputs["Base Color"].is_linked:
                colours.append(node.inputs["Base Color"].default_value)
    shown = []
    for c in colours:
        linear = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        shown.append(12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055)
    return min(shown)


#: A thing counts as a ground (a lot, a lawn, a terrace) when its faces looking up cover at least FLAT_AREA m² and
#: at least FLAT_SHARE of the ground it stands on, and it is at most FLAT_HEIGHT m high (its edges, banks and steps
#: included; a house with its floors and roof is not a ground).
FLAT_HEIGHT = 2.0
FLAT_AREA = 12.0
FLAT_SHARE = 0.5
#: …and its top at most this far above the place's lowest surface (a ground lies low; a flat roof is not one).
GROUND_RISE = 3.0
FLAT = "白地"
#: What a flat surface keeps: ベタ, glass and water are not ground.
KEEP_ON_FLAT = ("黒い塗装", "ガラス", "水")


def _flat_and_large(obj, lowest: float) -> bool:
    mw = obj.matrix_world
    points = [mw @ Vector(c) for c in obj.bound_box]
    xs, ys, zs = ([p[i] for p in points] for i in range(3))
    footprint = (max(xs) - min(xs)) * (max(ys) - min(ys))
    if max(zs) - min(zs) > FLAT_HEIGHT or max(zs) > lowest + GROUND_RISE or footprint < FLAT_AREA:
        return False
    turn = mw.to_3x3().inverted_safe().transposed()
    scale = abs(mw.to_scale().x * mw.to_scale().y)
    up = sum(p.area * scale for p in obj.data.polygons if (turn @ p.normal).normalized().z > 0.9)
    return up >= FLAT_AREA and up >= FLAT_SHARE * footprint


def add_place(place: dict):
    """The place's collection from its .blend (appended, so the scene is whole on its own), without its cameras, its
    lights (the development lights the scene) and the mannequins left in it; what the author moves is moved, what
    the author hides is left out. Each mesh's materials get a library material by their names (materials.py)."""
    path = Path(place["file"])
    wanted = place.get("collection") or place["name"]
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        if wanted in src.collections:
            dst.collections = [wanted]
        else:
            dst.objects = list(src.objects)
    coll = collection("place")
    band_collection("near").children.link(coll)
    bpy.context.scene.collection.children.unlink(coll)
    for c in getattr(dst, "collections", []) or []:
        if c is not None:
            coll.children.link(c)
    for o in getattr(dst, "objects", []) or []:
        if o is not None:
            coll.objects.link(o)
    hide = place.get("hide") or []
    for o in list(coll.all_objects):
        if o.type in ("CAMERA", "LIGHT") or _is_dummy(o.name) or _hidden(o.name, hide):
            for c in list(o.users_collection):
                c.objects.unlink(o)
    by_name = {o.name: o for o in coll.all_objects}
    for move in place.get("moves") or []:
        o = by_name.get(move["object"])
        if o is None:
            continue
        if move.get("positionM"):
            o.location = Vector(move["positionM"])
        if move.get("turnDeg") is not None:
            o.rotation_euler.z = math.radians(move["turnDeg"])
        if move.get("show"):
            for shown in (o, *o.children_recursive):
                shown.hide_render = False
    # What the .blend leaves out of its renders (a van switched off for some takes) is not part of the place, unless
    # the author shows it (moves[].show): else it would cast shadows in the check that the picture does not show.
    for o in list(coll.all_objects):
        if o.hide_render:
            for c in list(o.users_collection):
                c.objects.unlink(o)
    meshes = [o for o in coll.all_objects if o.type == "MESH"]
    lowest = min((min((o.matrix_world @ Vector(c)).z for c in o.bound_box) for o in meshes), default=0.0)
    for o in meshes:
        slots = [s.material for s in o.material_slots] or [None]
        # The object's own name and its material's first, then its collections' (H_plants, 植栽…) as a fallback; a
        # paint the modeller made very dark is ベタ whatever its name (a black van's body).
        groups = [c.name for c in o.users_collection]
        guessed = []
        for mat in slots:
            n = mat.name if mat else ""
            g = guess_part(o.name, n)
            if g == DEFAULT:
                g = guess_part(o.name, n, *groups)
            if mat is not None and g not in ("ガラス",) and _brightness(mat) < DARK_PAINT:
                g = "黒い塗装"
            guessed.append(g)
        # A large flat surface (a lot's ground, a lawn, a terrace, a flat roof) stays white as a manga leaves it, its
        # shadows toned: a whole ground in grey weighs the picture down.
        if _flat_and_large(o, lowest):
            guessed = [g if g in KEEP_ON_FLAT else FLAT for g in guessed]
            o["nb_ground"] = True
            mark_material_borders(o)
        o["nb_place_materials"] = guessed
        if any(g == "黒い塗装" for g in guessed):
            mark_sharp(o)
        leafy = [g in FOLIAGE for g in guessed]
        # Too fine for the pen: the whole object if its name says so, else the slots whose material's name does (a
        # roof kit's solar slot, not its parapet).
        whole = any(w in o.name.lower() for w in FINE_WORDS)
        leafy = [f or whole or (m is not None and any(w in m.name.lower() for w in FINE_WORDS)) for f, m in zip(leafy, slots)]
        mark_cells(o, slots)
        if any(leafy):
            mark_foliage(o, [leafy[min(poly.material_index, len(leafy) - 1)] for poly in o.data.polygons])
    return coll


def build(plan: dict) -> dict:
    """The whole scene for a plan. Returns the objects to measure: {"objects": {id: [objs]}, "figures": {...}, "edges": [objs]}."""
    reset()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    set_camera(plan)
    world = bpy.data.worlds.new(PREFIX + "world")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (1, 1, 1, 1)
    scene.world = world
    measured = {"objects": {}, "figures": {}, "gauges": {}, "edges": [], "room": [], "place": [], "world": world, "panorama": None}
    for band in BANDS:
        band_collection(band)
    if plan.get("ground"):
        measured["edges"].append(add_ground(plan["ground"]))
    if plan.get("place"):
        coll = add_place(plan["place"])
        measured["place"] = [o for o in coll.all_objects if o.type == "MESH"]
        measured["edges"] += measured["place"]
    if plan.get("room"):
        room = add_room(plan["room"])
        measured["room"] = [room]
        measured["edges"].append(room)
    for ref in plan.get("references", []):
        posts = band_collection("near")
        measured["edges"].append(add_box(PREFIX + ref["id"], ref["centreM"], ref["sizeM"], "X", posts, tone_material("proxy")))
    for obj in plan.get("objects", []):
        p = obj["placed"]
        band = obj.get("band", "near")
        material = tone_material(f"proxy_{band}", lift=TONE_LIFT[band])
        if plan.get("detail") and obj.get("asset"):
            parts = add_thing(obj, plan["camera"]["positionM"], band_collection(band))
            if parts:
                for part in parts:
                    part["nb_band"] = band
                    if not part.data.materials:
                        part.data.materials.append(material)
                measured["objects"][obj["id"]] = parts
                continue
        if plan.get("detail") and obj.get("parts"):
            parts = add_shape(obj, plan["camera"]["positionM"], band_collection(band), material)
            for part in parts:
                part["nb_band"] = band
            # A shape fills its box, but a roof or a crown leaves the box's corners empty: its range is measured by
            # the box it was made in (not drawn), the box as the Blockout had it.
            measured["objects"][obj["id"]] = parts
            measured["gauges"][obj["id"]] = {"centreM": list(p["centreM"]), "sizeM": list(p["sizeM"]), "along": p["along"]}
            measured["edges"] += parts
            continue
        box = add_box(PREFIX + "obj_" + obj["id"], p["centreM"], p["sizeM"], p["along"], band_collection(band), material)
        box["nb_label"] = obj["label"]
        box["nb_band"] = band
        measured["objects"][obj["id"]] = [box]
        measured["edges"].append(box)
    for fig in plan.get("figures", []):
        p = fig["placed"]
        band = fig.get("band", "near")
        material = tone_material(f"figure_{band}", base=-0.15, lift=TONE_LIFT[band])
        man = add_figure(PREFIX + "fig_" + fig["id"], p["centreM"], p["sizeM"][2], band_collection(band), material)
        measured["figures"][fig["id"]] = [man]
    if plan.get("far"):
        measured["panorama"] = add_far(plan["far"])["panorama"]
    bpy.context.view_layer.update()
    return measured
