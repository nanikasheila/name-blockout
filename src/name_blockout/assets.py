# SPDX-License-Identifier: GPL-3.0-or-later
"""素材.json: places, things and panoramas kept for reuse (shared with name-studio's bgassets.ts).

{"assets": [{"name", "kind": "place"|"thing"|"panorama", "file", "collection"?, "note"?, "picture"?, "by"?,
             "license"?, "source"?, "author"?, "attribution"?}],
 "allowLicenses"?: [...]}

Paths are from the 素材 folder, "/" between folders. name-studio reads the
same file; a later entry with the same name stands.

Only 素材 free to use, also for work that is sold, are used: the license
(an SPDX id such as "CC0-1.0" or "CC-BY-4.0", or "own" for one's own work)
must be one of ALLOWED_LICENSES or of the file's allowLicenses. One with
another license is left out (the check says so); one with none is used as
one's own, and the check asks for it. What needs credit is listed with the
take (credits).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ASSETS_FILE = "素材.json"
KINDS = ("place", "thing", "panorama")

#: Free, also for work that is sold, with at most a credit to give.
ALLOWED_LICENSES = frozenset(
    {"own", "CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "Unlicense", "0BSD"}
)
#: Need the author named where the work is published.
ATTRIBUTION_LICENSES = frozenset({"CC-BY-4.0", "CC-BY-3.0", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"})
_LICENSE_WORDS = {
    "cc0": "CC0-1.0",
    "cc0 1.0": "CC0-1.0",
    "public domain": "CC0-1.0",
    "cc by 4.0": "CC-BY-4.0",
    "cc-by 4.0": "CC-BY-4.0",
    "cc by": "CC-BY-4.0",
    "cc by 3.0": "CC-BY-3.0",
    "自作": "own",
    "own work": "own",
}


@dataclass(frozen=True)
class Asset:
    name: str
    kind: str
    file: str
    collection: str | None = None
    note: str | None = None
    picture: str | None = None
    by: str | None = None
    license: str | None = None
    source: str | None = None
    author: str | None = None
    attribution: str | None = None

    @property
    def needs_credit(self) -> bool:
        return self.license in ATTRIBUTION_LICENSES

    def credit(self) -> str:
        """One line naming the 素材 as its license asks (the attribution given, else the author, source and license)."""
        if self.attribution:
            return self.attribution
        parts = [f"「{self.name}」"]
        if self.author:
            parts.append(f"by {self.author}")
        if self.source:
            parts.append(self.source)
        if self.license:
            parts.append(f"({self.license})")
        return " ".join(parts)


def license_id(value) -> str | None:
    """A license as written, made the SPDX id the gate knows (CC BY 4.0 → CC-BY-4.0)."""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    return _LICENSE_WORDS.get(v.lower().replace("_", " "), v)


def license_problem(asset: Asset, allowed=ALLOWED_LICENSES) -> str | None:
    """Why a 素材 may not be used (None: it may)."""
    if asset.license is None or asset.license in allowed:
        return None
    return f"素材「{asset.name}」のライセンス {asset.license} は、無料で商用にも使えるものの一覧にありません（使いません）"


def _in_folder(value) -> str | None:
    if not isinstance(value, str):
        return None
    parts = value.replace("\\", "/").removeprefix("./").split("/")
    if not parts or any(not p or p in (".", "..") or ":" in p for p in parts):
        return None
    return "/".join(parts)


def allowed_licenses(folder: str | Path) -> frozenset:
    """The licenses the gate lets in: ALLOWED_LICENSES and the folder's own allowLicenses."""
    try:
        data = json.loads((Path(folder) / ASSETS_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ALLOWED_LICENSES
    extra = data.get("allowLicenses") if isinstance(data, dict) else None
    return ALLOWED_LICENSES | {license_id(v) for v in extra or [] if license_id(v)}


def read_assets(folder: str | Path, usable_only: bool = True) -> tuple[list[Asset], list[str]]:
    """The 素材 the folder lists, and what could not be read. `usable_only`: without those whose license is not allowed."""
    path = Path(folder) / ASSETS_FILE
    if not path.exists():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        return [], [f"{ASSETS_FILE} を読めません: {error}"]
    allowed = allowed_licenses(folder)
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
            kind=item.get("kind") if item.get("kind") in KINDS else "thing",
            file=file,
            collection=item.get("collection") or None,
            note=item.get("note") or None,
            picture=_in_folder(item.get("picture")),
            by=item.get("by") or None,
            license=license_id(item.get("license")),
            source=item.get("source") or None,
            author=item.get("author") or None,
            attribution=item.get("attribution") or None,
        )
    out = list(named.values())
    if usable_only:
        for asset in out:
            problem = license_problem(asset, allowed)
            if problem:
                problems.append(problem)
        out = [a for a in out if not license_problem(a, allowed)]
    return out, problems


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
