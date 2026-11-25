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

Then the check of the light: for each thing on the ground, a point of ground
where its shadow must fall (away from the sun) and one where it must not
(toward the sun), seen by the camera, are looked up in 光.
"""

from __future__ import annotations

import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

from .render import render_passes
from .scene import PREFIX, collection

#: Under this share of the light a white face gets facing the sun, a pixel is in shadow.
SHADOW_SHARE = 0.12
SHADOW_RGBA = (0.25, 0.25, 0.3, 0.55)
#: The mannequins: white in the light, a light tone in shadow (they stand for people drawn later).
FIGURE = {"tone": 0.0, "shadowTone": 0.25, "beta": False}
NO_SUN_ALL_SHADOW = ("dawn", "dusk", "night")
#: The sky's tone (density) when the sun is down.
SKY_TONES = {"dawn": 0.2, "dusk": 0.35, "night": 0.8}


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


def add_light_ground(plan: dict):
    """A ground to catch shadows (as far as the ground grid goes, else 200 m round the camera)."""
    ground = plan.get("ground") or {}
    rings = ground.get("rings") or []
    extent = min(400.0, rings[-1]["extentM"]) if rings else 200.0
    cx, cy = ground.get("centreM") or plan["camera"].get("positionM", [0, 0])[:2]
    mesh = bpy.data.meshes.new(PREFIX + "light_ground")
    mesh.from_pydata(
        [
            (cx - extent, cy - extent, 0.0),
            (cx + extent, cy - extent, 0.0),
            (cx + extent, cy + extent, 0.0),
            (cx - extent, cy + extent, 0.0),
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


def _render(path: Path, samples: int, transparent: bool = True) -> np.ndarray:
    scene = bpy.context.scene
    scene.cycles.samples = samples
    scene.render.film_transparent = transparent
    scene.render.use_freestyle = False
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    w, h = image.size
    pixels = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels.reshape(h, w, 4)[::-1]  # rows from the top


def _save(path: Path, rgba: np.ndarray) -> Path:
    h, w = rgba.shape[:2]
    image = bpy.data.images.new(path.stem, w, h, alpha=True)
    image.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path


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

    def grey(m):
        # A tone's density is how dark it shows: 1 − density on the screen.
        return 0.0 if m["beta"] else _linear(1.0 - m[which])

    for ident, objs in list(built["objects"].items()) + [(f"figure:{k}", v) for k, v in built["figures"].items()]:
        m = materials.get(ident) or (FIGURE if ident.startswith("figure:") else None)
        if not m:
            continue
        mat = _emission(f"dev_{ident.replace(':', '_')}_{which}", grey(m))
        for obj in objs:
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
    ground = add_light_ground(plan)
    sun = add_sun(light)
    keep_world = scene.world

    # 線画 (and 遠景) as in the Blockout, without the light's ground.
    collection("light_ground").hide_render = True
    passes = [p for p in ("線画", "遠景") if p in plan["render"]["passes"]]
    files = render_passes(plan, out_dir, passes=passes)
    collection("light_ground").hide_render = False
    # The grid lies on the same plane as the light's ground: the two would shade each other black.
    grid = bpy.data.collections.get(PREFIX + "ground")
    if grid is not None:
        grid.hide_render = True
    scene.render.use_freestyle = False
    for ls in layer.freestyle_settings.linesets:
        ls.show_render = True

    # 1. 光: white and matte, the sun alone (the sky black), as strong as π so a face square to it is exactly 1.
    if sun is not None:
        sun.data.energy = math.pi
    dark = bpy.data.worlds.new(PREFIX + "dark")
    dark.use_nodes = True
    dark.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    scene.world = dark
    scene.cycles.max_bounces = 0
    layer.material_override = _white_matte()
    lit = _render(out_dir / "光.png", samples)
    layer.material_override = None
    alpha = lit[..., 3]
    word = light.get("timeOfDay")
    if sun is not None:
        # The picture is stored for the screen (sRGB): compare with the share as stored.
        shadow = (lit[..., 0] < _srgb(SHADOW_SHARE)) & (alpha > 0.5)
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

    # 3. Put together; at dawn, dusk and night the sky is toned too.
    tone = np.where(shadow[..., None], shadow_tones, lit_tones)
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
    files["完成"] = _save(out_dir / "完成.png", _over(lines, _over(tone, white)))
    check = shadow_check(plan, built, shadow, lit, sun)
    for name in ("_lit.png", "_shadow.png"):
        (out_dir / name).unlink(missing_ok=True)
    if grid is not None:
        grid.hide_render = False
    return files, check


def _load(path: Path) -> np.ndarray:
    image = bpy.data.images.load(str(path), check_existing=False)
    w, h = image.size
    pixels = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels.reshape(h, w, 4)[::-1]


def shadow_check(plan: dict, built: dict, shadow: np.ndarray, lit: np.ndarray, sun) -> dict:
    """Shadows fall away from the sun: per thing on the ground, a point of ground in its shadow and one on its sunny side."""
    if sun is None:
        return {"name": "影の向き", "pass": True, "note": "太陽が出ていない（影の向きは照合しない）", "tested": 0}
    from bpy_extras.object_utils import world_to_camera_view

    scene = bpy.context.scene
    cam = scene.camera
    h, w = shadow.shape
    toward = Vector(plan["develop"]["lighting"]["sun"]["direction"])
    level = Vector((toward.x, toward.y, 0.0))
    if level.length < 1e-6:
        return {"name": "影の向き", "pass": True, "note": "太陽が真上（影は足もと）", "tested": 0}
    level.normalize()
    elevation = math.asin(max(-1.0, min(1.0, toward.z)))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = cam.matrix_world.translation
    grounds = (PREFIX + "light_ground", PREFIX + "ground")
    results = {"shadow": [0, 0], "sunny": [0, 0]}
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
            hit, location, _, _, hit_obj, _ = scene.ray_cast(depsgraph, origin, direction.normalized(), distance=direction.length + 0.01)
            if not hit or hit_obj.name not in grounds or (location - point).length > 0.05 * direction.length + 0.05:
                continue
            x, y = int(v.x * (w - 1)), int((1 - v.y) * (h - 1))
            results[kind][1] += 1
            if bool(shadow[y, x]) == (kind == "shadow"):
                results[kind][0] += 1
    tested = results["shadow"][1] + results["sunny"][1]
    ok = all(n == 0 or good / n >= 0.75 for good, n in results.values())
    return {
        "name": "影の向き",
        "pass": ok,
        "tested": tested,
        "shadowSide": results["shadow"],
        "sunnySide": results["sunny"],
        "note": f"影の側 {results['shadow'][0]}/{results['shadow'][1]}・日なたの側 {results['sunny'][0]}/{results['sunny'][1]}",
    }
