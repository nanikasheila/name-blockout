# SPDX-License-Identifier: GPL-3.0-or-later
"""What a change redoes, and the requirement's versions beside the instruction."""

import copy
import json
from pathlib import Path

from name_blockout.requirement import answer, confirm, effective, read_requirement
from name_blockout.scope import redo_scope

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "two-point" / "指示.json"


def shot():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))["shots"][0]


def test_first_build_is_design():
    assert redo_scope(None, shot())["redo"] == "design"


def test_light_only_redoes_development():
    a = shot()
    b = copy.deepcopy(a)
    b["look"] = {"timeOfDay": "evening"}
    scope = redo_scope(a, b)
    assert scope["redo"] == "develop" and scope["changed"] == ["look"]
    assert scope["objects"]["changed"] == []


def test_moving_a_thing_redoes_design_and_keeps_the_others():
    a = shot()
    b = copy.deepcopy(a)
    b["objects"][1]["shapeMm"][0][0] += 3
    scope = redo_scope(a, b)
    assert scope["redo"] == "design"
    assert scope["objects"]["changed"] == ["o2"] and set(scope["objects"]["kept"]) == {"o1", "f1"}


def test_notes_and_hint_redo_nothing():
    a = shot()
    b = copy.deepcopy(a)
    b["label"] = "別の名前"
    b.setdefault("intent", {})["memo"] = "演出メモ"
    b["camera"]["hint"] = {"lensMm": 30}
    assert redo_scope(a, b)["redo"] == "none"


def test_answers_fill_only_what_is_open(tmp_path):
    s = shot()
    del s["camera"]
    answer(tmp_path, s, {"camera.heightM": 1.2, "objects/o2/onGround": False})
    version = read_requirement(tmp_path, s["id"])["versions"][-1]
    assert version["state"] == "draft" and version["version"] == 1
    got, replaced = effective(s, version["answers"])
    assert got["camera"]["heightM"] == 1.2 and got["objects"][1]["onGround"] is False and replaced == []
    s2 = copy.deepcopy(s)
    s2["camera"] = {"heightM": 1.6}  # the author set it in the name tool afterwards
    got, replaced = effective(s2, version["answers"])
    assert got["camera"]["heightM"] == 1.6 and replaced == ["camera.heightM"]


def test_confirm_versions(tmp_path):
    s = shot()
    first = confirm(tmp_path, s)
    assert first["version"] == 1 and first["state"] == "confirmed"
    assert confirm(tmp_path, s)["version"] == 1  # nothing changed
    answer(tmp_path, s, {"look.timeOfDay": "evening"})
    second = confirm(tmp_path, s)
    assert second["version"] == 2 and second["hashes"]["develop"] != first["hashes"]["develop"]
    assert second["hashes"]["design"] == first["hashes"]["design"]
