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
