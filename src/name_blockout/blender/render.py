# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw a built scene out as a manga background's rough (runs inside Blender).

Cycles on the CPU (headless anywhere; the surfaces only emit, so a few
samples give clean flat greys), with Freestyle for the lines:

- 線画: black lines on transparent (the surfaces held out);
- トーン: the greys by which way faces look, on transparent;
- 完成: both on white;
- 遠景: the far band alone (far things and the far layers, their lines and
  greys), on the 360° panorama when there is one, else on transparent.

Lines get thinner with distance: one line set per distance band (far.py).
"""

from __future__ import annotations

from pathlib import Path

import bpy

from ..far import BANDS, LINE_SCALE
from .scene import PREFIX, holdout_material

LINE_PX_AT_150DPI = 1.6


def _freestyle(scene, thickness: float):
    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = "ABSOLUTE"
    layer = bpy.context.view_layer
    layer.use_freestyle = True
    fs = layer.freestyle_settings
    fs.crease_angle = 2.3  # ~132°: box edges, not a curved body's facets
    for ls in list(fs.linesets):
        fs.linesets.remove(ls)
    for group in (*BANDS, "ground"):
        coll = bpy.data.collections.get(PREFIX + ("ground" if group == "ground" else "band_" + group))
        if coll is None or not coll.all_objects:
            continue
        ls = fs.linesets.new(f"NB_lines_{group}")
        ls.select_by_visibility = True
        ls.visibility = "VISIBLE"
        ls.select_by_collection = True
        ls.collection = coll
        ls.select_by_edge_types = True
        ls.select_silhouette = True
        ls.select_border = False
        ls.select_crease = True
        ls.select_edge_mark = True
        ls.select_external_contour = True
        style = bpy.data.linestyles.new(f"NB_style_{group}")
        ls.linestyle = style
        style.color = (0, 0, 0)
        style.thickness = max(0.75, thickness * LINE_SCALE[group])
        style.thickness_position = "CENTER"


def _show_only_far(only_far: bool) -> None:
    for coll in bpy.data.collections:
        if coll.name.startswith(PREFIX) and coll.name not in (PREFIX + "band_far", PREFIX + "camera"):
            coll.hide_render = only_far
    for ls in bpy.context.view_layer.freestyle_settings.linesets:
        ls.show_render = not only_far or ls.name == "NB_lines_far"


def render_passes(plan: dict, out_dir: Path, passes=("完成", "線画", "トーン"), samples: int = 6) -> dict:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.max_bounces = 0
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    w, h = plan["render"]["sizePx"]
    scene.render.resolution_x, scene.render.resolution_y = w, h
    dpi = plan["render"]["dpi"]
    _freestyle(scene, max(1.0, LINE_PX_AT_150DPI * dpi / 150))
    layer = bpy.context.view_layer
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    white = bpy.data.worlds.get(PREFIX + "world")
    panorama = bpy.data.worlds.get(PREFIX + "panorama")
    settings = {
        "線画": dict(transparent=True, lines=True, holdout=True),
        "トーン": dict(transparent=True, lines=False, holdout=False),
        "完成": dict(transparent=False, lines=True, holdout=False),
        "遠景": dict(transparent=panorama is None, lines=True, holdout=False, far=True),
    }
    for name in passes:
        cfg = settings.get(name)
        if cfg is None:
            continue
        far = cfg.get("far", False)
        _show_only_far(far)
        scene.world = panorama if (far and panorama) else white
        scene.render.film_transparent = cfg["transparent"]
        scene.render.use_freestyle = cfg["lines"]
        layer.material_override = holdout_material() if cfg["holdout"] else None
        path = out_dir / f"{name}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        files[name] = path
    _show_only_far(False)
    scene.world = white
    layer.material_override = None
    return files
