# SPDX-License-Identifier: GPL-3.0-or-later
"""Distance bands and the far layers: the same seed gives the same layer, made only where the picture looks."""

import json
import math
import shutil
from pathlib import Path

from name_blockout.camera import fit_camera
from name_blockout.far import (
    FAR_M,
    NEAR_M,
    band_of,
    far_layers,
    mountains,
    panorama_width_needed,
    parallax_free_m,
    skyline,
    view_azimuths,
)
from name_blockout.instruction import read_instruction
from name_blockout.plan import build_plan

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "far" / "指示.json"


def example():
    data = read_instruction(EXAMPLE)
    return data, data["shots"][0]


def test_bands():
    assert band_of(NEAR_M) == "near" and band_of(NEAR_M + 1) == "middle"
    assert band_of(FAR_M) == "middle" and band_of(FAR_M + 1) == "far"


def test_view_azimuths_cover_the_picture():
    _, shot = example()
    cam = fit_camera(shot)
    lo, hi = view_azimuths(cam, margin_deg=0.0)
    for x in (0, cam.width / 2, cam.width):
        d = cam.ray((x, cam.height / 2))
        a = math.degrees(math.atan2(d[1], d[0]))
        while a < lo:
            a += 360
        assert lo <= a <= hi


def test_same_seed_same_layer():
    _, shot = example()
    cam = fit_camera(shot)
    span = view_azimuths(cam)
    assert skyline(cam, {"seed": 4}, span) == skyline(cam, {"seed": 4}, span)
    assert skyline(cam, {"seed": 4}, span) != skyline(cam, {"seed": 5}, span)
    ridge = mountains(cam, {"seed": 1, "heightM": [100, 300]}, span)["ridge"]
    assert all(100 <= p[2] <= 300 for p in ridge)
    # Each piece of the skyline is about as far as asked.
    for box in skyline(cam, {"seed": 4, "distanceM": 500}, span)["boxes"]:
        d = math.hypot(box["centreM"][0] - cam.position[0], box["centreM"][1] - cam.position[1])
        assert 400 < d < 700


def test_plan_bands_and_far_layers():
    data, shot = example()
    p = build_plan(data, shot, EXAMPLE)
    bands = {o["id"]: o["band"] for o in p["objects"]}
    assert bands == {"o1": "near", "o2": "middle"}
    assert [layer["kind"] for layer in p["far"]] == ["mountains", "skyline", "trees"]
    assert "遠景" in p["render"]["passes"]
    # The far layers do not stretch the ground grid.
    assert p["ground"]["rings"][-1]["extentM"] < 900


def test_band_given_against_where_it_stands_is_noted():
    data, shot = example()
    shot = json.loads(json.dumps(shot))
    shot["objects"][1]["band"] = "near"
    shot["objects"][1]["sizeM"] = [20, 30, 8]
    p = build_plan(data, shot, EXAMPLE)
    assert p["objects"][1]["band"] == "near"


def test_panorama_from_assets(tmp_path):
    shutil.copy(EXAMPLE, tmp_path / "指示.json")
    data = json.loads((tmp_path / "指示.json").read_text(encoding="utf-8"))
    data["folders"] = {"assets": "素材"}
    data["shots"][0]["far"] = [{"kind": "panorama", "asset": "空", "turnDeg": 30}]
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assets = tmp_path / "素材"
    assets.mkdir()
    # A Radiance header 2048 wide: too small for the preview of this lens.
    (assets / "sky.hdr").write_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1024 +X 2048\n")
    entry = {"name": "空", "kind": "panorama", "file": "sky.hdr", "license": "CC0", "source": "https://example.org/sky"}
    (assets / "素材.json").write_text(json.dumps({"assets": [entry]}, ensure_ascii=False), encoding="utf-8")
    data = read_instruction(tmp_path / "指示.json")
    p = build_plan(data, data["shots"][0], tmp_path / "指示.json")
    layer = p["far"][0]
    assert layer["kind"] == "panorama" and layer["turnDeg"] == 30 and layer["file"].endswith("sky.hdr")
    assert any("全天球の画像「空」は幅 2048px" in n for n in p["notes"])
    assert p["credits"] == [{"name": "空", "license": "CC0-1.0", "source": "https://example.org/sky", "needsCredit": False}]


def test_missing_panorama_is_left_out():
    data, shot = example()
    shot = {**shot, "far": [{"kind": "panorama", "asset": "ない"}]}
    p = build_plan(data, shot, EXAMPLE)
    assert p["far"] == [] and any("ない" in n for n in p["notes"])


def test_sizes_for_the_far():
    _, shot = example()
    cam = fit_camera(shot)
    assert parallax_free_m(cam) == cam.focal_px
    assert panorama_width_needed(1000.0) == 6284
    layers, _ = far_layers(cam, [{"kind": "trees", "seed": 2}])
    assert layers[0]["trees"] and all(t["heightM"] >= 6 for t in layers[0]["trees"])
