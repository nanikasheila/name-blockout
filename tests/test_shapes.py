# SPDX-License-Identifier: GPL-3.0-or-later
"""Detailed shapes the development makes for things without a 素材: found by the words of their names, inside
their boxes, and the author's own parts."""

import json
from pathlib import Path

import pytest

from name_blockout.plan import build_develop_plan, build_plan
from name_blockout.shapes import BUILDERS, KINDS, bounds, kind_of, shape_of

ROOT = Path(__file__).resolve().parents[1]
SIZES = {"house": (9, 7, 7.5), "building": (14, 10, 18), "van": (4.7, 1.7, 2.0), "chair": (0.45, 0.5, 0.85), "tree": (4, 4, 7)}


def test_kinds_by_words():
    assert kind_of({"label": "叔母の家"}) == "house"
    assert kind_of({"label": "黒いバン"}) == "van"
    assert kind_of({"label": "本棚"}) == "shelf"  # 本棚 over 棚
    assert kind_of({"label": "木造の壁"}) is None  # 木造 is not a tree
    assert kind_of({"label": "なにか", "shape": "car"}) == "car"
    assert kind_of({"label": "宇宙船"}) is None


@pytest.mark.parametrize("kind", sorted(BUILDERS))
def test_every_kind_stays_about_its_box(kind):
    w, d, h = SIZES.get(kind, (2.0, 1.0, 1.6))
    parts, how = shape_of({"shape": kind, "id": "o1"}, (w, d, h))
    assert how == kind and len(parts) >= 3
    lo, hi = bounds(parts)
    # Eaves, mirrors and handrails may stand out a little; nothing goes far outside, nothing under the ground.
    margin = 0.25 * max(w, d) + 0.2
    assert lo[0] > -w / 2 - margin and hi[0] < w / 2 + margin
    assert lo[1] > -d / 2 - margin and hi[1] < d / 2 + margin
    assert lo[2] >= -1e-3 and hi[2] < h * 1.15 + 1.2
    for p in parts:
        assert p["shape"] in ("box", "cylinder", "sphere", "prism") and all(v > 0 for v in p["s"]) and p["name"]


def test_every_kind_has_words_and_a_label():
    from name_blockout.shapes import KIND_LABELS

    assert set(KINDS) == set(BUILDERS) == set(KIND_LABELS)


def test_a_house_has_a_roof_windows_and_a_door():
    parts, _ = shape_of({"label": "家"}, (9, 7, 7.5))
    names = {p["name"] for p in parts}
    assert {"屋根", "窓ガラス", "ドア", "基礎"} <= names
    assert any(p["shape"] == "prism" for p in parts)


def test_a_van_seen_front_on_turns_its_length_away():
    parts, _ = shape_of({"label": "バン"}, (1.7, 4.7, 2.0))
    wheels = [p for p in parts if p["name"] == "タイヤ"]
    assert len(wheels) == 4 and all(p["axis"] == "X" for p in wheels)
    assert len({round(p["c"][1], 2) for p in wheels}) == 2  # front and rear axles along Y


def test_the_authors_own_parts_in_fractions_of_the_box():
    shape = {
        "unit": "box",
        "parts": [
            {"name": "台", "c": [0.5, 0.5, 0.0], "s": [1, 1, 0.2]},
            {"name": "柱", "shape": "cylinder", "axis": "Z", "c": [0.5, 0.5, 0.6], "s": [0.1, 0.1, 0.8], "material": "金属"},
        ],
    }
    parts, how = shape_of({"label": "宇宙船", "shape": shape}, (4, 2, 3))
    assert how == "own"
    assert parts[0]["c"] == [0.0, 0.0, 0.0] and parts[0]["s"] == pytest.approx([4, 2, 0.6])
    assert parts[1]["c"][2] == pytest.approx(1.8) and parts[1]["material"] == "金属"


def test_development_gives_shapes_and_far_layers():
    path = ROOT / "examples" / "develop" / "指示.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    shot = data["shots"][0]
    plan = build_develop_plan(data, shot, path)
    assert all(o.get("parts") for o in plan["objects"])
    assert any(n.startswith("形を作った: ") for n in plan["notes"])
    # Outdoors without far layers: a skyline (sheds are a town's) and mountains, noted as the tool's.
    assert [layer["kind"] for layer in plan["far"]] == ["skyline", "mountains", "mountains"]
    assert any(a["path"] == "far" for a in plan["assumptions"])
    # The design is the author's: the hashes do not take the far layers the tool added.
    assert plan["hashes"] == build_plan(data, shot, path)["hashes"]
    # The Blockout keeps its boxes.
    assert not any(o.get("parts") for o in build_plan(data, shot, path)["objects"])


def test_unknown_things_are_noted():
    path = ROOT / "examples" / "develop" / "指示.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    shot = data["shots"][0]
    shot["objects"][0]["label"] = "宇宙船"
    plan = build_develop_plan(data, shot, path)
    assert any(n.startswith("形のひな形がない物: 宇宙船") for n in plan["notes"])
