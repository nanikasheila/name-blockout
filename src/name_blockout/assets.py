# SPDX-License-Identifier: GPL-3.0-or-later
"""素材.json: places and things kept for reuse (shared with name-studio's bgassets.ts).

{"assets": [{"name", "kind": "place"|"thing", "file", "collection"?, "note"?, "picture"?, "by"?}]}
Paths are from the 素材 folder, "/" between folders. name-studio reads the
same file; a later entry with the same name stands.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ASSETS_FILE = "素材.json"


@dataclass(frozen=True)
class Asset:
    name: str
    kind: str
    file: str
    collection: str | None = None
    note: str | None = None
    picture: str | None = None
    by: str | None = None


def _in_folder(value) -> str | None:
    if not isinstance(value, str):
        return None
    parts = value.replace("\\", "/").removeprefix("./").split("/")
    if not parts or any(not p or p in (".", "..") or ":" in p for p in parts):
        return None
    return "/".join(parts)


def read_assets(folder: str | Path) -> tuple[list[Asset], list[str]]:
    path = Path(folder) / ASSETS_FILE
    if not path.exists():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        return [], [f"{ASSETS_FILE} を読めません: {error}"]
    items = data if isinstance(data, list) else (data or {}).get("assets")
    if not isinstance(items, list):
        return [], [f"{ASSETS_FILE} に assets の一覧がありません"]
    named: dict[str, Asset] = {}
    problems = []
    for i, item in enumerate(items):
        item = item if isinstance(item, dict) else {}
        name = item.get("name").strip() if isinstance(item.get("name"), str) else ""
        file = _in_folder(item.get("file"))
        if not name or not file:
            problems.append(f"{i + 1} 件目: 名前かファイル（素材のフォルダーの中）がありません")
            continue
        named.pop(name, None)
        named[name] = Asset(
            name=name,
            kind="place" if item.get("kind") == "place" else "thing",
            file=file,
            collection=item.get("collection") or None,
            note=item.get("note") or None,
            picture=_in_folder(item.get("picture")),
            by=item.get("by") or None,
        )
    return list(named.values()), problems


def object_asset(obj: dict, assets: list[Asset]) -> Asset | None:
    """As bgassets.ts objectAsset: the one named, else the thing named as the label is (or its first word; the longest)."""
    if obj.get("asset"):
        return next((a for a in assets if a.name == obj["asset"].strip()), None)
    label = (obj.get("label") or "").strip()
    things = sorted(
        (a for a in assets if a.kind == "thing" and (label == a.name or label.startswith(a.name + " ") or label.startswith(a.name + "　"))),
        key=lambda a: -len(a.name),
    )
    return things[0] if things else None
