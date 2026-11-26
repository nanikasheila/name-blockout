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

#: A pen's widths, in mm on the page (a 0.2 mm outline, 0.13 mm inside it, as a background's fine liners), and
#: the thinnest drawn in pixels (a small picture would lose them).
OUTLINE_MM = 0.2
INNER_MM = 0.13
MIN_OUTLINE_PX = 1.4
MIN_INNER_PX = 0.9
#: The ground's grid: its lines thin and grey.
GROUNDS = ("ground",)
GROUND_LINE = (0.45, 0.45, 0.45)
#: A crown's inner strokes (one lump before another): only the long ones, in the shortest strokes of the rest.
FOLIAGE_MIN_STROKE = 6.0
#: The shortest stroke drawn, in line widths.
MIN_STROKE_WIDTHS = 3.0


def line_px(dpi: float) -> float:
    """An outline's width in pixels at `dpi`."""
    return max(MIN_OUTLINE_PX, OUTLINE_MM * dpi / 25.4)


def inner_px(dpi: float) -> float:
    """A crease's (an edge inside an outline) width in pixels at `dpi`."""
    return max(MIN_INNER_PX, INNER_MM * dpi / 25.4)


def _style(name: str, color, thickness: float, length_min: float):
    style = bpy.data.linestyles.new(name)
    style.color = color
    style.thickness = thickness
    style.thickness_position = "CENTER"
    # Strokes shorter than a few line widths are specks (a crease on a small facet), not lines a pen would draw.
    style.use_length_min = True
    style.length_min = length_min
    return style


def _freestyle(scene, dpi: float):
    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = "ABSOLUTE"
    layer = bpy.context.view_layer
    layer.use_freestyle = True
    fs = layer.freestyle_settings
    fs.crease_angle = 2.3  # ~132°: box edges, not a curved body's facets
    for ls in list(fs.linesets):
        fs.linesets.remove(ls)
    outline, inner = line_px(dpi), inner_px(dpi)
    for group in (*BANDS, *GROUNDS):
        coll = bpy.data.collections.get(PREFIX + (group if group in GROUNDS else "band_" + group))
        if coll is None or not coll.all_objects:
            continue
        scale = LINE_SCALE[group]
        if group in GROUNDS:
            # The ground's grid is thin and grey, as a background artist draws a lot's paving (a place's joints:
            # develop.py).
            width = max(0.75, outline * scale)
            ls = _lineset(fs, f"NB_lines_{group}", coll, _style(f"NB_style_{group}", GROUND_LINE, width, width * 3))
            ls.select_crease = True
            ls.select_edge_mark = True
            continue
        # Two pens, as an artist holds them: the outline (a thing against what is behind it) thicker, the edges
        # inside it (creases, marked edges) thinner.
        w_out, w_in = max(0.75, outline * scale), max(0.6, inner * scale)
        out_style = _style(f"NB_style_{group}", (0, 0, 0), w_out, max(3.0, w_out * MIN_STROKE_WIDTHS))
        in_style = _style(f"NB_style_{group}_inner", (0, 0, 0), w_in, max(3.0, w_out * MIN_STROKE_WIDTHS))
        foliage = any(o.get("nb_foliage") for o in coll.all_objects)
        edges = _lineset(fs, f"NB_lines_{group}", coll, out_style)
        creases = _lineset(fs, f"NB_lines_{group}_inner", coll, in_style)
        creases.select_silhouette = False
        creases.select_external_contour = False
        creases.select_crease = True
        creases.select_edge_mark = True
        if foliage:
            # Crowns and bushes (their faces marked) get neither set: their outline is drawn below.
            for ls in (edges, creases):
                ls.select_by_face_marks = True
                ls.face_mark_negation = "EXCLUSIVE"
                ls.face_mark_condition = "ONE"
            # A crown: its whole outline against what is behind it, unbroken (no length limit beyond the rest's)…
            rim = _lineset(fs, f"NB_lines_{group}_foliage", coll, out_style)
            rim.select_silhouette = False
            # …and inside it only the long strokes where one lump stands before another, thinner.
            lump = in_style.copy()
            lump.name = f"NB_style_{group}_foliage"
            lump.length_min = out_style.length_min * FOLIAGE_MIN_STROKE
            lumps = _lineset(fs, f"NB_lines_{group}_foliage_inner", coll, lump)
            lumps.select_external_contour = False
            for ls in (rim, lumps):
                ls.select_by_face_marks = True
                ls.face_mark_negation = "INCLUSIVE"
                ls.face_mark_condition = "ONE"


def _lineset(fs, name: str, coll, style):
    ls = fs.linesets.new(name)
    ls.select_by_visibility = True
    ls.visibility = "VISIBLE"
    ls.select_by_collection = True
    ls.collection = coll
    ls.select_by_edge_types = True
    ls.select_silhouette = True
    ls.select_border = False
    ls.select_external_contour = True
    ls.select_crease = False
    ls.select_edge_mark = False
    ls.linestyle = style
    return ls


def _show_only_far(only_far: bool) -> None:
    for coll in bpy.data.collections:
        if coll.name.startswith(PREFIX) and coll.name not in (PREFIX + "band_far", PREFIX + "camera"):
            coll.hide_render = only_far
    for ls in bpy.context.view_layer.freestyle_settings.linesets:
        ls.show_render = not only_far or ls.name.startswith("NB_lines_far")


def render_passes(plan: dict, out_dir: Path, passes=("完成", "線画", "トーン"), samples: int = 6, crowns: bool = True) -> dict:
    """The passes as PNGs; `crowns` False: the 線画 without the crowns' lines (the development draws them itself)."""
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
    _freestyle(scene, plan["render"]["dpi"])
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
        if not crowns and name == "線画":
            for ls in layer.freestyle_settings.linesets:
                if "_foliage" in ls.name:
                    ls.show_render = False
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
