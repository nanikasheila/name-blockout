# SPDX-License-Identifier: GPL-3.0-or-later
"""要求: what the requirements phase settles for a shot, kept beside the
instruction (which stays as the name tool wrote it), with versions.

<作業フォルダー>/要求/<shot id>.json:

    {"format": "name-blockout/requirement", "formatVersion": 1, "shot": "...",
     "versions": [{"version": 1, "state": "draft"|"confirmed", "at": "...",
                   "answers": {"camera.heightM": 1.2}, "assumptions": [...],
                   "hashes": {"design": "...", "develop": "..."}}]}

The shot used for building is the instruction's, with the answers filling
what it leaves open (`effective`). When the author later sets a value in the
name tool, the instruction wins and that answer is reported as replaced.
Confirming makes a new version when the effective shot changed; each built
take records the version and hashes it was built from (redo_scope).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from .scope import hashes

REQUIREMENT_FORMAT = "name-blockout/requirement"
REQUIREMENT_DIR = "要求"


def _split(path: str) -> list[str]:
    return [p for p in path.replace("/", ".").split(".") if p]


def get_path(shot: dict, path: str):
    node = shot
    for key in _split(path):
        if isinstance(node, list):
            node = next((item for item in node if isinstance(item, dict) and item.get("id") == key), None)
        elif isinstance(node, dict):
            node = node.get(key)
        else:
            return None
        if node is None:
            return None
    return node


def set_path(shot: dict, path: str, value) -> bool:
    """Set `path` (a.b.c, or objects/<id>/field) in `shot`; False when a list item it names is missing."""
    keys = _split(path)
    node = shot
    for key in keys[:-1]:
        if isinstance(node, list):
            item = next((it for it in node if isinstance(it, dict) and it.get("id") == key), None)
            if item is None:
                return False
            node = item
            continue
        if key not in node or node[key] is None:
            if key in ("objects", "figures"):
                return False
            node[key] = {}
        node = node[key]
    if isinstance(node, list):
        return False
    node[keys[-1]] = value
    return True


def effective(shot: dict, answers: dict) -> tuple[dict, list[str]]:
    """The shot with the answers filling what it leaves open, and the answers the instruction now overrides."""
    out = copy.deepcopy(shot)
    replaced = []
    for path, value in answers.items():
        if get_path(shot, path) is not None:
            replaced.append(path)
            continue
        set_path(out, path, value)
    return out, replaced


def requirement_path(folder: str | Path, shot_id: str) -> Path:
    return Path(folder) / REQUIREMENT_DIR / f"{shot_id}.json"


def read_requirement(folder: str | Path, shot_id: str) -> dict:
    path = requirement_path(folder, shot_id)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data.get("format") == REQUIREMENT_FORMAT:
            return data
    return {"format": REQUIREMENT_FORMAT, "formatVersion": 1, "shot": shot_id, "versions": []}


def write_requirement(folder: str | Path, data: dict) -> Path:
    path = requirement_path(folder, data["shot"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def current(data: dict) -> dict | None:
    return data["versions"][-1] if data["versions"] else None


def answer(folder: str | Path, shot: dict, values: dict, by: str = "author") -> dict:
    """Add answers to the shot's draft (a new draft version after a confirmed one)."""
    data = read_requirement(folder, shot["id"])
    last = current(data)
    if last is None or last["state"] == "confirmed":
        last = {
            "version": (last["version"] + 1) if last else 1,
            "state": "draft",
            "answers": dict(last["answers"]) if last else {},
            "assumptions": list(last.get("assumptions", [])) if last else [],
        }
        data["versions"].append(last)
    for path, value in values.items():
        if value is None:
            last["answers"].pop(path, None)
        else:
            last["answers"][path] = value
    last["at"] = _now()
    last["by"] = by
    write_requirement(folder, data)
    return last


def confirm(folder: str | Path, shot: dict, assumptions: list | None = None) -> dict:
    """Confirm the shot as it now stands: a new version when it differs from the last confirmed one."""
    data = read_requirement(folder, shot["id"])
    last = current(data)
    answers = dict(last["answers"]) if last else {}
    shot_now, _ = effective(shot, answers)
    h = hashes(shot_now)
    confirmed = [v for v in data["versions"] if v["state"] == "confirmed"]
    if confirmed and confirmed[-1].get("hashes") == h and (last is None or last["state"] == "confirmed"):
        return confirmed[-1]
    if last is None or last["state"] == "confirmed":
        last = {"version": (last["version"] + 1) if last else 1, "answers": answers}
        data["versions"].append(last)
    last.update({"state": "confirmed", "at": _now(), "hashes": h, "assumptions": assumptions or last.get("assumptions", [])})
    write_requirement(folder, data)
    return last


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
