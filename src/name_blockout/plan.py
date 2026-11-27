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
from .far import BAND_LABELS, FAR_M, NEAR_M, band_of, far_layers, level_distance, panorama_width_needed, parallax_free_m
from .far import KIND_LABELS as FAR_LABELS
from .imagesize import image_size
from .instruction import Frame, frame_of
from .look import DEFAULT_NORTH, aimed, lighting, setting_of
from .materials import assign
from .parts import assembly, floating_words
from .room import WALL_LABELS, build_room, room_of, room_words, window_heading
from .scope import hashes, object_hashes
from .shapes import KIND_LABELS as SHAPE_LABELS
from .shapes import kind_of, shape_of
from .sizes import usual_size
from .solve import DEFAULT_FIGURE_M, fit_box, fit_figure, place_box

PREVIEW_DPI = 150
#: A thing placed on the top view that fills less than this of its range on the panel is noted (IoU).
PLACED_OVERLAP = 0.6
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
    used: list[Asset] = [place_asset] if use_place else []

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
        footless = bool(placed.note)
        if footless:
            notes.append(f"物「{obj['label']}」: {placed.note}")
        if obj.get("positionM"):
            # Placed on the top view: it stands where the author (or a correction) put it, at the size given or the
            # size that filled the panel's range; how well it then fills that range is told, not forced.
            placed = place_box(camera, target, obj["positionM"], placed.size, along)
        entry = {"id": obj["id"], "label": obj["label"], "placed": placed.as_dict(), "fixedSize": bool(size)}
        if footless and not obj.get("positionM"):
            entry["footless"] = True
        if obj.get("positionM"):
            entry["fixedPlace"] = True
            if placed.iou < PLACED_OVERLAP:
                notes.append(
                    f"物「{obj['label']}」: 俯瞰図の位置に置くと、ネームの範囲との重なりは {placed.iou * 100:.0f}%（位置か大きさ、どちらかがネームと違う）"
                )
        entry.update(_band(camera, obj, placed.centre, notes, obj["label"]))
        if entry["distanceM"] > parallax_free_m(camera, camera.focal_px * render_frame.dpi / frame.dpi) and not obj.get("band"):
            notes.append(
                f"物「{obj['label']}」は {entry['distanceM']:.0f}m 先: カメラの高さを 1m 変えても下見で 1px も動かないので、遠景の層"
                "（街並み・山並み・全天球の画像）でも足ります"
            )
        if asset:
            entry["asset"] = _asset_entry(asset, assets_dir)
            used.append(asset)
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
        figures.append(
            {"id": fig["id"], "name": fig.get("name", ""), "placed": placed.as_dict(), **_band(camera, {}, placed.centre, notes, "")}
        )

    panoramas = {a.name: a for a in assets if a.kind == "panorama"}
    far, far_notes = far_layers(camera, shot.get("far") or [], {n: _asset_entry(a, assets_dir) for n, a in panoramas.items()})
    notes += far_notes
    for layer in far:
        if layer["kind"] != "panorama":
            continue
        used.append(panoramas[layer["name"]])
        size = image_size(layer["file"])
        if size:
            for dpi_name, dpi_value in (("下見", render_frame.dpi), ("本番", frame.dpi)):
                need = panorama_width_needed(camera.focal_px * dpi_value / frame.dpi)
                if size[0] < need:
                    notes.append(
                        f"全天球の画像「{layer['name']}」は幅 {size[0]}px: {dpi_name}（{dpi_value:g}dpi）には {need}px 要るので粗く見えます"
                    )
                    break
    room = None
    spec = None if use_place else room_of(shot)
    if spec is not None:
        room, room_notes = build_room(spec, camera, objects + figures)
        notes += [room_words(room), *room_notes]
        if spec["autoWindows"] and room["windows"]:
            walls = [w["wall"] for w in room["windows"]]
            label = "・".join(WALL_LABELS[w] for w in walls)
            assumptions.append(
                {
                    "path": "room.windows",
                    "value": [{"wall": w} for w in walls],
                    "by": "tool",
                    "note": f"光は窓からなので、画面の左に見える壁（{label}）に窓",
                }
            )
    passes = ["完成", "線画", "トーン"] + (["遠景"] if far or any(o["band"] == "far" for o in objects) else [])
    passes = list((shot.get("render") or {}).get("passes") or passes)

    plan = {
        "format": PLAN_FORMAT,
        "formatVersion": 1,
        "shot": shot["id"],
        "label": shot.get("label", shot["id"]),
        "frame": {"boxMm": list(frame.box), "dpi": frame.dpi, "sizePx": [frame.width, frame.height]},
        "render": {
            "dpi": render_frame.dpi,
            "sizePx": [render_frame.width, render_frame.height],
            "passes": [p for p in passes if p != "影"],
        },
        "camera": {
            **camera.summary(),
            "sensorMm": 36.0,
            "matrixWorld": camera.blender_matrix(),
            "vanishingAxes": vp_axes,
        },
        "ground": None if use_place else (_floor(room) if room else _ground(camera, render_frame.dpi / frame.dpi, objects + figures)),
        "place": _place_entry(place_asset, assets_dir, place) if use_place else None,
        "room": room,
        "references": _references(camera) if (camera.points >= 3 and not objects and not use_place and not room) else [],
        "objects": objects,
        "figures": figures,
        "far": far,
        "credits": _credits(used),
        "targets": t,
        "hashes": {**hashes(shot), "objects": object_hashes(shot)},
        "assumptions": assumptions,
        "notes": notes + camera.notes,
    }
    return plan


def _asset_entry(asset: Asset, folder: Path | None) -> dict:
    path = (folder / asset.file) if folder else Path(asset.file)
    return {"name": asset.name, "kind": asset.kind, "file": str(path), "collection": asset.collection or asset.name}


def _band(camera: Camera, item: dict, centre, notes: list[str], label: str) -> dict:
    """The distance band of a thing as placed (or as the instruction says; a far cry from where it stands is noted)."""
    distance = level_distance(camera, centre)
    measured = band_of(distance)
    band = item.get("band") or measured
    if (
        label
        and item.get("band")
        and ((band == "near" and distance > FAR_M) or (band == "far" and distance < NEAR_M) or (band == "middle" and distance < NEAR_M / 3))
    ):
        notes.append(f"物「{label}」は{BAND_LABELS[band]}と指示されていますが、組むと {distance:.0f}m 先（{BAND_LABELS[measured]}）です")
    return {"band": band, "distanceM": round(distance, 2)}


def _credits(used: list[Asset]) -> list[dict]:
    """The 素材 a take is made with, once each: their licenses, and the line to credit them with where one is asked."""
    out, seen = [], set()
    for asset in used:
        if asset is None or asset.name in seen:
            continue
        seen.add(asset.name)
        out.append(
            {
                "name": asset.name,
                "license": asset.license or "own",
                **({"source": asset.source} if asset.source else {}),
                **({"author": asset.author} if asset.author else {}),
                "needsCredit": asset.needs_credit,
                **({"credit": asset.credit()} if asset.needs_credit else {}),
            }
        )
    return out


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
        # A whole number of the next ring's cells, so its cells meet this ring's edge (no faces overlap).
        step = 4 * spacing
        extent = min(2000.0, math.ceil(extent / step) * step)
        if extent <= inner:
            extent = inner + step
        rings.append({"spacingM": spacing, "extentM": extent})
        inner = extent
        if extent >= min(2000.0, reach + spacing) or len(rings) >= 4:
            break
        spacing *= 4
    unit = rings[-1]["spacingM"]
    cx, cy = round(camera.position[0] / unit) * unit, round(camera.position[1] / unit) * unit
    return {"z": 0.0, "centreM": [cx, cy], "rings": rings}


#: A floor's grid indoors: half a ken (a tatami's width), so its lines run to the vanishing points as boards would.
FLOOR_SPACING_M = 0.91


def _floor(room: dict) -> dict:
    """The room's floor as the ground: a grid inside its walls."""
    return {"z": 0.0, "rectM": list(room["rectM"]), "spacingM": FLOOR_SPACING_M}


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


DEVELOP_DPI = 300


#: Kinds that make a street of a place (a skyline behind); otherwise trees and mountains.
TOWN_KINDS = {"house", "building", "shed", "van", "car", "truck", "bus", "pole", "fence", "wall"}


def _place_entry(asset, assets_dir, place: dict) -> dict:
    """The place's file, with what the author moves or hides in it (by the objects' names in the .blend)."""
    entry = _asset_entry(asset, assets_dir)
    for key in ("moves", "hide"):
        if place.get(key):
            entry[key] = place[key]
    return entry


def horizon_in_frame(plan: dict) -> bool:
    """Whether the eye level crosses the picture (then what lies beyond the place shows)."""
    t = plan.get("targets") or {}
    rows, (_, height) = t.get("horizonPx"), t.get("sizePx") or (0, 0)
    return bool(rows) and any(0 <= y <= height for y in rows)


def default_far(shot: dict) -> list[dict]:
    """Far layers for a place outdoors whose author named none: a town's skyline where houses, buildings or cars
    stand, else trees with mountains behind (seeded by the shot, so the same each time)."""
    seed = sum(ord(ch) for ch in str(shot.get("id") or "shot"))
    kinds = {kind_of(o) for o in shot.get("objects") or []}
    # Low hills between the near trees and the far mountains, so the distance steps back in layers.
    hills = {"kind": "mountains", "seed": seed + 2, "distanceM": 1800.0, "heightM": [30.0, 140.0]}
    if kinds & TOWN_KINDS:
        return [{"kind": "skyline", "seed": seed}, hills, {"kind": "mountains", "seed": seed + 1}]
    return [{"kind": "trees", "seed": seed}, hills, {"kind": "mountains", "seed": seed + 1}]


def build_develop_plan(data: dict, shot: dict, instruction_path: str | Path | None = None, dpi: float | None = None) -> dict:
    """The development plan: the same camera and layout as the Blockout (the design does not move), with the light
    (look.py) and each thing's material (materials.py) in numbers, drawn at `dpi` (default 300, at most the frame's)."""
    frame = frame_of(shot["frame"])
    setting, setting_assumed = setting_of(shot)
    # Outdoors the finished picture has a distance: far layers the author did not ask for are made (and noted).
    # A place (a .blend) ends somewhere: past it, when the eye level shows, the far layers too.
    dpi = min(dpi or DEVELOP_DPI, frame.dpi)
    far_assumed = default_far(shot) if setting == "outdoor" and not shot.get("far") else []
    if far_assumed and shot.get("place") and not horizon_in_frame(build_plan(data, shot, instruction_path, dpi)):
        far_assumed = []
    built_from = {**shot, "far": far_assumed} if far_assumed else shot
    plan = build_plan(data, built_from, instruction_path, dpi)
    plan["hashes"] = {**hashes(shot), "objects": object_hashes(shot)}
    camera = plan["camera"]
    light, light_assumed = lighting(shot.get("look"), camera["headingDeg"], setting)
    materials, material_assumed = assign(shot, setting, room=bool(plan.get("room")))
    # Light through a window comes from the window the room has (not only "from the left").
    toward = window_heading(plan.get("room"), plan["objects"] + plan["figures"]) if light["key"] == "window" else None
    if toward and light.get("sun"):
        light["sun"] = aimed(light["sun"], toward[0], (shot.get("look") or {}).get("north") or DEFAULT_NORTH)
        plan["notes"].append(f"窓の光は{WALL_LABELS[toward[1]]}の壁の窓から")
    plan["develop"] = {"lighting": light, "materials": materials}
    # The development draws each thing as its 素材 where it has one (the Blockout keeps the boxes).
    plan["detail"] = True
    swapped = [f"{o['label']}（{o['asset']['name']}）" for o in plan["objects"] if o.get("asset")]
    if swapped:
        plan["notes"].append("素材に差し替え: " + "・".join(swapped))
    # What has no 素材 gets a detailed shape the tool makes (or the author wrote), in its box.
    given = {o.get("id"): o for o in shot.get("objects") or []}
    made, plain = [], []
    for o in plan["objects"]:
        if o.get("asset") or o.get("band") == "far":
            continue
        parts, how = shape_of({**given.get(o["id"], {}), **o}, o["placed"]["sizeM"])
        if parts:
            o["parts"], o["shapeKind"] = parts, how
            made.append(f"{o['label']}（{'作者の形' if how == 'own' else SHAPE_LABELS[how]}・部品 {len(parts)}）")
        else:
            plain.append(o["label"])
    if made:
        plan["notes"].append("形を作った: " + "・".join(made))
    # A part that neither stands on the ground nor touches one that does is a mistake in the numbers: say so
    # before it is drawn floating.
    for o in plan["objects"]:
        if o.get("parts"):
            plan["notes"] += floating_words(o["label"], assembly(o["parts"]))
    if plain:
        plan["notes"].append(
            "形のひな形がない物: " + "・".join(plain) + "（箱のまま。objects[].shape に部品を書くか、素材を足してください）"
        )
    if far_assumed:
        kinds = "・".join(dict.fromkeys(FAR_LABELS[layer["kind"]] for layer in far_assumed))
        plan["notes"].append(f"遠景が決まっていないので {kinds} を置いた")
        plan["assumptions"].append({"path": "far", "value": far_assumed, "by": "tool", "note": f"遠景が決まっていないので{kinds}"})
    plan["assumptions"] += ([setting_assumed] if setting_assumed else []) + light_assumed + material_assumed
    passes = ["完成", "線画", "トーン", "影"] + (["遠景"] if "遠景" in plan["render"]["passes"] else [])
    plan["render"]["passes"] = passes
    return plan
