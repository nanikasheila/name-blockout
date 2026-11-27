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
from ..lines import fold_mm
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


def _freestyle(scene, dpi: float, texture_from: float | None = None):
    """The line sets. For a Blockout: every thing's outline and edges, one pen pair per distance band. For a
    development (`texture_from`: its foreground's distance): only the folds and the texture lines (creases,
    marked edges, the ground's grid), black and as thin as a pen's finest (lines.py; develop.py ends them with
    distance); its boundaries are drawn from depth (lines.py), and far things get none."""
    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = "ABSOLUTE"
    layer = bpy.context.view_layer
    layer.use_freestyle = True
    fs = layer.freestyle_settings
    fs.crease_angle = 2.3  # ~132°: box edges, not a curved body's facets
    for ls in list(fs.linesets):
        fs.linesets.remove(ls)
    for style in [st for st in bpy.data.linestyles if st.name.startswith("NB_style_")]:
        bpy.data.linestyles.remove(style)
    outline, inner = line_px(dpi), inner_px(dpi)
    for group in (*BANDS, *GROUNDS):
        coll = bpy.data.collections.get(PREFIX + (group if group in GROUNDS else "band_" + group))
        if coll is None or not coll.all_objects:
            continue
        scale = LINE_SCALE[group]
        if group in GROUNDS:
            # The ground's grid: thin and grey in a Blockout (a construction grid); in a development a lot's
            # joints, black and as thin as the pen's finest.
            width = max(0.75, outline * scale)
            if texture_from:
                width = max(0.75, fold_mm() * dpi / 25.4)
            style = _style(f"NB_style_{group}", (0, 0, 0) if texture_from else GROUND_LINE, width, width * 3)
            ls = _lineset(fs, f"NB_lines_{group}", coll, style)
            ls.select_crease = True
            ls.select_edge_mark = True
            if texture_from:
                # A development's ground has no outline of its own: its far edge (the horizon) is told by the
                # backdrop's tones over the white ground.
                ls.select_silhouette = False
                ls.select_external_contour = False
            continue
        if texture_from:
            if group == "far":
                continue
            # A fold's width (the pen's finest, lines.py): the folds of small faces (a wall's boards) come out as
            # whole strokes here, where a picture's pixels would dot them.
            width = max(0.75, fold_mm() * dpi / 25.4)
            style = _style(f"NB_style_{group}_texture", (0, 0, 0), width, max(3.0, inner * MIN_STROKE_WIDTHS))
            marks = _lineset(fs, f"NB_lines_{group}_texture", coll, style)
            marks.select_silhouette = False
            marks.select_external_contour = False
            marks.select_crease = True
            marks.select_edge_mark = True
            if any(o.get("nb_foliage") for o in coll.all_objects):
                marks.select_by_face_marks = True
                marks.face_mark_negation = "EXCLUSIVE"
                marks.face_mark_condition = "ONE"
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


#: Which Cycles device draws: "auto" (a GPU when there is one and the picture is large, else the CPU), "cpu" or
#: "gpu" (NAME_BLOCKOUT_DEVICE).
DEVICE_ENV = "NAME_BLOCKOUT_DEVICE"
GPU_TYPES = ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI")
_chosen: str | None = None
#: Under this many pixels "auto" keeps the CPU: readying the GPU (2–3 s) costs more than it saves (a 150 dpi panel).
GPU_MIN_PIXELS = 4_000_000


def choose_device(pixels: int | None = None) -> str:
    """'GPU' with the first GPU backend that has a device (all its devices on), else 'CPU'; with "auto", a picture
    smaller than GPU_MIN_PIXELS on the CPU. The GPU looked for once a run."""
    import os

    if os.environ.get(DEVICE_ENV, "auto").lower() == "auto" and pixels is not None and pixels < GPU_MIN_PIXELS:
        return "CPU"
    return _find_gpu()


def _find_gpu() -> str:
    global _chosen
    if _chosen is not None:
        return _chosen
    import os

    want = os.environ.get(DEVICE_ENV, "auto").lower()
    _chosen = "CPU"
    if want == "cpu":
        return _chosen
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except (KeyError, AttributeError):
        return _chosen
    for kind in GPU_TYPES:
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue  # not built in this Blender
        prefs.get_devices()
        devices = [d for d in prefs.devices if d.type == kind]
        if devices:
            for d in prefs.devices:
                d.use = d.type == kind
            _chosen = "GPU"
            print(f"name-blockout: Cycles を GPU（{kind}: {', '.join(d.name for d in devices)}）で描きます")
            return _chosen
    try:
        prefs.compute_device_type = "NONE"
    except TypeError:
        pass
    if want == "gpu":
        print("name-blockout: GPU が見つからないので CPU で描きます")
    return _chosen


def setup(plan: dict, samples: int = 6):
    """The scene set for flat pictures of the plan's size (Cycles, a few samples, no bounces)."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    w, h = plan["render"]["sizePx"]
    scene.cycles.device = choose_device(w * h)
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.max_bounces = 0
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 100
    return scene


def render_passes(
    plan: dict,
    out_dir: Path,
    passes=("完成", "線画", "トーン"),
    samples: int = 6,
    texture_from: float | None = None,
) -> dict:
    """The passes as PNGs; `texture_from` (a development's foreground distance): the 線画 with the texture lines
    only (the development draws the boundaries itself, from depth)."""
    scene = setup(plan, samples)
    _freestyle(scene, plan["render"]["dpi"], texture_from)
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
