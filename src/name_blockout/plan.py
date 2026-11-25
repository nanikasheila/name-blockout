# SPDX-License-Identifier: GPL-3.0-or-later
"""The Blockout of a shot, as data: the camera, the ground, the place, boxes
for things and figures, and what the picture must show (the targets the
check compares against). Blender builds exactly this (blender/scene.py), so
the same instruction gives the same scene; nothing here needs Blender.
"""

from __future__ import annotations

import math
from pathlib import Path

from .assets import Asset, object_asset, read_assets
from .camera import AXES, DEFAULT_HEIGHT_M, Camera, CameraError, fit_camera
from .instruction import Frame, frame_of
from .scope import hashes, object_hashes
from .sizes import usual_size
from .solve import DEFAULT_FIGURE_M, fit_box, fit_figure

PREVIEW_DPI = 150
PLAN_FORMAT = "name-blockout/plan"


def instruction_dir(instruction_path: str | Path | None) -> Path:
    return Path(instruction_path).resolve().parent if instruction_path else Path.cwd()


def folder_of(data: dict, key: str, base: Path) -> Path | None:
    value = (data.get("folders") or {}).get(key)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else (base / path)


def vanishing_axes(camera: Camera, vanishing_px: list) -> list[str | None]:
    """For each vanishing point, the world axis whose far end the camera draws there."""
    out = []
    for i, v in enumerate(vanishing_px):
        candidates = dict(AXES)
        if i == 2:
            candidates = {"+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0)}
        best, best_d = None, float("inf")
        for name, d in candidates.items():
            p = camera.project(d, direction=True)
            if p is None:
                continue
            dist = math.dist(p, v)
            if dist < best_d:
                best, best_d = name, dist
        out.append(best)
    return out


def targets(shot: dict, frame: Frame) -> dict:
    """What the picture must show, in the instruction's pixels."""
    out: dict = {"sizePx": [frame.width, frame.height]}
    ruler = shot.get("ruler")
    if ruler and ruler.get("horizonMm"):
        a, b = (frame.px(p) for p in ruler["horizonMm"])
        dx = b[0] - a[0]
        slope = (b[1] - a[1]) / dx if abs(dx) > 1e-9 else 0.0
        out["horizonPx"] = [a[1] + (0 - a[0]) * slope, a[1] + (frame.width - a[0]) * slope]
        points = int(ruler.get("points", 0))
        out["vanishingPx"] = [list(frame.px(p)) for p in (ruler.get("vanishingMm") or [])[: points or 0]]
    out["objectsPx"] = {o["id"]: list(frame.px_box(o["shapeMm"])) for o in shot.get("objects") or []}
    out["figuresPx"] = {f["id"]: list(frame.px_box(f["shapeMm"])) for f in shot.get("figures") or []}
    return out


def build_plan(data: dict, shot: dict, instruction_path: str | Path | None = None, preview_dpi: float | None = None) -> dict:
    """The Blockout plan for one shot of an instruction (raises CameraError when the ruler gives no camera)."""
    base = instruction_dir(instruction_path)
    frame = frame_of(shot["frame"])
    dpi = preview_dpi or (shot.get("render") or {}).get("previewDpi") or PREVIEW_DPI
    render_frame = frame.at_dpi(min(dpi, frame.dpi))
    assumptions = list((shot.get("requirement") or {}).get("assumptions") or [])
    notes: list[str] = []

    camera = fit_camera(shot, frame)
    if camera is None:
        camera = _camera_from_words(shot, frame)
        assumptions.append(
            {
                "path": "ruler",
                "value": (shot.get("intent") or {}).get("camera", "eye"),
                "by": "tool",
                "note": "定規がないので、カメラの言葉（なければ目の高さ）から仮のカメラ",
            }
        )
    cam_cfg = shot.get("camera") or {}
    if "heightM" not in cam_cfg and "positionM" not in cam_cfg:
        assumptions.append(
            {"path": "camera.heightM", "value": DEFAULT_HEIGHT_M, "by": "tool", "note": "カメラの高さが決まっていないので仮"}
        )

    assets_dir = folder_of(data, "assets", base)
    assets: list[Asset] = read_assets(assets_dir)[0] if assets_dir else []
    place = shot.get("place") or {}
    place_asset = next((a for a in assets if a.kind == "place" and a.name == place.get("asset")), None) if place.get("asset") else None
    use_place = bool(place_asset and cam_cfg.get("positionM"))
    if place_asset and not use_place:
        notes.append(f"場所「{place_asset.name}」の中のカメラの位置（camera.positionM）が決まっていないので、場所は読み込まず箱だけで組む")

    t = targets(shot, frame)
    vp_axes = vanishing_axes(camera, t.get("vanishingPx", []))

    objects = []
    for obj in shot.get("objects") or []:
        target = t["objectsPx"][obj["id"]]
        # The box's first side runs to the object's vanishing point (VP1 by default).
        index = 1 if obj.get("axis") == 2 else 0
        axis = vp_axes[index] if index < len(vp_axes) and vp_axes[index] else ("+Y" if index else "+X")
        along = axis[1]
        asset = object_asset(obj, assets)
        size = obj.get("sizeM")
        placed = fit_box(
            camera, target, size=size, along=along, on_ground=obj.get("onGround", True), prior=None if size else usual_size(obj["label"])
        )
        entry = {"id": obj["id"], "label": obj["label"], "placed": placed.as_dict(), "fixedSize": bool(size)}
        if asset:
            entry["asset"] = _asset_entry(asset, assets_dir)
        objects.append(entry)

    figures = []
    for fig in shot.get("figures") or []:
        target = t["figuresPx"][fig["id"]]
        height = float(fig.get("heightM") or DEFAULT_FIGURE_M)
        if not fig.get("heightM"):
            assumptions.append(
                {
                    "path": f"figures/{fig['id']}/heightM",
                    "value": DEFAULT_FIGURE_M,
                    "by": "tool",
                    "note": "人物の身長が決まっていないので仮",
                }
            )
        placed = fit_figure(camera, target, height)
        figures.append({"id": fig["id"], "name": fig.get("name", ""), "placed": placed.as_dict()})

    plan = {
        "format": PLAN_FORMAT,
        "formatVersion": 1,
        "shot": shot["id"],
        "label": shot.get("label", shot["id"]),
        "frame": {"boxMm": list(frame.box), "dpi": frame.dpi, "sizePx": [frame.width, frame.height]},
        "render": {"dpi": render_frame.dpi, "sizePx": [render_frame.width, render_frame.height], "passes": ["完成", "線画", "トーン"]},
        "camera": {
            **camera.summary(),
            "sensorMm": 36.0,
            "matrixWorld": camera.blender_matrix(),
            "vanishingAxes": vp_axes,
        },
        "ground": None if use_place else _ground(camera, render_frame.dpi / frame.dpi, objects + figures),
        "place": _asset_entry(place_asset, assets_dir) if use_place else None,
        "references": _references(camera) if (camera.points >= 3 and not objects and not use_place) else [],
        "objects": objects,
        "figures": figures,
        "targets": t,
        "hashes": {**hashes(shot), "objects": object_hashes(shot)},
        "assumptions": assumptions,
        "notes": notes + camera.notes,
    }
    return plan


def _asset_entry(asset: Asset, folder: Path | None) -> dict:
    path = (folder / asset.file) if folder else Path(asset.file)
    return {"name": asset.name, "kind": asset.kind, "file": str(path), "collection": asset.collection or asset.name}


def _camera_from_words(shot: dict, frame: Frame) -> Camera:
    """A camera for a shot without a ruler: eye level (horizon at the middle), looking up (low) or down (high)."""
    word = (shot.get("intent") or {}).get("camera", "eye")
    w, h = frame.width, frame.height
    if word == "low":
        ruler = {"points": 0, "horizonMm": [frame.mm((0, h * 0.85)), frame.mm((w, h * 0.85))]}
    elif word == "high":
        ruler = {"points": 0, "horizonMm": [frame.mm((0, -h * 0.4)), frame.mm((w, -h * 0.4))]}
    else:
        ruler = {"points": 0, "horizonMm": [frame.mm((0, h * 0.5)), frame.mm((w, h * 0.5))]}
    height = {"low": 0.5, "high": 6.0}.get(word, DEFAULT_HEIGHT_M)
    camera_cfg = {"heightM": height, **(shot.get("camera") or {})}
    camera = fit_camera({**shot, "ruler": ruler, "camera": camera_cfg}, frame)
    if camera is None:
        raise CameraError("カメラを作れません")
    return camera


def _grid_spacing(camera: Camera) -> float:
    h = abs(camera.position[2]) or 1.5
    for spacing in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0):
        if spacing >= h / 2:
            return spacing
    return 100.0


def _ground(camera: Camera, render_scale: float, placed: list[dict]) -> dict:
    """The ground: grids in rings, each coarser than the one inside it (×4), so its lines stay a few pixels apart in
    the picture all the way to what stands farthest (a dense grid near the horizon would draw a black band; beyond
    the last ring the white of the sky stands for the ground: a large plane there makes Freestyle very slow)."""
    spacing = _grid_spacing(camera)
    h = abs(camera.position[2]) or 1.5
    focal = camera.focal_px * render_scale
    reach = 0.0
    for item in placed:
        c, size = item["placed"]["centreM"], item["placed"]["sizeM"]
        reach = max(reach, max(abs(c[0] - camera.position[0]), abs(c[1] - camera.position[1])) + max(size[0], size[1]) / 2)
    rings = []
    inner = 0.0
    while True:
        # Lines `spacing` apart at distance D are about focal·h·spacing/D² rows apart: end the ring where that is 5 px.
        extent = max(8 * spacing, math.sqrt(focal * h * spacing / 5.0))
        extent = min(2000.0, math.ceil(extent / spacing) * spacing)
        if extent <= inner:
            extent = inner + 4 * spacing
        rings.append({"spacingM": spacing, "extentM": extent})
        inner = extent
        if extent >= min(2000.0, reach + spacing) or len(rings) >= 4:
            break
        spacing *= 4
    unit = rings[-1]["spacingM"]
    cx, cy = round(camera.position[0] / unit) * unit, round(camera.position[1] / unit) * unit
    return {"z": 0.0, "centreM": [cx, cy], "rings": rings}


def _references(camera: Camera) -> list[dict]:
    """For 3点 with nothing else in the picture: posts standing ahead, so the uprights' vanishing shows."""
    _, _, forward = camera.camera_axes_world()
    level = (forward[0], forward[1])
    n = math.hypot(*level) or 1.0
    level = (level[0] / n, level[1] / n)
    side = (-level[1], level[0])
    h = abs(camera.position[2]) or 1.5
    out = []
    for k, (ahead, across) in enumerate(((6, -3), (6, 3), (12, -6), (12, 6))):
        d = ahead * max(1.0, h / 1.5)
        x = camera.position[0] + level[0] * d + side[0] * across * max(1.0, h / 1.5)
        y = camera.position[1] + level[1] * d + side[1] * across * max(1.0, h / 1.5)
        out.append({"id": f"post{k + 1}", "centreM": [x, y, 0.0], "sizeM": [0.6, 0.6, max(12.0, h * 4)]})
    return out
