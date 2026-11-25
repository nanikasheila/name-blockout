# SPDX-License-Identifier: GPL-3.0-or-later
"""Which phase a change to a shot's requirement redoes.

The fields of a shot fall in three groups (docs/instruction-format.md):

- design: what the camera and the layout come from (the frame, the ruler,
  the camera, the place, things, figures, the words describing what shows).
  A change redoes the Blockout and everything after it.
- develop: how it is finished (the look: time of day, weather, light,
  materials; how it is drawn out). A change redoes the development only.
- none: what only people read (the label, notes, dialogue) or bookkeeping.

A hash of each group is kept with what was built, so the next request
redoes only what changed, and things that did not change are not rebuilt.
"""

from __future__ import annotations

import hashlib
import json

DESIGN_FIELDS = ("frame", "ruler", "camera", "place", "objects", "figures")
DESIGN_INTENT = ("none", "brief", "camera")
DEVELOP_FIELDS = ("look", "render", "stage")


def _canon(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()[:16]


def design_part(shot: dict) -> dict:
    part = {key: shot.get(key) for key in DESIGN_FIELDS if shot.get(key) is not None}
    camera = dict(part.get("camera") or {})
    camera.pop("hint", None)  # the name tool's own working: not a requirement
    if camera:
        part["camera"] = camera
    else:
        part.pop("camera", None)
    intent = {key: (shot.get("intent") or {}).get(key) for key in DESIGN_INTENT if (shot.get("intent") or {}).get(key) is not None}
    if intent:
        part["intent"] = intent
    return part


def develop_part(shot: dict) -> dict:
    return {key: shot.get(key) for key in DEVELOP_FIELDS if shot.get(key) is not None}


def hashes(shot: dict) -> dict:
    return {"design": _digest(design_part(shot)), "develop": _digest(develop_part(shot))}


def object_hashes(shot: dict) -> dict:
    """Each thing and figure on its own: those unchanged keep what was built for them."""
    out = {}
    for obj in shot.get("objects") or []:
        out[obj["id"]] = _digest(obj)
    for fig in shot.get("figures") or []:
        out[fig["id"]] = _digest(fig)
    return out


def redo_scope(before: dict | None, after: dict) -> dict:
    """What to redo going from the shot `before` (as last built; None: never built) to `after`.

    {"redo": "design" | "develop" | "none", "changed": [fields], "objects": {"changed": [...], "kept": [...], "removed": [...]}}
    """
    if before is None:
        return {
            "redo": "design",
            "changed": ["(初めて)"],
            "objects": {"changed": [o for o in object_hashes(after)], "kept": [], "removed": []},
        }
    changed = []
    db, da = design_part(before), design_part(after)
    for key in sorted(set(db) | set(da)):
        if _canon(db.get(key)) != _canon(da.get(key)):
            changed.append(key)
    design = bool(changed)
    vb, va = develop_part(before), develop_part(after)
    for key in sorted(set(vb) | set(va)):
        if _canon(vb.get(key)) != _canon(va.get(key)):
            changed.append(key)
    hb, ha = object_hashes(before), object_hashes(after)
    objects = {
        "changed": [k for k in ha if hb.get(k) != ha[k]],
        "kept": [k for k in ha if hb.get(k) == ha[k]],
        "removed": [k for k in hb if k not in ha],
    }
    redo = "design" if design else ("develop" if changed else "none")
    return {"redo": redo, "changed": changed, "objects": objects}
