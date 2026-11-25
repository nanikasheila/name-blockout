# SPDX-License-Identifier: GPL-3.0-or-later
"""Placing simple shapes so they fill what the author marked on the panel.

A thing (物の指示) is a box standing on the ground (or floating), its sides
along the world's level axes, so its edges run to the ruler's vanishing
points. Given the camera, its place and size are found so that the box's
outline in the picture fills the marked range. A figure (人物) is a box of a
person's size whose feet stand on the ground.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .camera import Camera
from .vec import add, box_iou, nelder_mead, scale

DEFAULT_FIGURE_M = 1.6
FIGURE_WIDTH_M = 0.5
FIGURE_DEPTH_M = 0.3


@dataclass
class Placed:
    """A box in the world: centre of its bottom, size along its own axes, and which world axis its x runs along."""

    centre: tuple[float, float, float]
    size: tuple[float, float, float]
    along: str  # "X" or "Y": the world axis of the box's first size
    box_px: tuple[float, float, float, float] | None
    target_px: tuple[float, float, float, float]
    residual_px: float
    iou: float
    note: str = ""

    def corners(self):
        return box_corners(self.centre, self.size, self.along)

    def as_dict(self) -> dict:
        return {
            "centreM": [round(v, 4) for v in self.centre],
            "sizeM": [round(v, 4) for v in self.size],
            "along": self.along,
            "boxPx": [round(v, 1) for v in self.box_px] if self.box_px else None,
            "targetPx": [round(v, 1) for v in self.target_px],
            "residualPx": round(self.residual_px, 2),
            "iou": round(self.iou, 4),
            "note": self.note,
        }


def box_corners(centre, size, along: str = "X"):
    w, d, h = size
    if along == "Y":
        w, d = d, w
    cx, cy, cz = centre
    return [(cx + sx * w / 2, cy + sy * d / 2, cz + z) for sx in (-1, 1) for sy in (-1, 1) for z in (0.0, h)]


def projected_box(camera: Camera, corners):
    pts = [camera.project(c) for c in corners]
    if any(p is None for p in pts):
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _start(camera: Camera, target, floor: float):
    x0, y0, x1, y1 = target
    foot = camera.ground_point(((x0 + x1) / 2, y1), floor)
    if foot is None or math.dist(foot[:2], camera.position[:2]) > 5000:
        # Above the horizon (or very far): put it ahead at a distance from its width.
        _, _, forward = camera.camera_axes_world()
        level = (forward[0], forward[1], 0.0)
        n = math.hypot(level[0], level[1]) or 1.0
        distance = 10.0
        foot = add((camera.position[0], camera.position[1], floor), scale((level[0] / n, level[1] / n, 0.0), distance))
    distance = math.dist(foot, camera.position)
    width = max(0.1, (x1 - x0) / camera.focal_px * distance)
    height = max(0.1, (y1 - y0) / camera.focal_px * distance)
    return foot, width, height


def fit_box(
    camera: Camera,
    target,
    size=None,
    along: str = "X",
    on_ground: bool = True,
    floor: float = 0.0,
    prior=None,
) -> Placed:
    """A box filling `target` (picture px [x0, y0, x1, y1]). Size fixed when given, else found: among the boxes that
    fill it, the one nearest the proportions (and size) of `prior` [w, d, h] (a cube's when none)."""
    prior = tuple(prior) if prior else None
    ratio = prior[0] / prior[1] if prior else 1.0
    longer = camera.longer
    foot, width, height = _start(camera, target, floor)

    def unpack(q):
        if size is not None:
            if on_ground:
                return (q[0], q[1], floor), tuple(size)
            return (q[0], q[1], q[2]), tuple(size)
        x, y, lw, ld, lh = q[:5]
        z = floor if on_ground else q[5]
        return (x, y, z), (math.exp(lw), math.exp(ld), math.exp(lh))

    def cost(q):
        centre, s = unpack(q)
        box = projected_box(camera, box_corners(centre, s, along))
        if box is None:
            return 1e9 + sum(v * v for v in q)
        c = sum(((a - b) / longer) ** 2 for a, b in zip(box, target))
        if size is None:
            c += 1e-4 * (math.log(s[0] / s[1]) - math.log(ratio)) ** 2
            if prior:
                c += 1e-4 * (math.log(s[2] / s[0]) - math.log(prior[2] / prior[0])) ** 2
                c += 1e-6 * (math.log(s[0]) - math.log(prior[0])) ** 2
        return c

    if size is not None:
        q0 = [foot[0], foot[1]] + ([] if on_ground else [max(floor, foot[2])])
        steps = [max(0.2, width / 2)] * len(q0)
    else:
        q0 = [foot[0], foot[1], math.log(width), math.log(width / ratio), math.log(height)] + ([] if on_ground else [foot[2]])
        steps = [max(0.2, width / 2), max(0.2, width / 2), 0.3, 0.3, 0.3] + ([] if on_ground else [0.5])
    best = (q0, cost(q0))
    for k in (1.0, 0.3, 0.1, 0.03):
        q, v = nelder_mead(cost, best[0], step=[s * k for s in steps], iterations=3000)
        if v <= best[1]:
            best = (q, v)
    centre, s = unpack(best[0])
    box = projected_box(camera, box_corners(centre, s, along))
    residual = math.sqrt(best[1] / 4) * longer if box else float("inf")
    return Placed(
        centre=tuple(centre),
        size=tuple(s),
        along=along,
        box_px=box,
        target_px=tuple(target),
        residual_px=residual,
        iou=box_iou(box, target) if box else 0.0,
    )


def fit_figure(camera: Camera, target, height_m: float = DEFAULT_FIGURE_M, floor: float = 0.0) -> Placed:
    """A person of `height_m` whose feet stand where the marked range ends (its head where it begins, if the camera height agrees)."""
    x0, y0, x1, y1 = target
    longer = camera.longer
    foot, _, _ = _start(camera, target, floor)
    size = (FIGURE_WIDTH_M, FIGURE_DEPTH_M, height_m)

    def cost(q):
        corners = box_corners((q[0], q[1], floor), size)
        box = projected_box(camera, corners)
        if box is None:
            return 1e9
        # Feet (bottom) and the middle across count most; the head shows whether the camera height agrees.
        return ((box[3] - y1) / longer) ** 2 + (((box[0] + box[2]) - (x0 + x1)) / 2 / longer) ** 2 + 0.05 * ((box[1] - y0) / longer) ** 2

    q, v = nelder_mead(cost, [foot[0], foot[1]], step=0.5, iterations=3000)
    q, v = nelder_mead(cost, q, step=0.05, iterations=3000)
    centre = (q[0], q[1], floor)
    box = projected_box(camera, box_corners(centre, size))
    head_error = (box[1] - y0) if box else float("inf")
    return Placed(
        centre=centre,
        size=size,
        along="X",
        box_px=box,
        target_px=tuple(target),
        residual_px=abs(head_error),
        iou=box_iou(box, target) if box else 0.0,
        note=f"頭の行のずれ {head_error:+.0f}px" if box else "カメラの後ろ",
    )


def camera_height_from_figure(camera: Camera, target, height_m: float) -> float | None:
    """For a level camera: the eye height that makes a person of `height_m` standing in `target` as tall as drawn.

    The horizon crosses every standing person at the camera's height, so
    height = person × (feet − horizon) / (feet − head), rows measured at the person.
    """
    if camera.mode != "level":
        return None
    x0, y0, x1, y1 = target
    rows = camera.horizon_rows()
    x = (x0 + x1) / 2
    horizon = rows[0] + (rows[1] - rows[0]) * x / camera.width
    if y1 - y0 < 1:
        return None
    return height_m * (y1 - horizon) / (y1 - y0)
