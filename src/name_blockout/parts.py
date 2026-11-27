# SPDX-License-Identifier: GPL-3.0-or-later
"""部品 (a thing's parts) as numbers before any geometry: the table of their sizes, the thing drawn from the front,
the side and above (views one can measure, unlike a panel in perspective), and the check of how they are put
together: no part may float. A part stands on the ground or touches a part that does; a gap is a mistake in the
numbers, found here for the cost of a line instead of after modelling.

Parts are the shapes of shapes.py (metres; the middle of the thing's bottom at the origin, its front toward −Y).
Nothing here needs Blender.
"""

from __future__ import annotations

import json
import math
import re
from html import escape
from pathlib import Path

from .shapes import bounds

PARTS_DIR = "部品"
#: Parts nearer than this touch (m): the builders round to a tenth of a millimetre, a pen cannot show less.
TOUCH = 0.003
VIEW_PX = 420
PAD = 46
FILLS = {"ガラス": "#dce8f5", "黒い塗装": "#555", "草": "#dcebd6", "木": "#efe4d2", "瓦": "#cfcfd6"}


def box_of(part: dict) -> tuple[list[float], list[float]]:
    """A part's lowest and highest corner (a ball, a cylinder and a gable by the box around them; a tilted branch
    by the box around it tilted)."""
    c, s = part["c"], part["s"]
    half = [v / 2 for v in s]
    if part.get("tilt"):
        # A cylinder along Z leaned toward `tilt`: its length reaches sideways too.
        reach = s[2] / 2
        half = [half[0] + abs(part["tilt"][0]) * reach, half[1] + abs(part["tilt"][1]) * reach, half[2]]
    return [c[i] - half[i] for i in range(3)], [c[i] + half[i] for i in range(3)]


def gap(a: dict, b: dict) -> float:
    """How far apart two parts are (0 when they touch or overlap), by their boxes."""
    (alo, ahi), (blo, bhi) = box_of(a), box_of(b)
    return math.sqrt(sum(max(0.0, alo[i] - bhi[i], blo[i] - ahi[i]) ** 2 for i in range(3)))


def assembly(parts: list[dict], touch: float = TOUCH) -> dict:
    """How the parts are put together: the whole's size, what each part rests on, and the parts that float (they
    neither stand on the ground nor touch, through other parts, one that does)."""
    if not parts:
        return {"parts": 0, "sizeM": [0.0, 0.0, 0.0], "on": [], "floating": [], "pass": True}
    lo, hi = bounds(parts)
    boxes = [box_of(p) for p in parts]
    on: list[str | None] = [None] * len(parts)
    reached = []
    for i, (plo, _) in enumerate(boxes):
        if plo[2] - lo[2] <= touch:
            on[i] = "地面"
            reached.append(i)
    queue = list(reached)
    while queue:
        i = queue.pop(0)
        for j in range(len(parts)):
            if on[j] is None and gap(parts[i], parts[j]) <= touch:
                on[j] = parts[i]["name"]
                queue.append(j)
    floating = []
    for j, p in enumerate(parts):
        if on[j] is not None:
            continue
        nearest = min((k for k in range(len(parts)) if on[k] is not None), key=lambda k: gap(parts[k], p), default=None)
        floating.append(
            {
                "index": j,
                "name": p["name"],
                "gapM": round(gap(parts[nearest], p), 4) if nearest is not None else None,
                "nearest": parts[nearest]["name"] if nearest is not None else None,
            }
        )
    return {
        "parts": len(parts),
        "sizeM": [round(hi[i] - lo[i], 4) for i in range(3)],
        "on": on,
        "floating": floating,
        "pass": not floating,
    }


def table(parts: list[dict]) -> list[dict]:
    """The parts as a table of numbers (cm): what one reads before modelling."""
    on = assembly(parts)["on"]
    rows = []
    for p, rests in zip(parts, on):
        rows.append(
            {
                "name": p["name"],
                "shape": p.get("shape", "box"),
                "sizeCm": [round(v * 100, 1) for v in p["s"]],
                "centreCm": [round(v * 100, 1) for v in p["c"]],
                "material": p.get("material"),
                "on": rests,
            }
        )
    return rows


def floating_words(label: str, result: dict) -> list[str]:
    return [
        f"物「{label}」: 部品「{f['name']}」が浮いている"
        + (f"（「{f['nearest']}」から {f['gapM'] * 100:.1f} cm）" if f.get("nearest") else "")
        for f in result["floating"]
    ]


# --- the three views ------------------------------------------------------------------------------

#: A view: its name, the axes across and up the page, the axis it looks along and whether nearer is larger on it.
VIEWS = (
    ("正面", 0, 2, 1, False),  # from the front (−Y): X across, Z up; smaller Y is nearer
    ("側面", 1, 2, 0, True),  # from the right (+X): Y across, Z up; larger X is nearer
    ("上", 0, 1, 2, True),  # from above: X across, Y up the page; larger Z is nearer
)


def _shape_svg(part: dict, a: int, b: int, along: int, to_px) -> str:
    lo, hi = box_of(part)
    x0, y0 = to_px(lo[a], hi[b])
    x1, y1 = to_px(hi[a], lo[b])
    fill = FILLS.get(part.get("material") or "", "#fff")
    stroke = "#fff" if fill == "#555" else "#222"
    kind = part.get("shape", "box")
    style = f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"'
    round_on = kind == "sphere" or (kind == "cylinder" and "XYZ".index(part.get("axis", "Z")) == along)
    if round_on:
        return (
            f'<ellipse cx="{(x0 + x1) / 2:.1f}" cy="{(y0 + y1) / 2:.1f}" rx="{abs(x1 - x0) / 2:.1f}" ry="{abs(y1 - y0) / 2:.1f}" {style}/>'
        )
    if kind == "prism":
        ridge = "XYZ".index(part.get("ridge", "Y"))
        if along == ridge:  # looking along the ridge: the gable's triangle
            return f'<polygon points="{x0:.1f},{y1:.1f} {x1:.1f},{y1:.1f} {(x0 + x1) / 2:.1f},{y0:.1f}" {style}/>'
        if along == 2:  # from above: the two slopes and the ridge between
            if ridge == 1:
                line = f'<line x1="{(x0 + x1) / 2:.1f}" y1="{y0:.1f}" x2="{(x0 + x1) / 2:.1f}" y2="{y1:.1f}" stroke="{stroke}" stroke-width="1"/>'
            else:
                line = f'<line x1="{x0:.1f}" y1="{(y0 + y1) / 2:.1f}" x2="{x1:.1f}" y2="{(y0 + y1) / 2:.1f}" stroke="{stroke}" stroke-width="1"/>'
            return f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" {style}/>{line}'
    return f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" {style}/>'


def _text(x, y, words, size=12, anchor="middle", fill="#222", weight="normal") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" font-weight="{weight}" '
        f'stroke="#fff" stroke-width="3" paint-order="stroke" stroke-linejoin="round">{escape(words)}</text>'
    )


def three_views(label: str, parts: list[dict]) -> str:
    """The thing from the front, the side and above, to one scale, its overall sizes written on: an SVG drawing."""
    lo, hi = bounds(parts)
    size = [hi[i] - lo[i] for i in range(3)]
    scale = VIEW_PX / max(max(size), 1e-6)
    result = assembly(parts)
    floating = {f["index"] for f in result["floating"]}
    cells = {"正面": (0, 0), "側面": (1, 0), "上": (0, 1)}
    cell = VIEW_PX + 2 * PAD
    rows = floating_words(label, result)
    height = 2 * cell + 40 + 20 * max(1, len(rows))
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{2 * cell}" height="{height}" viewBox="0 0 {2 * cell} {height}" '
        "font-family=\"'Noto Sans JP', 'Yu Gothic', 'Hiragino Sans', sans-serif\">",
        f'<rect width="{2 * cell}" height="{height}" fill="#fff"/>',
    ]
    for name, a, b, along, nearer_larger in VIEWS:
        col, row = cells[name]
        ox = col * cell + PAD + (VIEW_PX - size[a] * scale) / 2
        oy = row * cell + PAD + (VIEW_PX - size[b] * scale) / 2

        def to_px(u, v, ox=ox, oy=oy, a=a, b=b):
            return (ox + (u - lo[a]) * scale, oy + (hi[b] - v) * scale)

        order = sorted(range(len(parts)), key=lambda i: box_of(parts[i])[1][along] if nearer_larger else -box_of(parts[i])[0][along])
        for i in order:
            out.append(_shape_svg(parts[i], a, b, along, to_px))
            if i in floating:
                plo, phi = box_of(parts[i])
                x0, y0 = to_px(plo[a], phi[b])
                x1, y1 = to_px(phi[a], plo[b])
                out.append(
                    f'<rect x="{x0 - 3:.1f}" y="{y0 - 3:.1f}" width="{x1 - x0 + 6:.1f}" height="{y1 - y0 + 6:.1f}" fill="none" stroke="#d93025" stroke-width="2" stroke-dasharray="5 3"/>'
                )
        x0, y0 = to_px(lo[a], hi[b])
        x1, y1 = to_px(hi[a], lo[b])
        # The overall sizes: across under the view, up beside it.
        out.append(
            f'<path d="M {x0:.1f} {y1 + 14:.1f} H {x1:.1f} M {x0:.1f} {y1 + 9:.1f} v 10 M {x1:.1f} {y1 + 9:.1f} v 10" stroke="#2f6fe0" stroke-width="1.2" fill="none"/>'
        )
        out.append(_text((x0 + x1) / 2, y1 + 30, f"{size[a] * 100:.0f} cm", 12, fill="#2f6fe0"))
        out.append(
            f'<path d="M {x0 - 14:.1f} {y0:.1f} V {y1:.1f} M {x0 - 19:.1f} {y0:.1f} h 10 M {x0 - 19:.1f} {y1:.1f} h 10" stroke="#2f6fe0" stroke-width="1.2" fill="none"/>'
        )
        out.append(_text(x0 - 20, (y0 + y1) / 2 + 4, f"{size[b] * 100:.0f}", 12, anchor="end", fill="#2f6fe0"))
        out.append(
            _text(
                col * cell + PAD,
                row * cell + 22,
                {"正面": "正面（手前から）", "側面": "側面（右から）", "上": "上から（下が正面）"}[name],
                13,
                anchor="start",
                weight="bold",
            )
        )
    tx, ty = cell + PAD, cell + 30
    out.append(_text(tx, ty, f"{label}（部品 {len(parts)} 個）", 15, anchor="start", weight="bold"))
    out.append(
        _text(tx, ty + 26, f"幅 {size[0] * 100:.0f} cm × 奥行 {size[1] * 100:.0f} cm × 高さ {size[2] * 100:.0f} cm", 13, anchor="start")
    )
    names: dict[str, int] = {}
    for p in parts:
        names[p["name"]] = names.get(p["name"], 0) + 1
    listed = "・".join(f"{n}{f' ×{k}' if k > 1 else ''}" for n, k in names.items())
    for i in range(0, len(listed), 26):
        out.append(_text(tx, ty + 52 + 18 * (i // 26), listed[i : i + 26], 11.5, anchor="start", fill="#444"))
    y = 2 * cell + 24
    if rows:
        for i, line in enumerate(rows):
            out.append(_text(16, y + 20 * i, "！ " + line, 12.5, anchor="start", fill="#b3261e"))
    else:
        out.append(
            _text(
                16,
                y,
                "組み立て: 浮いている部品なし（どの部品も、地面か、地面につながる部品に触れている）",
                12.5,
                anchor="start",
                fill="#1d7268",
            )
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --- files ----------------------------------------------------------------------------------------


def _file_name(obj: dict) -> str:
    """A thing's file name: its label and its id, without what a file name cannot hold."""
    words = "_".join(str(v) for v in (obj.get("label"), obj.get("id")) if v)
    return re.sub(r'[\\/:*?"<>|\s]+', "_", words) or "物"


def write_parts(folder: Path, plan: dict) -> list[dict]:
    """Write each made thing's parts into the work folder's 部品/<コマ>/: its three views (.svg) and its table and
    assembly check (.json). What each file is, and whether the thing is put together."""
    out_dir = Path(folder) / PARTS_DIR / plan["shot"]
    written = []
    for obj in plan.get("objects", []):
        parts = obj.get("parts")
        if not parts:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        result = assembly(parts)
        data = {
            "format": "name-blockout/parts",
            "formatVersion": 1,
            "shot": plan["shot"],
            "object": obj.get("id"),
            "label": obj.get("label"),
            "shapeKind": obj.get("shapeKind"),
            "sizeM": result["sizeM"],
            "parts": table(parts),
            "floating": result["floating"],
            "pass": result["pass"],
        }
        stem = out_dir / _file_name(obj)
        stem.with_suffix(".svg").write_text(three_views(obj.get("label") or "物", parts), encoding="utf-8")
        stem.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        written.append(
            {
                "object": obj.get("id"),
                "label": obj.get("label"),
                "parts": len(parts),
                "sizeM": result["sizeM"],
                "pass": result["pass"],
                "floating": floating_words(obj.get("label") or "物", result),
                "svg": str(stem.with_suffix(".svg")),
                "json": str(stem.with_suffix(".json")),
            }
        )
    return written
