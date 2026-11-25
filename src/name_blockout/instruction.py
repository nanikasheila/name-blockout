# SPDX-License-Identifier: GPL-3.0-or-later
"""背景の指示書 (instruction): reading, checking against the schema, and the
panel's picture (its frame: paper mm to the picture's pixels).

The instruction is the contract between the name tool (name-studio) and
name-blockout: schema/v1/instruction.schema.json, explained in
docs/instruction-format.md. It is read only; what the requirements phase
adds (answers, assumptions, versions) lives beside it (requirement.py).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import FORMAT, FORMAT_VERSION
from .vec import bounds

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"


class InstructionError(ValueError):
    """The instruction cannot be read (not JSON, another format, or not as the schema says)."""

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = problems or []


def schema_path(version: int = FORMAT_VERSION) -> Path:
    """The schema: packaged with the code, or the repository's schema/ when run from a checkout."""
    packaged = SCHEMA_DIR / f"v{version}" / "instruction.schema.json"
    if packaged.exists():
        return packaged
    return Path(__file__).resolve().parents[2] / "schema" / f"v{version}" / "instruction.schema.json"


def load_schema(version: int = FORMAT_VERSION) -> dict:
    return json.loads(schema_path(version).read_text(encoding="utf-8"))


def schema_problems(data: Any) -> list[str]:
    """What does not follow the schema (empty when it does). Needs `jsonschema`; without it, the basic shape only."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return _basic_problems(data)
    validator = jsonschema.Draft202012Validator(load_schema())
    out = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in error.absolute_path) or "(全体)"
        out.append(f"{where}: {error.message}")
    return out


def _basic_problems(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["(全体): オブジェクトではありません"]
    out = []
    if data.get("format") != FORMAT:
        out.append(f"format: {FORMAT!r} ではありません")
    if data.get("formatVersion") != FORMAT_VERSION:
        out.append(f"formatVersion: {FORMAT_VERSION} ではありません")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        out.append("shots: コマがありません")
        return out
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict) or not isinstance(shot.get("id"), str):
            out.append(f"shots/{i}: id がありません")
            continue
        frame = shot.get("frame")
        if not isinstance(frame, dict) or len(frame.get("boxMm") or []) != 4 or not frame.get("dpi"):
            out.append(f"shots/{i}/frame: boxMm と dpi が要ります")
    return out


def read_instruction(path: str | Path) -> dict:
    """The instruction at `path`, checked (InstructionError when it cannot be used)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise InstructionError(f"{path} を読めません: {error}") from error
    return check_instruction(data)


def check_instruction(data: Any) -> dict:
    if isinstance(data, dict) and data.get("format") == FORMAT and data.get("formatVersion") not in (None, FORMAT_VERSION):
        raise InstructionError(
            f"この name-blockout は指示書の版 {FORMAT_VERSION} を読みます（このファイルは版 {data.get('formatVersion')}）。"
        )
    problems = schema_problems(data)
    if problems:
        raise InstructionError("指示書がスキーマに合いません", problems)
    ids = [shot["id"] for shot in data["shots"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise InstructionError("同じコマが 2 回あります", [f"shots: {i}" for i in dupes])
    return data


def find_shot(data: dict, shot_id: str) -> dict:
    for shot in data["shots"]:
        if shot["id"] == shot_id:
            return shot
    raise KeyError(shot_id)


@dataclass(frozen=True)
class Frame:
    """A panel's picture: the paper box it shows (mm) and its pixels."""

    box: tuple[float, float, float, float]
    dpi: float
    width: int
    height: int

    @property
    def scale(self) -> float:
        """Pixels per mm."""
        return self.dpi / 25.4

    @property
    def longer(self) -> int:
        return max(self.width, self.height)

    def px(self, point) -> tuple[float, float]:
        """A paper point (mm) in the picture (px from its top-left, unrounded)."""
        return ((point[0] - self.box[0]) * self.scale, (point[1] - self.box[1]) * self.scale)

    def mm(self, point) -> tuple[float, float]:
        return (point[0] / self.scale + self.box[0], point[1] / self.scale + self.box[1])

    def px_box(self, shape) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = bounds(shape)
        a, b = self.px((x0, y0)), self.px((x1, y1))
        return (a[0], a[1], b[0], b[1])

    def at_dpi(self, dpi: float) -> Frame:
        """The same box drawn at another resolution (a preview)."""
        return frame_of({"boxMm": list(self.box), "dpi": dpi})


def pixels(box, dpi: float) -> tuple[int, int]:
    """As name-studio's boxPixels: the box's size at dpi, rounded half up."""
    k = dpi / 25.4
    return (_round((box[2] - box[0]) * k), _round((box[3] - box[1]) * k))


def _round(v: float) -> int:
    # JavaScript's Math.round: half up (not Python's half to even).
    return int(math.floor(v + 0.5))


def frame_of(frame: dict) -> Frame:
    box = tuple(float(v) for v in frame["boxMm"])
    dpi = float(frame["dpi"])
    width, height = pixels(box, dpi)
    return Frame(box=box, dpi=dpi, width=max(1, width), height=max(1, height))
