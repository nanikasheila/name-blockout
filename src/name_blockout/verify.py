# SPDX-License-Identifier: GPL-3.0-or-later
"""照合: does the built scene show what the instruction asks, in numbers?

The measurements come from Blender (blender/measure.py: its own camera
projection of the scene as built: the horizon, where the scene's level and
upright edges meet, the outline of each thing and figure). They are compared
with the targets taken from the instruction (plan.targets), never with this
package's own camera, so a mistake on either side shows.

Tolerances (shares of the picture's longer side unless said):

- eye level: each end within 0.5 %;
- a vanishing point: the lines aimed at it, seen from points across the
  picture, within 0.3° of the lines aimed at the target (a point far outside
  the picture is judged by the lines it gives, not by its distance);
- a thing: its outline overlaps the marked range by IoU ≥ 0.85 when its
  size was free (only reported when its size or model was given);
- a figure: its feet within 1 %.
"""

from __future__ import annotations

import math

from .camera import angle_between_lines
from .vec import box_iou

HORIZON_TOL = 0.005
ANGLE_TOL_DEG = 0.3
IOU_TOL = 0.85
FEET_TOL = 0.01


def _samples(width: int, height: int):
    return [(width * fx, height * fy) for fx in (0.1, 0.5, 0.9) for fy in (0.1, 0.5, 0.9)]


def line_error_deg(width: int, height: int, measured, target) -> float:
    """The largest angle between lines to `measured` and to `target`, from points across the picture."""
    worst = 0.0
    for p in _samples(width, height):
        if math.dist(p, target) < 1 or math.dist(p, measured) < 1:
            continue
        worst = max(worst, angle_between_lines(p, measured, target))
    return worst


def verify(plan: dict, measured: dict) -> dict:
    t = plan["targets"]
    width, height = t["sizePx"]
    longer = max(width, height)
    checks = []

    def add(name, value, limit, ok, **extra):
        checks.append({"name": name, "value": value, "limit": limit, "pass": bool(ok), **extra})

    if "horizonPx" in t and measured.get("horizonPx"):
        for side, a, b in zip(("左端", "右端"), measured["horizonPx"], t["horizonPx"]):
            err = abs(a - b)
            add(
                f"アイレベル（{side}）",
                round(err, 2),
                round(HORIZON_TOL * longer, 2),
                err <= HORIZON_TOL * longer,
                measuredPx=round(a, 2),
                targetPx=round(b, 2),
                unit="px",
            )

    axes = plan["camera"].get("vanishingAxes") or []
    for i, target in enumerate(t.get("vanishingPx") or []):
        got = (measured.get("vanishingPx") or {}).get(str(i))
        if got is None:
            add(f"消失点 {i + 1}", None, ANGLE_TOL_DEG, False, note="測れませんでした（カメラの後ろ）")
            continue
        err = line_error_deg(width, height, got, target)
        add(
            f"消失点 {i + 1}（{axes[i] if i < len(axes) else '?'} の向き）",
            round(err, 4),
            ANGLE_TOL_DEG,
            err <= ANGLE_TOL_DEG,
            measuredPx=[round(v, 1) for v in got],
            targetPx=[round(v, 1) for v in target],
            unit="deg",
        )
        edges = (measured.get("edgeVanishingPx") or {}).get(str(i))
        if edges:
            err = line_error_deg(width, height, edges["point"], target)
            add(
                f"消失点 {i + 1}（場の辺 {edges['lines']} 本が集まる点）",
                round(err, 4),
                ANGLE_TOL_DEG,
                err <= ANGLE_TOL_DEG,
                measuredPx=[round(v, 1) for v in edges["point"]],
                targetPx=[round(v, 1) for v in target],
                unit="deg",
            )

    for obj in plan.get("objects", []):
        box = (measured.get("objectsPx") or {}).get(obj["id"])
        target = t["objectsPx"].get(obj["id"])
        if box is None or target is None:
            add(f"物「{obj['label']}」", None, IOU_TOL, False, note="測れませんでした")
            continue
        if obj.get("footless"):
            # Its foot is not in the picture (or not in the range): the range is filled by its top and sides.
            target = [target[0], target[1], target[2], max(target[3], box[3])]
        iou = box_iou(box, target)
        strict = "asset" not in obj and not obj.get("fixedSize") and not obj.get("fixedPlace")
        add(
            f"物「{obj['label']}」の範囲",
            round(iou, 4),
            IOU_TOL,
            iou >= IOU_TOL or not strict,
            measuredPx=[round(v, 1) for v in box],
            targetPx=[round(v, 1) for v in target],
            unit="IoU",
            **(
                {}
                if strict
                else {"note": "俯瞰図の位置に置いたので参考" if obj.get("fixedPlace") else "大きさか素材が決まっているので参考"}
            ),
        )

    for fig in plan.get("figures", []):
        box = (measured.get("figuresPx") or {}).get(fig["id"])
        target = t["figuresPx"].get(fig["id"])
        if box is None or target is None:
            add(f"人物「{fig.get('name') or fig['id']}」", None, FEET_TOL * longer, False, note="測れませんでした")
            continue
        err = abs(box[3] - target[3])
        add(
            f"人物「{fig.get('name') or fig['id']}」の足",
            round(err, 2),
            round(FEET_TOL * longer, 2),
            err <= FEET_TOL * longer,
            measuredPx=[round(v, 1) for v in box],
            targetPx=[round(v, 1) for v in target],
            unit="px",
            headPx=round(box[1] - target[1], 1),
        )

    return {
        "format": "name-blockout/check",
        "formatVersion": 1,
        "shot": plan["shot"],
        "pass": all(c["pass"] for c in checks),
        "checks": checks,
        "camera": {k: plan["camera"][k] for k in ("lensMm", "shiftX", "shiftY", "tiltDeg", "rollDeg", "headingDeg", "positionM")},
    }


def summary_words(result: dict) -> str:
    """One line for 背景.json's note and people: what was checked and how far off."""
    parts = []
    for c in result["checks"]:
        if c.get("unit") == "words":
            parts.append(f"{c['name']} {c.get('note', '')}")
        elif c["value"] is None:
            parts.append(f"{c['name']}: 測れず")
        elif c.get("unit") == "deg":
            parts.append(f"{c['name']} {c['value']:.2f}°")
        elif c.get("unit") == "IoU":
            parts.append(f"{c['name']} 重なり {c['value'] * 100:.0f}%")
        else:
            parts.append(f"{c['name']} {c['value']:.1f}px")
    head = "照合 OK" if result["pass"] else "照合 NG"
    return f"{head}（{'・'.join(parts)}）" if parts else head
