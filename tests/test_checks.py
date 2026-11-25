# SPDX-License-Identifier: GPL-3.0-or-later
"""要求の点検: findings and questions for what an instruction leaves open or contradicts."""

import copy
import json
from pathlib import Path

from name_blockout.checks import check_instruction, pick_questions

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "two-point" / "指示.json"


def example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def codes(data):
    return {f["code"] for f in check_instruction(data)}


def test_example_is_clean():
    assert codes(example()) == set()


def test_points_and_vanishing_disagree():
    data = example()
    data["shots"][0]["ruler"]["points"] = 3
    assert "ruler.count" in codes(data)


def test_vanishing_point_off_the_eye_level():
    data = example()
    data["shots"][0]["ruler"]["vanishingMm"][0][1] += 5
    assert "ruler.off-horizon" in codes(data)


def test_low_word_against_a_high_eye_level():
    data = example()
    shot = data["shots"][0]
    shot["intent"]["camera"] = "low"
    shot["ruler"]["horizonMm"] = [[20, 30], [237, 30]]
    shot["ruler"]["vanishingMm"] = [[-60, 30], [330, 30]]
    assert "camera.word-low" in codes(data)


def test_missing_height_asks_with_choices():
    data = example()
    del data["shots"][0]["camera"]
    findings = check_instruction(data)
    q = pick_questions(findings, 2)
    assert q and q[0]["path"] == "camera.heightM"
    labels = [o["label"] for o in q[0]["options"]]
    assert any("人物" in label for label in labels)  # the figure gives a height


def test_figure_disagrees_with_camera_height():
    data = example()
    data["shots"][0]["camera"]["heightM"] = 4.0
    assert "figure.height" in codes(data)


def test_hint_mismatch_is_an_error():
    data = example()
    data["shots"][0]["camera"]["hint"] = {
        "mode": "level",
        "points": 2,
        "lensMm": 31.5,
        "shiftX": 0.0,
        "shiftY": 0.2,
        "tiltDeg": 0,
        "rollDeg": 0,
    }
    found = [f for f in check_instruction(data) if f["code"] == "camera.hint"]
    assert [f["path"] for f in found] == ["camera.hint.shiftY"] and found[0]["level"] == "error"


def test_thing_above_the_eye_level_asks_if_it_floats():
    data = example()
    data["shots"][0]["objects"][1]["shapeMm"] = [[160, 40], [215, 40], [215, 70], [160, 70]]
    found = [f for f in check_instruction(data) if f["code"] == "object.above-horizon"]
    assert found and found[0]["question"]["options"][0]["set"] == {"objects/o2/onGround": False}


def test_develop_needs_a_time_of_day():
    data = example()
    data["shots"][0]["stage"] = "develop"
    assert {"look.time", "look.weather"} <= codes(data)


def test_same_place_next_panels_disagree_on_time():
    data = example()
    a = data["shots"][0]
    a["place"] = {"asset": "教室"}
    a["look"] = {"timeOfDay": "noon"}
    b = copy.deepcopy(a)
    b.update(id="panel2", label="p1 コマ2", order=2, look={"timeOfDay": "night"})
    data["shots"].append(b)
    assert "sequence.timeOfDay" in codes(data)


def test_questions_skip_what_was_answered():
    data = example()
    del data["shots"][0]["camera"]
    findings = check_instruction(data)
    assert pick_questions(findings, 2, answered={"panel1:camera.heightM"}) == []


def with_assets(tmp_path, data, assets):
    folder = tmp_path / "素材"
    folder.mkdir()
    (folder / "素材.json").write_text(json.dumps({"assets": assets}, ensure_ascii=False), encoding="utf-8")
    data["folders"] = {"assets": str(folder)}
    return folder


def test_asset_license_not_allowed_is_told(tmp_path):
    data = example()
    with_assets(tmp_path, data, [{"name": "倉庫", "file": "w.blend", "license": "CC-BY-NC-4.0"}, {"name": "小屋", "file": "h.blend"}])
    found = {f["code"]: f for f in check_instruction(data)}
    assert "asset.license" in found and "CC-BY-NC-4.0" in found["asset.license"]["message"]
    assert "object.asset" not in found  # not "missing": named, but not used
    assert found["asset.license-unknown"]["path"] == "objects/1/asset"


def test_panorama_checks(tmp_path):
    data = example()
    folder = with_assets(tmp_path, data, [{"name": "空", "kind": "panorama", "file": "sky.hdr", "license": "CC0-1.0"}])
    (folder / "sky.hdr").write_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 512 +X 1024\n")
    data["shots"][0]["far"] = [{"kind": "panorama", "asset": "空"}]
    found = {f["code"]: f for f in check_instruction(data)}
    assert found["far.resolution"]["level"] == "warn" and "1024px" in found["far.resolution"]["message"]
    data["shots"][0]["far"] = [{"kind": "panorama", "asset": "ない"}]
    found = {f["code"]: f for f in check_instruction(data)}
    assert found["far.asset"]["question"]["options"][0]["set"] == {"far/0/asset": "空"}


DEVELOP = Path(__file__).resolve().parents[1] / "examples" / "develop" / "指示.json"


def test_develop_example_is_clean():
    data = json.loads(DEVELOP.read_text(encoding="utf-8"))
    assert {f["code"] for f in check_instruction(data) if f["level"] != "info"} == set()


def test_develop_asks_for_the_light():
    data = json.loads(DEVELOP.read_text(encoding="utf-8"))
    look = data["shots"][0]["look"]
    for key in ("location", "date", "north", "materials"):
        look.pop(key)
    found = {f["code"]: f for f in check_instruction(data)}
    assert {"look.location", "look.date", "look.north", "look.materials"} <= set(found)
    assert found["look.materials"]["question"]["options"][0]["set"] == {"look.materials/o1": "トタン"}
    sides = [o["label"] for o in found["look.north"]["question"]["options"]]
    assert sides and all(label.startswith("日差しを") for label in sides)


def test_develop_light_against_the_key():
    data = json.loads(DEVELOP.read_text(encoding="utf-8"))
    look = data["shots"][0]["look"]
    look["light"] = {"key": "back"}
    found = {f["code"]: f for f in check_instruction(data)}
    assert found["look.key"]["level"] == "warn"
    north = found["look.key"]["question"]["options"][0]["set"]["look.north"]
    look["north"] = north
    assert "look.key" not in {f["code"] for f in check_instruction(data)}
    look["materials"].append({"target": "o2", "material": "ないもの"})
    assert "look.material-unknown" in {f["code"] for f in check_instruction(data)}


def test_develop_indoors_from_the_words():
    """A sofa puts the shot indoors (asked once); indoors the sun's questions are not asked, the light's is."""
    data = json.loads(DEVELOP.read_text(encoding="utf-8"))
    shot = data["shots"][0]
    shot["objects"][0]["label"] = "ソファ"
    shot["look"].pop("north")
    found = {f["code"]: f for f in check_instruction(data)}
    assert found["look.setting"]["question"]["options"][0]["set"] == {"look.setting": "indoor"}
    assert found["look.indoor-key"]["question"]["options"][0]["set"] == {"look.light.key": "interior"}
    assert not {"look.north", "look.key", "look.location", "look.date"} & set(found)
    shot["look"]["setting"] = "outdoor"
    found = {f["code"] for f in check_instruction(data)}
    assert "look.setting" not in found and "look.indoor-key" not in found and "look.north" in found


def test_answered_questions_are_not_asked_again(tmp_path):
    """An app that asked the author lists what was answered (requirement.answered); check asks the next one."""
    import subprocess
    import sys

    data = example()
    shot = data["shots"][0]
    del shot["camera"]
    first = pick_questions(check_instruction(data), 1)
    assert first
    shot["requirement"] = {"answered": [first[0]["path"]]}
    path = tmp_path / "指示.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "name_blockout", "check", str(path), "--json", "--questions", "5"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    asked = {q["path"] for q in json.loads(out.stdout)["questions"]}
    assert first[0]["path"] not in asked
