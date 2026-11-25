# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a Blockout plan in Blender (runs inside Blender: bpy).

Everything comes from the plan (plan.py): the camera's lens, shift and
matrix, the ground grid, the place (a .blend collection from 素材), boxes
for things, posts, and simple figures. Nothing is decided here.
"""

from __future__ import annotations

from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

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


def tone_material(name: str, base: float = 0.0, flat: float | None = None):
    """Grey by which way a face looks (three steps), as light from LIGHT; `flat` for one grey."""
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
    els[0].position, els[0].color = 0.0, (0.58 + base, 0.58 + base, 0.58 + base, 1)
    els[1].position, els[1].color = 0.55, (0.78 + base, 0.78 + base, 0.78 + base, 1)
    third = els.new(0.8)
    third.color = (0.93, 0.93, 0.93, 1)
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
    """Level grids in rings (the plan's), each cell's edges marked so they are drawn: they run to the vanishing points."""
    z = ground.get("z", 0.0)
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


def add_place(place: dict):
    """The place's collection from its .blend (appended, so the scene is whole on its own)."""
    path = Path(place["file"])
    wanted = place.get("collection") or place["name"]
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        if wanted in src.collections:
            dst.collections = [wanted]
        else:
            dst.objects = list(src.objects)
    coll = collection("place")
    for c in getattr(dst, "collections", []) or []:
        if c is not None:
            coll.children.link(c)
    for o in getattr(dst, "objects", []) or []:
        if o is not None and o.type != "CAMERA":
            coll.objects.link(o)
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
    measured = {"objects": {}, "figures": {}, "edges": []}
    if plan.get("ground"):
        measured["edges"].append(add_ground(plan["ground"]))
    if plan.get("place"):
        coll = add_place(plan["place"])
        measured["edges"] += [o for o in coll.all_objects if o.type == "MESH"]
    proxies = collection("proxies")
    for ref in plan.get("references", []):
        measured["edges"].append(add_box(PREFIX + ref["id"], ref["centreM"], ref["sizeM"], "X", proxies, tone_material("proxy")))
    for obj in plan.get("objects", []):
        p = obj["placed"]
        box = add_box(PREFIX + "obj_" + obj["id"], p["centreM"], p["sizeM"], p["along"], proxies, tone_material("proxy"))
        box["nb_label"] = obj["label"]
        measured["objects"][obj["id"]] = [box]
        measured["edges"].append(box)
    figures = collection("figures")
    for fig in plan.get("figures", []):
        p = fig["placed"]
        man = add_figure(PREFIX + "fig_" + fig["id"], p["centreM"], p["sizeM"][2], figures, tone_material("figure", base=-0.15))
        measured["figures"][fig["id"]] = [man]
    bpy.context.view_layer.update()
    return measured
