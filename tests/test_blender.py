# SPDX-License-Identifier: GPL-3.0-or-later
"""End to end in Blender (bpy): build, measure independently, draw out, hand to name-studio."""

import json
import shutil
from pathlib import Path

from conftest import needs_blender, shot_from_camera, true_camera

ROOT = Path(__file__).resolve().parents[1]


@needs_blender
def test_two_point_example(tmp_path):
    from name_blockout.pipeline import run_blockout

    shutil.copy(ROOT / "examples" / "two-point" / "指示.json", tmp_path / "指示.json")
    reports = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None)
    assert [r["status"] for r in reports] == ["built"]
    r = reports[0]
    assert r["pass"], json.loads(Path(r["check"]).read_text(encoding="utf-8"))
    for name in ("完成", "線画", "トーン"):
        assert (tmp_path / "案" / "panel1" / "1" / f"{name}.png").exists()
    manifest = json.loads((tmp_path / "依頼" / "example-2pt" / "背景.json").read_text(encoding="utf-8"))
    assert manifest["takes"][0]["panel"] == "panel1" and manifest["takes"][0]["files"]["完成"] == "案/panel1/1/完成.png"
    # Again: a new take, and --only-changed builds nothing when nothing changed.
    again = run_blockout(tmp_path / "指示.json", preview_dpi=60, only_changed=True, log=lambda *_: None)
    assert again[0]["status"] == "unchanged"


@needs_blender
def test_rolled_three_point_camera_checks_out(tmp_path):
    from name_blockout.instruction import frame_of
    from name_blockout.pipeline import run_blockout

    box = (10.0, 20.0, 210.0, 120.0)
    f = frame_of({"boxMm": list(box), "dpi": 100.0})
    truth = true_camera(f.width, f.height, 650.0, 35.0, 30.0, 6.0, (f.width / 2 + 30, f.height / 2 - 20))
    shot = shot_from_camera(truth, 3, box, 100.0)
    data = {"format": "name-blockout/instruction", "formatVersion": 1, "shots": [shot]}
    (tmp_path / "指示.json").write_text(json.dumps(data), encoding="utf-8")
    reports = run_blockout(tmp_path / "指示.json", preview_dpi=60, render=False, log=lambda *_: None)
    check = json.loads(Path(reports[0]["check"]).read_text(encoding="utf-8"))
    assert check["pass"], check
    assert any("縦" in c["name"] or "-Z" in c["name"] or "+Z" in c["name"] for c in check["checks"])


@needs_blender
def test_far_layers_and_panorama(tmp_path):
    """遠景.png carries the panorama, its horizon on the camera's; the take lists 遠景 and the credits."""
    import bpy

    from name_blockout.pipeline import run_blockout

    data = json.loads((ROOT / "examples" / "far" / "指示.json").read_text(encoding="utf-8"))
    assets = tmp_path / "素材"
    assets.mkdir()
    # A synthetic 360° sky: light above its middle row (the horizon), dark below.
    w, h = 256, 128
    img = bpy.data.images.new("sky", w, h, float_buffer=True)
    pixels = []
    for y in range(h):  # Blender's rows go bottom up
        v = 0.15 if y < h // 2 else 1.0
        pixels += [v, v, v, 1.0] * w
    img.pixels = pixels
    img.filepath_raw = str(assets / "sky.hdr")
    img.file_format = "HDR"
    img.save()
    (assets / "素材.json").write_text(
        json.dumps({"assets": [{"name": "空", "kind": "panorama", "file": "sky.hdr", "license": "CC0-1.0"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    data["folders"] = {"assets": "素材"}
    data["shots"][0]["far"] = [{"kind": "panorama", "asset": "空"}]
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    reports = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None)
    r = reports[0]
    assert r["pass"] and set(r["files"]) == {"完成", "線画", "トーン", "遠景"}
    plan = json.loads((tmp_path / "blockout" / "panel1" / "1" / "plan.json").read_text(encoding="utf-8"))
    far = bpy.data.images.load(str(tmp_path / "案" / "panel1" / "1" / "遠景.png"))
    fw, fh = far.size
    px = far.pixels[:]

    def grey(x, y_from_top):
        i = ((fh - 1 - y_from_top) * fw + x) * 4
        return px[i], px[i + 3]

    horizon = plan["targets"]["horizonPx"][0] * fh / plan["frame"]["sizePx"][1]
    # The sky image is coarse (256 px round), so look a little away from the horizon.
    above, alpha = grey(2, int(horizon) - 15)
    below, _ = grey(2, int(horizon) + 15)
    assert alpha == 1.0 and above > below + 0.1, (above, below)
    edge = next(y for y in range(fh) if grey(2, y)[0] < (above + below) / 2)
    assert abs(edge - horizon) < 6, (edge, horizon)
    assert (tmp_path / "blockout" / "panel1" / "1" / "credits.json").exists()
