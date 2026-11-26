# SPDX-License-Identifier: GPL-3.0-or-later
"""Distance bands and the far layers, as data (nothing here needs Blender).

Things fall in three bands by how far they stand from the camera:

- near (近景): up to NEAR_M; drawn with the full line and the darkest tones;
- middle (中景): up to FAR_M; thinner lines, lighter tones;
- far (遠景): beyond; thinnest lines, the lightest tones, and drawn again on
  their own in 遠景.png.

The far layers of a shot (shot.far) are made by the tool from a seed, so the
same instruction gives the same skyline, mountains or trees, or are a 360°
panorama (an equirectangular image from 素材, kind "panorama"). Only the
directions the picture sees (and a little more) are made.

What may go to a far layer: a thing whose place in the picture moves by less
than a pixel when the camera is a metre higher or lower (f·1m/D ≤ 1px), so
the camera's height (often a guess in a Blockout) does not matter for it.
"""

from __future__ import annotations

import math
import random

from .camera import Camera

BANDS = ("near", "middle", "far")
BAND_LABELS = {"near": "近景", "middle": "中景", "far": "遠景"}
NEAR_M = 25.0
FAR_M = 250.0
#: Line widths and tones by band (× the near ones; the tones are made lighter by this much).
LINE_SCALE = {"near": 1.0, "middle": 0.75, "far": 0.55, "ground": 0.5}
TONE_LIFT = {"near": 0.0, "middle": 0.08, "far": 0.18}

DEFAULTS = {
    "skyline": {"distanceM": 800.0, "heightM": (15.0, 90.0)},
    "mountains": {"distanceM": 6000.0, "heightM": (200.0, 900.0)},
    "trees": {"distanceM": 150.0, "heightM": (6.0, 18.0)},
}
KIND_LABELS = {"panorama": "全天球の画像", "skyline": "街並み", "mountains": "山並み", "trees": "木立"}
MAX_PIECES = 400


def band_of(distance_m: float) -> str:
    if distance_m <= NEAR_M:
        return "near"
    return "middle" if distance_m <= FAR_M else "far"


def level_distance(camera: Camera, point) -> float:
    return math.hypot(point[0] - camera.position[0], point[1] - camera.position[1])


def parallax_free_m(camera: Camera, focal_px: float | None = None, metres: float = 1.0, pixels: float = 1.0) -> float:
    """How far a thing must be for `metres` of camera height to move it by at most `pixels`."""
    return (focal_px or camera.focal_px) * metres / pixels


def view_azimuths(camera: Camera, margin_deg: float = 4.0) -> tuple[float, float]:
    """The level directions (degrees from world +X, counter-clockwise) the picture sees, from its edges, with a margin."""
    forward = camera.camera_axes_world()[2]
    base = math.atan2(forward[1], forward[0])
    if math.hypot(forward[0], forward[1]) < 1e-6:  # straight up or down: all round
        return math.degrees(base) - 180.0, math.degrees(base) + 180.0
    w, h = camera.width, camera.height
    angles = []
    for i in range(9):
        for j in range(9):
            q = (w * i / 8, h * j / 8)
            d = camera.ray(q)
            if math.hypot(d[0], d[1]) < 1e-6:
                continue
            a = math.atan2(d[1], d[0]) - base
            a = (a + math.pi) % (2 * math.pi) - math.pi
            angles.append(a)
    lo, hi = min(angles), max(angles)
    span = hi - lo
    lo -= span * 0.1 + math.radians(margin_deg)
    hi += span * 0.1 + math.radians(margin_deg)
    if hi - lo >= 2 * math.pi:
        lo, hi = -math.pi, math.pi
    return math.degrees(base + lo), math.degrees(base + hi)


def _range(layer: dict, kind: str) -> tuple[float, tuple[float, float]]:
    d = float(layer.get("distanceM") or DEFAULTS[kind]["distanceM"])
    lo, hi = layer.get("heightM") or DEFAULTS[kind]["heightM"]
    lo, hi = sorted((float(lo), float(hi)))
    return d, (lo, max(hi, lo + 0.1))


def _at(camera: Camera, azimuth_deg: float, distance: float) -> tuple[float, float]:
    a = math.radians(azimuth_deg)
    return camera.position[0] + distance * math.cos(a), camera.position[1] + distance * math.sin(a)


def skyline(camera: Camera, layer: dict, span: tuple[float, float]) -> dict:
    """Blocks of buildings standing along the far arc, square to the world's axes (so they run to the vanishing points)."""
    rng = random.Random(layer.get("seed", 0))
    d, (lo, hi) = _range(layer, "skyline")
    boxes = []
    a = span[0]
    while a < span[1] and len(boxes) < MAX_PIECES:
        width = rng.uniform(12.0, 50.0)
        depth = rng.uniform(12.0, 40.0)
        dist = d * rng.uniform(0.9, 1.25)
        height = lo + (hi - lo) * rng.random() ** 1.6
        x, y = _at(camera, a + math.degrees(width / 2 / dist), dist)
        boxes.append({"centreM": [round(x, 3), round(y, 3), 0.0], "sizeM": [round(width, 3), round(depth, 3), round(height, 2)]})
        a += math.degrees((width + rng.uniform(0.0, 8.0)) / dist)
    return {"kind": "skyline", "distanceM": d, "boxes": boxes}


def mountains(camera: Camera, layer: dict, span: tuple[float, float]) -> dict:
    """A ridge along the far arc: heights from a few waves with seeded phases (rough, but the same each time)."""
    rng = random.Random(layer.get("seed", 0))
    d, (lo, hi) = _range(layer, "mountains")
    waves = [(rng.uniform(0.6, 1.4) * k, rng.uniform(0, 2 * math.pi), 1.0 / k**1.3) for k in (1, 2, 3, 5, 8, 13, 21)]
    total = sum(w for _, _, w in waves)
    n = 160
    ridge = []
    for i in range(n + 1):
        t = i / n
        a = span[0] + (span[1] - span[0]) * t
        u = math.radians(a) * 3.0  # the same mountains whichever way the picture looks
        value = sum(w * math.sin(f * u + p) for f, p, w in waves) / total  # -1..1
        height = lo + (hi - lo) * (0.5 + 0.5 * value)
        dist = d * (1.0 + 0.08 * math.sin(u * 2.3 + waves[0][1]))
        x, y = _at(camera, a, dist)
        ridge.append([round(x, 2), round(y, 2), round(height, 2)])
    return {"kind": "mountains", "distanceM": d, "ridge": ridge}


def trees(camera: Camera, layer: dict, span: tuple[float, float]) -> dict:
    """A row of trees along the arc, in clumps: most broadleaf (a crown of lumps), a few conifers (cones)."""
    rng = random.Random(layer.get("seed", 0))
    d, (lo, hi) = _range(layer, "trees")
    out = []
    a = span[0]
    while a < span[1] and len(out) < MAX_PIECES:
        clump = rng.randint(3, 9)
        for _ in range(clump):
            height = rng.uniform(lo, hi)
            radius = height * rng.uniform(0.22, 0.35)
            dist = d * rng.uniform(0.92, 1.12)
            x, y = _at(camera, a, dist)
            form = "conifer" if rng.random() < layer.get("conifers", 0.2) else "broad"
            out.append(
                {
                    "centreM": [round(x, 3), round(y, 3), 0.0],
                    "heightM": round(height, 2),
                    "radiusM": round(radius * (1.0 if form == "conifer" else 1.3), 2),
                    "form": form,
                    "seed": rng.randrange(1 << 16),
                }
            )
            a += math.degrees(radius * rng.uniform(0.9, 1.6) / dist)
        a += math.degrees(rng.uniform(4.0, 30.0) / d)
    return {"kind": "trees", "distanceM": d, "trees": out[:MAX_PIECES]}


def far_layers(camera: Camera, layers: list[dict], panoramas: dict | None = None) -> tuple[list[dict], list[str]]:
    """The far layers of a shot made into data: [{kind, ...}], and notes (a panorama missing from 素材 is left out)."""
    span = view_azimuths(camera)
    out, notes = [], []
    for layer in layers or []:
        kind = layer.get("kind")
        if kind == "panorama":
            asset = (panoramas or {}).get(layer.get("asset") or "")
            if not asset:
                notes.append(f"遠景の全天球の画像「{layer.get('asset', '')}」が素材にないので、遠景の画像なしで組む")
                continue
            out.append({"kind": "panorama", **asset, "turnDeg": float(layer.get("turnDeg") or 0.0)})
        elif kind == "skyline":
            out.append(skyline(camera, layer, span))
        elif kind == "mountains":
            out.append(mountains(camera, layer, span))
        elif kind == "trees":
            out.append(trees(camera, layer, span))
    return out, notes


def panorama_width_needed(focal_px: float) -> int:
    """The width an equirectangular image needs so one of its pixels is no bigger than one of the picture's."""
    return math.ceil(2 * math.pi * focal_px)
