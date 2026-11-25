# SPDX-License-Identifier: GPL-3.0-or-later
"""案 (takes) in the background folder, as name-studio reads them.

Pictures: 案/<panel>/<take>/{完成,線画,トーン,影}.png. Each take is listed in
背景.json (the request's own: 依頼/<request id>/背景.json, else the folder's)
as {"panel", "take", "box", "files", "note", "request"}. name-studio reads
the folder's 背景.json and every request's, a later entry for the same
panel and take standing. name-blockout also keeps what it built from in
blockout/<panel>/<take>/ (plan.json, check.json, scene.blend).
"""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST_FILE = "背景.json"
REQUEST_DIR = "依頼"
TAKES_DIR = "案"
WORK_DIR = "blockout"


def manifest_paths(folder: Path) -> list[Path]:
    out = [folder / MANIFEST_FILE]
    requests = folder / REQUEST_DIR
    if requests.is_dir():
        out += sorted(p / MANIFEST_FILE for p in requests.iterdir() if p.is_dir())
    return [p for p in out if p.exists()]


def read_takes(folder: Path) -> list[dict]:
    takes = []
    for path in manifest_paths(folder):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        items = data if isinstance(data, list) else (data or {}).get("takes") or []
        takes += [t for t in items if isinstance(t, dict)]
    return takes


def next_take(folder: Path, panel: str) -> str:
    numbers = [int(t["take"]) for t in read_takes(folder) if t.get("panel") == panel and str(t.get("take", "")).isdigit()]
    if (folder / TAKES_DIR / panel).is_dir():
        numbers += [int(p.name) for p in (folder / TAKES_DIR / panel).iterdir() if p.name.isdigit()]
    return str(max(numbers, default=0) + 1)


def add_take(folder: Path, request_id: str | None, entry: dict) -> Path:
    """Add (or replace) a take in the request's 背景.json; written whole, through a temporary file."""
    path = (folder / REQUEST_DIR / request_id / MANIFEST_FILE) if request_id else (folder / MANIFEST_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"takes": []}
    if path.exists():
        try:
            read = json.loads(path.read_text(encoding="utf-8-sig"))
            data = (
                read
                if isinstance(read, dict) and isinstance(read.get("takes"), list)
                else {"takes": read if isinstance(read, list) else []}
            )
        except json.JSONDecodeError:
            pass
    data["takes"] = [t for t in data["takes"] if not (t.get("panel") == entry["panel"] and str(t.get("take")) == str(entry["take"]))]
    data["takes"].append(entry)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
