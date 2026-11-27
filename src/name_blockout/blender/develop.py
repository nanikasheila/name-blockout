# SPDX-License-Identifier: GPL-3.0-or-later
"""The development render of a built scene (runs inside Blender): the light
from the 3D side, the drawing from the manga side.

1. 光: every surface white and matte, lit by the sun alone. Where it gets
   (almost) no sun is in shadow: faces turned away and shadows cast, on a
   ground that is there only for this (it is not drawn with lines).
2. The tones of each material twice, flat (emission, exact): as lit, and as
   in shadow; ベタ materials black in both.
3. トーン = the lit tones, the shadow tones where 光 says shadow.
   影 = the shadow alone (a grey on transparent). 線画 as in the Blockout
   (thinner with distance). 完成 = トーン and 線画 on white.

ベタ: the lines over a solid black are drawn white (else they vanish in it).

Then the check of the light, looked up in 光 against the geometry (Blender's
ray casts, not the render):
- for each thing on the ground, points of ground where its shadow must fall
  (away from the sun) and where it must not (toward the sun);
- a grid of points over the whole picture: the surface the camera sees there
  must be in shadow when it is turned away from the light or something stands
  between it and the light, and lit when it faces the light with nothing in
  between (points near a shadow's edge, in a soft shadow's half-light or at a
  grazing angle are left out).
When no point could be tried the check says so (照合せず) instead of passing
quietly.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

from ..lines import boundary_lines, tone_floor
from ..materials import DEFAULT, LIBRARY, seen
from .picture import load as _load
from .picture import save as _save
from .render import inner_px, line_px, render_passes, setup
from .scene import GROUND_BELOW_PLACE_M, PREFIX, collection, ground_level, mark_foliage

#: Set (to anything) to keep the working passes beside the pictures (_depth.exr, _normal.exr…), for looking into
#: how a line or a tone came out.
KEEP_ENV = "NAME_BLOCKOUT_KEEP"
#: The object numbers the depth pass tells surfaces by: the backdrop's (the far band: flat tones, no lines) and the
#: ground's (the light's ground, a place's lot or lawn: no line where it ends against the sky far off).
BACKDROP_INDEX = 1
GROUND_INDEX = 2
#: …and natural things' (trees, bushes: told by their shade, no outline of their own).
NATURAL_INDEX = 3
#: Under this share of the light a white face gets facing the sun, a pixel is in shadow.
SHADOW_SHARE = 0.12
SHADOW_RGBA = (0.25, 0.25, 0.3, 0.55)
#: The mannequins: white in the light, a light tone in shadow (they stand for people drawn later).
FIGURE = {"tone": 0.0, "shadowTone": 0.25, "beta": False}
NO_SUN_ALL_SHADOW = ("dawn", "dusk", "night")
#: The sky's tone (density) when the sun is down.
SKY_TONES = {"dawn": 0.2, "dusk": 0.35, "night": 0.8}
#: Under this brightness (as shown) a tone counts as ベタ, and the lines over it are drawn white.
BETA_SHOWN = 0.12
#: The grid of the picture's check (across, down), and the shares it must agree in.
GRID = (32, 20)
GROUND_SHARE = 0.75
FACE_SHARE = 0.85
#: A face lit squarer than this to the light must be lit; one turned away past this must be in shadow.
FACE_LIT = 0.3
FACE_AWAY = -0.02
#: A light higher than this (degrees) is overhead: the ground beside a thing is not checked, its shadow is at its foot.
OVERHEAD_DEG = 70.0
#: A surface counts as looking up (a floor, the ground) when its normal's z is above this.
UP_NORMAL = 0.9
#: A face looking up in the light is the lightest of a thing's three (top, lit side, shadow side): its tone is this
#: much less dense (a concrete roof's top comes out white, as the ground does; a tiled roof keeps a lighter tone).
#: Tones from TOP_KEEPS up stay as they are (a solar panel's dark cells), and so do a crown's lumps.
TOP_LIGHTER = 0.15
TOP_KEEPS = 0.5
#: The texture lines (a floor's joints, a wall's boards) are drawn up to this many foregrounds off, ending within
#: TEXTURE_END of that distance: farther off they would close up into a grey.
TEXTURE_REACH = 4.0
TEXTURE_END = 0.1
#: Under the ceiling's light, a place's faces this high above the floor under the camera (m) are the ceiling (and
#: what is over it): they let the light through.
CEILING_OVER_FLOOR = 2.0


def _emission(name: str, grey: float):
    mat = bpy.data.materials.get(PREFIX + name) or bpy.data.materials.new(PREFIX + name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (grey, grey, grey, 1.0)
    links.new(emit.outputs[0], out.inputs[0])
    return mat


#: A solar panel's cell (m), the share of a cell its joint takes, how much darker the joint is (density), and the
#: least a cell may show (px): smaller, cells are drawn by twos (fours…), as an artist simplifies a far roof.
CELL_M = 0.16
CELL_JOINT = 0.1
CELL_DARKER = 0.25
CELL_MIN_PX = 7.0
#: A joint between cells: nearly white (a tone's density).
CELL_JOINT_TONE = 0.08


def _cells(name: str, grey: float, joint: float, axes: tuple[int, int], size: tuple[float, float], start=(0.0, 0.0)):
    """A flat tone with a grid of joints over it (a solar panel's cells), along two of the mesh's own axes, from
    the panel's corner (`start`, in the mesh's units)."""
    mat = bpy.data.materials.get(PREFIX + name) or bpy.data.materials.new(PREFIX + name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    coords = nodes.new("ShaderNodeTexCoord")
    split = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coords.outputs["Object"], split.inputs[0])
    on_joint = None
    for axis, cell, first in zip(axes, size, start):
        moved = nodes.new("ShaderNodeMath")
        moved.operation = "SUBTRACT"
        moved.inputs[1].default_value = first
        links.new(split.outputs["XYZ"[axis]], moved.inputs[0])
        scaled = nodes.new("ShaderNodeMath")
        scaled.operation = "DIVIDE"
        scaled.inputs[1].default_value = cell
        links.new(moved.outputs[0], scaled.inputs[0])
        frac = nodes.new("ShaderNodeMath")
        frac.operation = "FRACT"
        links.new(scaled.outputs[0], frac.inputs[0])
        near = nodes.new("ShaderNodeMath")
        near.operation = "LESS_THAN"
        near.inputs[1].default_value = CELL_JOINT
        links.new(frac.outputs[0], near.inputs[0])
        if on_joint is None:
            on_joint = near
        else:
            either = nodes.new("ShaderNodeMath")
            either.operation = "MAXIMUM"
            links.new(on_joint.outputs[0], either.inputs[0])
            links.new(near.outputs[0], either.inputs[1])
            on_joint = either
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = (grey, grey, grey, 1.0)
    mix.inputs["B"].default_value = (joint, joint, joint, 1.0)
    links.new(on_joint.outputs[0], mix.inputs["Factor"])
    emit = nodes.new("ShaderNodeEmission")
    links.new(mix.outputs["Result"], emit.inputs["Color"])
    links.new(emit.outputs[0], out.inputs[0])
    return mat


def cell_grid(obj, scene, slot: int | None = None):
    """The panel's two long axes (its mesh's; the faces of material `slot` only, if given), a cell's size along them
    in the mesh's units (cells grouped by twos until one shows at least CELL_MIN_PX, the panel split evenly) and its
    corner; None if it has no face to speak of."""
    mesh = obj.data
    if slot is None:
        points = [tuple(c) for c in obj.bound_box]
    else:
        points = [tuple(mesh.vertices[v].co) for f in mesh.polygons if f.material_index == slot for v in f.vertices]
    if not points:
        return None
    lo = [min(c[i] for c in points) for i in range(3)]
    hi = [max(c[i] for c in points) for i in range(3)]
    scale = obj.matrix_world.to_scale()
    extent = [(hi[i] - lo[i]) * abs(scale[i]) for i in range(3)]
    axes = tuple(sorted(sorted(range(3), key=lambda i: -extent[i])[:2]))
    if min(extent[a] for a in axes) < CELL_M:
        return None
    cell = CELL_M
    cam = scene.camera
    if cam is not None and cam.data.type == "PERSP":
        f_px = scene.render.resolution_x * cam.data.lens / cam.data.sensor_width
        centre = obj.matrix_world @ Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
        d = max((centre - cam.matrix_world.translation).length, 0.1)
        while f_px * cell / d < CELL_MIN_PX and cell < 2.0:
            cell *= 2
    # Whole cells across the panel (a panel's cells fill it), each near `cell`; the first joint just inside its edge.
    size = tuple((hi[a] - lo[a]) / max(1, round(extent[a] / cell)) for a in axes)
    start = tuple(lo[a] - size[i] * CELL_JOINT / 2 for i, a in enumerate(axes))
    return axes, size, start


def _srgb(linear: float) -> float:
    return 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055


def _linear(shown: float) -> float:
    """The light that shows as `shown` on the screen (the pictures are stored as sRGB)."""
    return shown / 12.92 if shown <= 0.04045 else ((shown + 0.055) / 1.055) ** 2.4


def _white_matte():
    mat = bpy.data.materials.get(PREFIX + "white_matte") or bpy.data.materials.new(PREFIX + "white_matte")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(diffuse.outputs[0], out.inputs[0])
    return mat


def add_light_ground(plan: dict, under: float = 0.0):
    """A ground to catch shadows (as far as the ground grid goes, else 200 m round the camera), at height `under`."""
    ground = plan.get("ground") or {}
    rings = ground.get("rings") or []
    extent = min(400.0, rings[-1]["extentM"]) if rings else 200.0
    cx, cy = ground.get("centreM") or plan["camera"].get("positionM", [0, 0])[:2]
    if ground.get("rectM"):  # a room's floor: as far as its walls (a little beyond, under them)
        x0, y0, x1, y1 = ground["rectM"]
        cx, cy, extent = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2 + 0.5
    mesh = bpy.data.meshes.new(PREFIX + "light_ground")
    mesh.from_pydata(
        [
            (cx - extent, cy - extent, under),
            (cx + extent, cy - extent, under),
            (cx + extent, cy + extent, under),
            (cx - extent, cy + extent, under),
        ],
        [],
        [(0, 1, 2, 3)],
    )
    obj = bpy.data.objects.new(PREFIX + "light_ground", mesh)
    collection("light_ground").objects.link(obj)
    return obj


def add_sun(light: dict):
    sun = light.get("sun")
    if not sun or not sun.get("strength"):
        return None
    data = bpy.data.lights.new(PREFIX + "sun", "SUN")
    data.energy = sun["strength"]
    data.angle = math.radians(sun.get("angleDeg", 0.6))
    obj = bpy.data.objects.new(PREFIX + "sun", data)
    collection("light").objects.link(obj)
    # A sun shines along its −Z: turn +Z toward the sun.
    obj.rotation_euler = Vector(sun["direction"]).to_track_quat("Z", "Y").to_euler()
    return obj


def _render(path: Path, samples: int, transparent: bool = True, exact: bool = False) -> np.ndarray:
    """A render loaded back (rows from the top); `exact`: as floats (OpenEXR), not as shown on a screen."""
    scene = bpy.context.scene
    scene.cycles.samples = samples
    scene.render.film_transparent = transparent
    scene.render.use_freestyle = False
    scene.render.filepath = str(path)
    settings = scene.render.image_settings
    keep = (settings.file_format, settings.color_depth, scene.cycles.use_denoising, scene.cycles.filter_width)
    if exact:
        # Values to read (a height, an object's number): no denoiser or wide pixel filter mixing two surfaces'.
        settings.file_format = "OPEN_EXR"
        settings.color_depth = "32"
        scene.cycles.use_denoising = False
        scene.cycles.filter_width = 0.01
    bpy.ops.render.render(write_still=True)
    if exact:
        settings.file_format, settings.color_depth, scene.cycles.use_denoising, scene.cycles.filter_width = keep
    image = bpy.data.images.load(str(path), check_existing=False)
    w, h = image.size
    pixels = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels.reshape(h, w, 4)[::-1]  # rows from the top


def _over(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    a = top[..., 3:4]
    out = top.copy()
    out[..., :3] = top[..., :3] * a + bottom[..., :3] * bottom[..., 3:4] * (1 - a)
    out[..., 3:4] = a + bottom[..., 3:4] * (1 - a)
    rgb = np.where(out[..., 3:4] > 1e-6, out[..., :3] / np.maximum(out[..., 3:4], 1e-6), 0.0)
    return np.concatenate([rgb, out[..., 3:4]], axis=-1)


def _set_materials(built: dict, plan: dict, which: str, ground) -> None:
    """Every thing as its material's flat tone (`which`: "tone" lit, "shadowTone" in shadow; ベタ black)."""
    materials = plan["develop"]["materials"]
    lighting = plan["develop"]["lighting"]

    def grey(m):
        # A tone's density is how dark it shows: 1 − density on the screen (glass: as this light shows it).
        m = seen(m, lighting.get("setting"), lighting.get("timeOfDay"))
        return 0.0 if m["beta"] else _linear(1.0 - m[which])

    for ident, objs in list(built["objects"].items()) + [(f"figure:{k}", v) for k, v in built["figures"].items()]:
        m = materials.get(ident) or (FIGURE if ident.startswith("figure:") else None)
        if not m:
            continue
        mat = _emission(f"dev_{ident.replace(':', '_')}_{which}", grey(m))
        for obj in objs:
            # A part of a 素材 the author gave its own material (look.materials by the part's name).
            part = materials.get(_part_name(obj.get("nb_part", "")))
            own = _emission(f"dev_part_{_part_name(obj['nb_part'])}_{which}", grey(part)) if part and part.get("part") else None
            # A part of a shape the tool made carries its own material (glass, tyres…), unless the author named one.
            made = LIBRARY.get(obj.get("nb_material", ""))
            if own is None and made is not None:
                own = _emission(f"dev_lib_{made.name}_{which}", grey(made.as_dict()))
            obj.data.materials.clear()
            obj.data.materials.append(own or mat)
    # A place's meshes: each material slot as the library material its names suggest (or the author's, by name).
    for obj in list(built.get("place", [])) + list(built.get("surroundings", [])):
        guessed = obj.get("nb_place_materials") or []
        slots = obj.material_slots
        if not slots:
            obj.data.materials.append(None)
        for i, slot in enumerate(obj.material_slots):
            name = guessed[i] if i < len(guessed) else DEFAULT
            m = materials.get(_part_name(obj.name)) or LIBRARY.get(name, LIBRARY[DEFAULT]).as_dict()
            slot.link = "OBJECT"
            # A solar panel: dark cells with light joints between them, as a manga draws one (too fine for the pen).
            # Where the model's faces are the cells, the joints go between them on the picture (cell_gaps);
            # where a panel is one face, a grid is laid over it.
            cells = i in (obj.get("nb_cell_slots") or []) and not m["beta"]
            dark = _linear(max(0.0, 1.0 - m[which] - CELL_DARKER))
            grid = cell_grid(obj, bpy.context.scene, i) if cells and not obj.get("nb_cell_faces") else None
            if grid:
                light = _linear(1.0 - CELL_JOINT_TONE)
                slot.material = _cells(f"dev_cells_{obj.name}_{i}_{which}", dark, light, *grid)
            elif cells:
                slot.material = _emission(f"dev_cell_faces_{m['name']}_{which}", dark)
            else:
                slot.material = _emission(f"dev_lib_{m['name']}_{which}", grey(m))
    walls = materials.get("walls")
    if walls:
        mat = _emission(f"dev_walls_{which}", grey(walls))
        for obj in built.get("room", []):
            obj.data.materials.clear()
            obj.data.materials.append(mat)
    g = materials.get("ground")
    if g and ground is not None:
        ground.data.materials.clear()
        ground.data.materials.append(_emission(f"dev_ground_{which}", grey(g)))


def develop_passes(plan: dict, built: dict, out_dir: Path, samples: int = 16) -> tuple[dict, dict]:
    """The development's pictures, and the check of its light."""
    scene = bpy.context.scene
    layer = bpy.context.view_layer
    out_dir.mkdir(parents=True, exist_ok=True)
    light = plan["develop"]["lighting"]
    w, h = plan["render"]["sizePx"]
    scene.render.resolution_x, scene.render.resolution_y = w, h
    # Under a place, below its lowest surface: on the same plane as a floor of the place the two would shade each
    # other black (as the grid does, below), and where the place has ground of its own that takes the shadows.
    place = built.get("place") or []
    level = ground_level(place)
    ground = add_light_ground(plan, level)
    for obj in place:
        # A place's ground lying on the ground round it (a lot, a road: flat, at its lowest) casts no shadow: its
        # edge would draw a strip of shade on the light's ground just under it.
        if obj.get("nb_ground") and max((obj.matrix_world @ Vector(c)).z for c in obj.bound_box) <= level + 2 * GROUND_BELOW_PLACE_M:
            obj.visible_shadow = False
            obj["nb_noshadow"] = True
    sun = add_sun(light)
    keep_world = scene.world

    # 線画 (and 遠景) as in the Blockout, without the light's ground.
    # 0. The boundaries (lines.py): each pixel's depth and normal as the finished picture shows them (the light's
    # ground in, the grid on the same plane out), drawn twice as large for a small picture so thin lines stay
    # smooth. A line is as thick as its boundary is deep; far things get none, and are told by their tones.
    setup(plan)
    tone_far()
    ground.pass_index = GROUND_INDEX
    for obj in place:
        if obj.get("nb_ground"):
            obj.pass_index = GROUND_INDEX
    for obj in scene.objects:
        if obj.get("nb_natural") and obj.pass_index == 0:
            obj.pass_index = NATURAL_INDEX
            if obj.type == "MESH":
                # All of it (a trunk's edges, a rock's facets as much as a crown's lumps): no folds, no texture
                # lines. A made part of it (the pot of a potted plant) stays as it is, and keeps its lines.
                slots = list(obj.get("nb_natural_slots") or [])
                if slots and not all(slots):
                    marked = obj.data.attributes.get("freestyle_face")
                    already = [m.value for m in marked.data] if marked else [False] * len(obj.data.polygons)
                    mark_foliage(obj, [was or slots[min(p.material_index, len(slots) - 1)] for was, p in zip(already, obj.data.polygons)])
                else:
                    mark_foliage(obj)
    grid = bpy.data.collections.get(PREFIX + "ground")
    if grid is not None:
        grid.hide_render = True
    # A hairline (a wire between two poles: as thin as a pen's finest line, and solid black) is its own line: it
    # is no boundary to draw a line along on either side, nor has it folds to draw (the 線画 below).
    hairlines = [obj for obj in scene.objects if obj.get("nb_hairline") and not obj.hide_render]
    for obj in hairlines:
        obj.hide_render = True
    by = 2 if w * h < SUPERSAMPLE_UNDER else 1
    scene.render.resolution_percentage = 100 * by
    layer.material_override = _depths()
    depths = _render(out_dir / "_depth.exr", 1, exact=True)
    layer.material_override = _normals()
    normals = _render(out_dir / "_normal.exr", 1, exact=True)[..., :3] * 2.0 - 1.0
    layer.material_override = None
    scene.render.resolution_percentage = 100
    if grid is not None:
        grid.hide_render = False
    seen = depths[..., 3] > 0.5
    backdrop = seen & (np.abs(depths[..., 2] - BACKDROP_INDEX) < 0.5)
    lot = seen & (np.abs(depths[..., 2] - GROUND_INDEX) < 0.5)
    # A natural thing's natural faces (marked above): its made parts are lined as any made thing.
    natural = seen & (np.abs(depths[..., 2] - NATURAL_INDEX) < 0.5) & (depths[..., 1] > 0.5)
    ink, line_info = boundary_lines(
        depths[..., 0],
        seen,
        normals,
        depths[..., 1] > 0.5,
        plan["render"]["dpi"] / 25.4,
        by,
        flat=backdrop,
        ground=lot,
        natural=natural,
    )
    del natural
    # Where the lines thin out with distance the tones take over: a standing thing there (not the ground or a
    # roof's top, not the backdrop) is given at least a light tone, so its shape reads without a line round it.
    standing = seen & ~backdrop & (normals[..., 2] < UP_NORMAL)
    distance = depths[::by, ::by, 0][:h, :w].copy()
    least_tone = tone_floor(distance, standing[::by, ::by][:h, :w], line_info["foregroundM"])
    # The tops in the light (not a crown's lumps), for the tones below.
    tops = (seen & ~backdrop & ~standing & (depths[..., 1] < 0.5))[::by, ::by][:h, :w].copy()
    del depths, normals, seen, backdrop, lot, standing

    # 線画: the texture lines (marked edges, the ground's grid) by Freestyle, fading with distance, without the
    # light's ground; 遠景: the far band alone, its tones.
    collection("light_ground").hide_render = True
    passes = [p for p in ("線画", "遠景") if p in plan["render"]["passes"]]
    files = render_passes(plan, out_dir, passes=passes, texture_from=line_info["foregroundM"])
    collection("light_ground").hide_render = False
    for obj in hairlines:
        obj.hide_render = False
    # The grid lies on the same plane as the light's ground: the two would shade each other black.
    grid = bpy.data.collections.get(PREFIX + "ground")
    if grid is not None:
        grid.hide_render = True
    scene.render.use_freestyle = False
    for ls in layer.freestyle_settings.linesets:
        ls.show_render = True

    # Indoors under the ceiling's light, a place's ceilings and roofs (all above the eye) let it through: the light
    # stands for the lamps in the room, not a sun over the house.
    # A ceiling is often one mesh with its walls: its faces above the eye are split off to let the light through.
    if light.get("key") == "interior":
        cut = ceiling_cut(scene, plan["camera"].get("positionM", [0, 0, 1.5]))
        for obj in list(built.get("place", [])):
            if min((obj.matrix_world @ Vector(c)).z for c in obj.bound_box) > cut:
                above = obj
            else:
                above = split_above(obj, cut)
                if above is None:
                    continue
                built["place"].append(above)
            above.visible_shadow = False
            above["nb_noshadow"] = True

    # 1. 光: white and matte, the sun alone (the sky black), as strong as π so a face square to it is exactly 1.
    # A wide light (a soft shadow) needs more samples, and the denoiser, or its shadow's edge comes out grainy.
    if sun is not None:
        sun.data.energy = math.pi
    soft = sun is not None and sun.data.angle > math.radians(5)
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        scene.cycles.use_denoising = False
    dark = bpy.data.worlds.new(PREFIX + "dark")
    dark.use_nodes = True
    dark.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    scene.world = dark
    scene.cycles.max_bounces = 0
    layer.material_override = _white_matte()
    lit = _render(out_dir / "光.png", samples * 4 if soft else samples)
    scene.cycles.use_denoising = False
    layer.material_override = None
    alpha = lit[..., 3]
    word = light.get("timeOfDay")
    if sun is not None:
        # The picture is stored for the screen (sRGB): compare with the share as stored.
        shadow = (lit[..., 0] < _srgb(SHADOW_SHARE)) & (alpha > 0.5)
        # A wall lit at a grazing angle sits near the share all over, and its noise would speckle it: each pixel
        # goes with the most of those round it.
        shadow = majority(shadow, 2) & (alpha > 0.5)
    elif word in NO_SUN_ALL_SHADOW:
        shadow = alpha > 0.5
    else:
        shadow = np.zeros_like(alpha, dtype=bool)

    # 2. The tones, lit and in shadow (flat: no light needed).
    scene.world = keep_world
    _set_materials(built, plan, "tone", ground)
    lit_tones = _render(out_dir / "_lit.png", 4)
    _set_materials(built, plan, "shadowTone", ground)
    shadow_tones = _render(out_dir / "_shadow.png", 4)
    # Which solar cell (a face of the model) each pixel shows: light joints between them.
    cell_ids = None
    if any(o.get("nb_cell_faces") for o in built.get("place", [])):
        layer.material_override = _face_value("nb_cell")
        cell_ids = _render(out_dir / "_cells.exr", 1, exact=True)[..., 0]
    layer.material_override = None

    # 3. Put together; at dawn, dusk and night the sky is toned too.
    tone = np.where(shadow[..., None], shadow_tones, lit_tones)
    if sun is not None:
        tone[..., :3] = top_lighter(tone[..., :3], tops & ~shadow & (tone[..., 3] > 0.5))
    tone[..., :3] = np.minimum(tone[..., :3], (1.0 - least_tone)[..., None])
    if cell_ids is not None:
        gaps = cell_gaps(cell_ids, CELL_MIN_PX)
        # A joint as wide as a fine pen's line, kept inside the panel.
        r = max(0, round(inner_px(plan["render"]["dpi"]) / 2 - 1))
        if r:
            gaps = grow(gaps, r) & (cell_ids > 0.05)
        tone[gaps, :3] = 1.0 - CELL_JOINT_TONE
    sky = SKY_TONES.get(word)
    if sky:
        g = 1.0 - sky
        empty = tone[..., 3] < 1.0
        back = np.zeros_like(tone)
        back[...] = (g, g, g, 1.0)
        tone[empty] = _over(tone[empty][None], back[empty][None])[0]
    files["トーン"] = _save(out_dir / "トーン.png", tone)
    shade = np.zeros((h, w, 4), dtype=np.float32)
    shade[shadow] = SHADOW_RGBA
    files["影"] = _save(out_dir / "影.png", shade)
    white = np.ones((h, w, 4), dtype=np.float32)
    lines = _load(files["線画"]) if "線画" in files else np.zeros((h, w, 4), dtype=np.float32)
    dpi = plan["render"]["dpi"]
    reach = max(2, round(line_px(dpi) * 1.2))
    if "線画" in files:
        lines[..., 3] *= texture_reach(distance, line_info["foregroundM"])
        black = np.zeros((h, w, 4), dtype=np.float32)
        black[..., 3] = ink[:h, :w]
        lines = _over(black, lines)
        _save(files["線画"], lines)
    files["完成"] = _save(out_dir / "完成.png", _over(white_on_beta(lines, tone, reach), _over(tone, white)))
    check = shadow_check(plan, built, shadow, lit, sun)
    check["lines"] = line_info
    if not os.environ.get(KEEP_ENV):
        for name in ("_lit.png", "_shadow.png", "_depth.exr", "_normal.exr", "_cells.exr"):
            (out_dir / name).unlink(missing_ok=True)
    if grid is not None:
        grid.hide_render = False
    return files, check


def ceiling_cut(scene, camera_at) -> float:
    """The height over which a room's faces count as its ceiling: the floor under the camera + CEILING_OVER_FLOOR."""
    # The lowest surface under the camera (a camera on a loft or the stairs over a double-height room looks down past
    # the loft's floor; under a place with no floor of its own, the light's ground).
    depsgraph = bpy.context.evaluated_depsgraph_get()
    start, down = Vector(camera_at), Vector((0, 0, -1))
    floor = None
    for _ in range(32):
        hit, location, *_ = scene.ray_cast(depsgraph, start, down, distance=50.0)
        if not hit:
            break
        floor = location.z
        start = location + down * 1e-3
    return (floor if floor is not None else 0.0) + CEILING_OVER_FLOOR


def split_above(obj, z: float):
    """The faces of a mesh lying wholly above height `z` (in the world), moved to an object of their own (same
    materials, same place's materials); None when there are none or the mesh is all above."""
    import bmesh

    mw = obj.matrix_world
    mesh = obj.data
    above = [p.index for p in mesh.polygons if all((mw @ mesh.vertices[v].co).z > z for v in p.vertices)]
    if not above or len(above) == len(mesh.polygons):
        return None
    if mesh.users > 1:
        obj.data = mesh = mesh.copy()
    top = mesh.copy()
    keep = set(above)
    for target, wanted in ((mesh, lambda i: i not in keep), (top, lambda i: i in keep)):
        bm = bmesh.new()
        bm.from_mesh(target)
        bm.faces.ensure_lookup_table()
        gone = [f for f in bm.faces if not wanted(f.index)]
        bmesh.ops.delete(bm, geom=gone, context="FACES")
        bm.to_mesh(target)
        bm.free()
    piece = bpy.data.objects.new(obj.name + "_above", top)
    piece.matrix_world = mw.copy()
    for k in ("nb_place_materials", "nb_foliage", "nb_cell_slots", "nb_cell_faces"):
        if k in obj:
            piece[k] = obj[k]
    for coll in obj.users_collection:
        coll.objects.link(piece)
    return piece


def _face_value(name: str):
    """A material showing a face attribute's value (to be read back exactly)."""
    mat = bpy.data.materials.get(PREFIX + "face_" + name) or bpy.data.materials.new(PREFIX + "face_" + name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    attr = nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "GEOMETRY"
    attr.attribute_name = name
    emit = nodes.new("ShaderNodeEmission")
    links.new(attr.outputs["Fac"], emit.inputs["Strength"])
    emit.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(emit.outputs[0], out.inputs[0])
    return mat


def cell_gaps(ids: np.ndarray, min_px: float) -> np.ndarray:
    """The pixels between two cells (two faces with different ids, both cells: a panel's edge against the roof is
    its outline, drawn by the pen); none if the cells show smaller than `min_px` on average (they would be a blur)."""
    cell = ids > 0.05
    h, w = ids.shape
    gap = np.zeros((h, w), dtype=bool)
    for dy, dx in ((0, 1), (1, 0)):
        a = (slice(0, h - dy), slice(0, w - dx))
        b = (slice(dy, h), slice(dx, w))
        differ = cell[a] & cell[b] & (np.abs(ids[a] - ids[b]) > 1e-4)
        gap[a] |= differ
    n = len(np.unique(np.round(ids[cell], 4)))
    if n == 0 or math.sqrt(cell.sum() / n) < min_px:
        return np.zeros((h, w), dtype=bool)
    return gap


#: Under this many pixels the boundaries are drawn from passes twice as large (a 150 dpi panel's thin lines).
SUPERSAMPLE_UNDER = 4_000_000
#: The far band's tones: flat, lighter with distance (the air between), from the first density at the first
#: distance (m) to the second at the second. Far things have no lines: their shapes are told by these.
FAR_TONES = ((100.0, 0.26), (6000.0, 0.07))


def _depths():
    """A material showing each surface's depth from the camera (m), whether its face is marked soft
    (freestyle_face: a crown's lumps, a louvre's slats) and its object's number (BACKDROP_INDEX, GROUND_INDEX,
    else 0); to be read back exactly."""
    mat = bpy.data.materials.get(PREFIX + "depths") or bpy.data.materials.new(PREFIX + "depths")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    cam = nodes.new("ShaderNodeCameraData")
    marked = nodes.new("ShaderNodeAttribute")
    marked.attribute_type = "GEOMETRY"
    marked.attribute_name = "freestyle_face"
    rgb = nodes.new("ShaderNodeCombineXYZ")
    links.new(cam.outputs["View Z Depth"], rgb.inputs[0])
    links.new(marked.outputs["Fac"], rgb.inputs[1])
    info = nodes.new("ShaderNodeObjectInfo")
    links.new(info.outputs["Object Index"], rgb.inputs[2])
    emit = nodes.new("ShaderNodeEmission")
    links.new(rgb.outputs[0], emit.inputs["Color"])
    links.new(emit.outputs[0], out.inputs[0])
    return mat


def _normals():
    """A material showing each surface's normal (x, y, z as 0–1: ½ + ½ n), flat."""
    mat = bpy.data.materials.get(PREFIX + "normals") or bpy.data.materials.new(PREFIX + "normals")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    geo = nodes.new("ShaderNodeNewGeometry")
    half = nodes.new("ShaderNodeVectorMath")
    half.operation = "MULTIPLY_ADD"
    half.inputs[1].default_value = (0.5, 0.5, 0.5)
    half.inputs[2].default_value = (0.5, 0.5, 0.5)
    links.new(geo.outputs["Normal"], half.inputs[0])
    emit = nodes.new("ShaderNodeEmission")
    links.new(half.outputs["Vector"], emit.inputs["Color"])
    links.new(emit.outputs[0], out.inputs[0])
    return mat


def tone_far() -> None:
    """The far band's things in one flat tone each, lighter the farther (FAR_TONES)."""
    coll = bpy.data.collections.get(PREFIX + "band_far")
    if coll is None or not coll.all_objects:
        return
    (d0, t0), (d1, t1) = FAR_TONES
    mat = bpy.data.materials.get(PREFIX + "dev_far") or bpy.data.materials.new(PREFIX + "dev_far")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    cam = nodes.new("ShaderNodeCameraData")
    log = nodes.new("ShaderNodeMath")
    log.operation = "LOGARITHM"
    log.inputs[1].default_value = 10.0
    links.new(cam.outputs["View Distance"], log.inputs[0])
    shown = nodes.new("ShaderNodeMapRange")
    shown.clamp = True
    shown.inputs["From Min"].default_value = math.log10(d0)
    shown.inputs["From Max"].default_value = math.log10(d1)
    shown.inputs["To Min"].default_value = 1.0 - t0
    shown.inputs["To Max"].default_value = 1.0 - t1
    links.new(log.outputs[0], shown.inputs["Value"])
    # As shown on the screen → the light that shows so (about sRGB).
    light = nodes.new("ShaderNodeMath")
    light.operation = "POWER"
    light.inputs[1].default_value = 2.2
    links.new(shown.outputs["Result"], light.inputs[0])
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(light.outputs[0], emit.inputs["Strength"])
    links.new(emit.outputs[0], out.inputs[0])
    for o in coll.all_objects:
        if o.type == "MESH":
            o.data.materials.clear()
            o.data.materials.append(mat)
            o.pass_index = BACKDROP_INDEX


def majority(mask: np.ndarray, r: int) -> np.ndarray:
    """Each pixel set as most of the (2r+1)² square round it is (speckles go, edges stay)."""
    padded = np.pad(mask.astype(np.int32), r + 1, mode="edge")
    total = padded.cumsum(0).cumsum(1)
    n = 2 * r + 1
    h, w = mask.shape
    s = total[n : n + h, n : n + w] - total[0:h, n : n + w] - total[n : n + h, 0:w] + total[0:h, 0:w]
    return s * 2 > n * n


def erode(mask: np.ndarray, r: int) -> np.ndarray:
    """Where `mask` holds within r pixels all round (a square, in two passes)."""
    out = mask.copy()
    for axis in (0, 1):
        src = out.copy()
        for d in range(1, r + 1):
            out[(slice(d, None),) if axis == 0 else (slice(None), slice(d, None))] &= src[
                (slice(None, -d),) if axis == 0 else (slice(None), slice(None, -d))
            ]
            out[(slice(None, -d),) if axis == 0 else (slice(None), slice(None, -d))] &= src[
                (slice(d, None),) if axis == 0 else (slice(None), slice(d, None))
            ]
        edge = [slice(None)] * 2
        edge[axis] = slice(0, r)
        out[tuple(edge)] = False
        edge[axis] = slice(-r, None)
        out[tuple(edge)] = False
    return out


def _spread(values: np.ndarray, r: int, pick) -> np.ndarray:
    """Each pixel's highest (pick=np.maximum) or lowest (np.minimum) value within r pixels (a square, two passes)."""
    out = values.copy()
    for axis in (0, 1):
        src = out.copy()
        for d in range(1, r + 1):
            if axis == 0:
                out[d:] = pick(out[d:], src[:-d])
                out[:-d] = pick(out[:-d], src[d:])
            else:
                out[:, d:] = pick(out[:, d:], src[:, :-d])
                out[:, :-d] = pick(out[:, :-d], src[:, d:])
    return out


def grow(mask: np.ndarray, r: int) -> np.ndarray:
    """Where `mask` holds somewhere within r pixels (a square)."""
    return _spread(mask, r, np.maximum)


def top_lighter(shown: np.ndarray, tops: np.ndarray) -> np.ndarray:
    """The tones (as shown: 1 − density) with the faces looking up in the light TOP_LIGHTER less dense; tones from
    TOP_KEEPS up (and ベタ) stay."""
    out = shown.copy()
    light = tops & (shown.min(axis=-1) > 1.0 - TOP_KEEPS)
    out[light] = np.minimum(1.0, shown[light] + TOP_LIGHTER)
    return out


def texture_reach(distance: np.ndarray, foreground: float) -> np.ndarray:
    """How much of a texture line is kept at each pixel's distance (m): all of it up to TEXTURE_REACH foregrounds
    off, none a little farther (the lines end there; they are never drawn paler)."""
    reach = TEXTURE_REACH * foreground
    return np.clip((reach * (1.0 + TEXTURE_END) - distance) / (reach * TEXTURE_END), 0.0, 1.0).astype(np.float32)


#: A ベタ narrower than this many reaches (a dark fascia, a strip of dark glass) keeps its lines black: white lines
#: on it would be specks.
BETA_WIDE = 3


def white_on_beta(lines: np.ndarray, tone: np.ndarray, reach: int = 0) -> np.ndarray:
    """The lines with those over ベタ (a solid black) turned white, as a manga draws them; within `reach` pixels of
    the ベタ's edge they stay black (its outline against what is round it), and on a narrow ベタ all stay black."""
    beta = (tone[..., 3] > 0.5) & (tone[..., :3].max(axis=-1) < BETA_SHOWN)
    if reach:
        drawn = lines[..., 3] > 0.05
        solid = beta | drawn
        wide = grow(erode(solid, BETA_WIDE * reach), BETA_WIDE * reach)
        beta = erode(solid, reach) & beta & wide
    out = lines.copy()
    out[beta, :3] = 1.0 - out[beta, :3]
    return out


def _blocked(scene, depsgraph, start: Vector, ray: Vector) -> bool:
    """Whether something between `start` and the light (along `ray`) casts a shadow there; a room's walls do not."""
    for _ in range(8):
        hit, location, _, _, obj, _ = scene.ray_cast(depsgraph, start, ray, distance=1e5)
        if not hit:
            return False
        if not obj.get("nb_noshadow"):
            return True
        start = location + ray * 1e-3
    return True


def _part_name(name: str) -> str:
    """A part's name as the 素材 has it (without the .001 Blender adds when the same name is appended twice)."""
    head, dot, tail = name.rpartition(".")
    return head if dot and tail.isdigit() else name


def _skipped(why: str) -> dict:
    return {"name": "影の向き", "pass": True, "skipped": True, "tested": 0, "note": f"照合せず（{why}）"}


def _edge(mask: np.ndarray, x: int, y: int, r: int) -> bool:
    """Whether a shadow's edge is within r pixels of (x, y)."""
    h, w = mask.shape
    patch = mask[max(0, y - r) : min(h, y + r + 1), max(0, x - r) : min(w, x + r + 1)]
    return bool(patch.any()) and not bool(patch.all())


def _around(toward: Vector, angle_deg: float) -> list[Vector]:
    """The direction toward the light and four at the edges of its disc (a wide light casts soft shadows)."""
    half = math.radians(max(angle_deg, 0.0)) / 2
    if half < 1e-4:
        return [toward]
    side = toward.cross(Vector((0, 0, 1)))
    if side.length < 1e-6:
        side = Vector((1, 0, 0))
    side.normalize()
    up = side.cross(toward).normalized()
    t = math.tan(half)
    return [toward] + [(toward + d * t).normalized() for d in (side, -side, up, -up)]


def shadow_check(plan: dict, built: dict, shadow: np.ndarray, lit: np.ndarray, sun) -> dict:
    """Shadows fall where the geometry says: away from the light on the ground beside each thing, and over the
    whole picture on the faces turned away from it or hidden from it."""
    if sun is None:
        return _skipped("日差しも明かりもない")
    from bpy_extras.object_utils import world_to_camera_view

    scene = bpy.context.scene
    cam = scene.camera
    h, w = shadow.shape
    light = plan["develop"]["lighting"]["sun"]
    toward = Vector(light["direction"]).normalized()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = cam.matrix_world.translation
    grounds = (PREFIX + "light_ground", PREFIX + "ground")
    edge = max(2, round(min(w, h) / 200))
    results = {"shadow": [0, 0], "sunny": [0, 0]}

    # 1. The ground beside each thing on it (not when the light is nearly overhead: the shadow is at its foot, and a
    # soft light blurs that much); each point only where the light is wholly hidden from it or wholly not.
    rays = _around(toward, light.get("angleDeg", 0.0))
    level = Vector((toward.x, toward.y, 0.0))
    elevation = math.asin(max(-1.0, min(1.0, toward.z)))
    if level.length > 1e-6 and math.degrees(elevation) <= OVERHEAD_DEG:
        level.normalize()
        things = [o["placed"] for o in plan["objects"]] + [f["placed"] for f in plan["figures"]]
        for p in things:
            if p["centreM"][2] > 0.01:
                continue
            size = p["sizeM"]
            height = size[2]
            reach = min(height / max(math.tan(elevation), 1e-3), 4 * height)
            half = 0.5 * math.hypot(size[0], size[1])
            base = Vector((p["centreM"][0], p["centreM"][1], 0.0))
            for kind, sign, share in (("shadow", -1.0, 0.35), ("shadow", -1.0, 0.7), ("sunny", 1.0, 0.35), ("sunny", 1.0, 0.7)):
                point = base + level * sign * (half + share * reach) + Vector((0, 0, 0.001))
                v = world_to_camera_view(scene, cam, point)
                if v.z <= 0 or not (0 <= v.x <= 1 and 0 <= v.y <= 1):
                    continue
                direction = point - origin
                hit, location, _, _, hit_obj, _ = scene.ray_cast(
                    depsgraph, origin, direction.normalized(), distance=direction.length + 0.01
                )
                if not hit or hit_obj.name not in grounds or (location - point).length > 0.05 * direction.length + 0.05:
                    continue
                start = location + Vector((0, 0, 1e-3 + 1e-4 * direction.length))
                hidden = [_blocked(scene, depsgraph, start, ray) for ray in rays]
                if (kind == "shadow" and not all(hidden)) or (kind == "sunny" and any(hidden)):
                    continue  # in a soft shadow's half-light, or lit or shaded by something else
                x, y = int(v.x * (w - 1)), int((1 - v.y) * (h - 1))
                results[kind][1] += 1
                if bool(shadow[y, x]) == (kind == "shadow"):
                    results[kind][0] += 1

    # 2. A grid over the picture: what the camera sees there, turned to the light or not, hidden from it or not.
    faces = {"shadow": [0, 0], "sunny": [0, 0]}
    tr, br, bl, tl = (cam.matrix_world @ v for v in cam.data.view_frame(scene=scene))
    nx, ny = GRID
    for j in range(ny):
        for i in range(nx):
            u, t = (i + 0.5) / nx, (j + 0.5) / ny
            target = tl.lerp(tr, u).lerp(bl.lerp(br, u), t)
            direction = (target - origin).normalized()
            hit, location, normal, _, hit_obj, _ = scene.ray_cast(depsgraph, origin, direction, distance=1e5)
            if not hit:
                continue
            if normal.dot(direction) > 0:
                normal = -normal
            v = world_to_camera_view(scene, cam, location)
            x, y = int(v.x * (w - 1)), int((1 - v.y) * (h - 1))
            if not (0 <= x < w and 0 <= y < h) or _edge(shadow, x, y, edge):
                continue
            facing = normal.dot(toward)
            start = location + normal * (1e-3 + 1e-4 * (location - origin).length)
            hidden = [_blocked(scene, depsgraph, start, ray) for ray in rays]
            if facing < FACE_AWAY or all(hidden):
                kind = "shadow"
            elif facing > FACE_LIT and not any(hidden):
                kind = "sunny"
            else:
                continue  # grazing, or in a soft shadow's half-light
            faces[kind][1] += 1
            if bool(shadow[y, x]) == (kind == "shadow"):
                faces[kind][0] += 1

    tested = sum(n for _, n in results.values()) + sum(n for _, n in faces.values())
    if not tested:
        return _skipped("コマの中に試せる点がない")
    ok = all(n == 0 or good / n >= GROUND_SHARE for good, n in results.values()) and all(
        n == 0 or good / n >= FACE_SHARE for good, n in faces.values()
    )
    words = []
    if results["shadow"][1] or results["sunny"][1]:
        words.append(f"地面 影の側 {results['shadow'][0]}/{results['shadow'][1]}・日なたの側 {results['sunny'][0]}/{results['sunny'][1]}")
    words.append(f"面 影 {faces['shadow'][0]}/{faces['shadow'][1]}・日なた {faces['sunny'][0]}/{faces['sunny'][1]}")
    return {
        "name": "影の向き",
        "pass": ok,
        "tested": tested,
        "shadowSide": results["shadow"],
        "sunnySide": results["sunny"],
        "faces": {"shadow": faces["shadow"], "sunny": faces["sunny"]},
        "note": "・".join(words),
    }
