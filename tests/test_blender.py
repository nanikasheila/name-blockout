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


@needs_blender
def test_develop_example(tmp_path):
    """The development: the same layout, lit by the afternoon sun; shadows fall away from it, tones by material."""
    import bpy

    from name_blockout.pipeline import run_blockout

    shutil.copy(ROOT / "examples" / "develop" / "指示.json", tmp_path / "指示.json")
    reports = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None, develop=True)
    r = reports[0]
    check = json.loads(Path(r["check"]).read_text(encoding="utf-8"))
    light = next(c for c in check["checks"] if c["name"] == "影の向き")
    assert r["pass"] and light["pass"] and light["tested"] >= 2, light
    assert light["faces"]["shadow"][1] >= 20 and light["faces"]["sunny"][1] >= 20, light
    # The check sees a wrong light: the shadows the other way round fail it (the scene is still the one built).
    from name_blockout.blender.develop import shadow_check

    plan = json.loads((tmp_path / "blockout" / "panel1" / "1" / "plan.json").read_text(encoding="utf-8"))
    mask = bpy.data.images.load(str(tmp_path / "案" / "panel1" / "1" / "影.png"))
    fw, fh = mask.size
    shown = [a > 0.1 for a in mask.pixels[3::4]]
    import numpy as np

    shadow = np.array(shown, dtype=bool).reshape(fh, fw)[::-1]
    assert shadow_check(plan, None, shadow, None, sun=True)["pass"]
    assert not shadow_check(plan, None, ~shadow, None, sun=True)["pass"]
    assert set(r["files"]) == {"完成", "線画", "トーン", "影"}
    assert r["note"].startswith("開発（光と材質、name-blockout）: 午後・晴れ・日差しは")
    shade = bpy.data.images.load(str(tmp_path / "案" / "panel1" / "1" / "影.png"))
    alpha = shade.pixels[3::4]
    assert 0.02 < sum(1 for a in alpha if a > 0.1) / len(alpha) < 0.6
    built = json.loads((tmp_path / "blockout" / "panel1" / "1" / "built.json").read_text(encoding="utf-8"))
    assert built["mode"] == "develop"
    # A Blockout of the same shot does not count as the development's last build.
    again = run_blockout(tmp_path / "指示.json", preview_dpi=60, only_changed=True, log=lambda *_: None, develop=True)
    assert again[0]["status"] == "unchanged"


@needs_blender
def test_develop_indoors_and_beta(tmp_path):
    """A sofa indoors under a window, painted black: lit from the window, its lines drawn white over the ベタ."""
    import bpy
    import numpy as np

    from name_blockout.pipeline import run_blockout

    data = json.loads((ROOT / "examples" / "develop" / "指示.json").read_text(encoding="utf-8"))
    shot = data["shots"][0]
    shot["objects"][0]["label"] = "ソファ"
    shot["look"] = {"timeOfDay": "evening", "light": {"key": "window"}, "materials": [{"target": "o1", "material": "黒い塗装"}]}
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None, develop=True)[0]
    assert r["pass"], r["note"]
    assert "屋内・夕方・明かりは窓から" in r["note"] and "look.materials/ground=木" in r["note"]

    def load(name):
        image = bpy.data.images.load(str(tmp_path / "案" / "panel1" / "1" / f"{name}.png"))
        w, h = image.size
        return np.array(image.pixels[:], dtype=np.float32).reshape(h, w, 4)

    tone, done, lines = load("トーン"), load("完成"), load("線画")
    beta = (tone[..., 3] > 0.5) & (tone[..., :3].max(axis=-1) < 0.05)
    assert beta.sum() > 1000
    drawn = beta & (lines[..., 3] > 0.5)
    assert drawn.sum() > 10 and (done[drawn][:, 0] > 0.5).mean() > 0.8


@needs_blender
def test_develop_under_a_ceiling_light(tmp_path):
    """Indoors under the room's light (nearly overhead, soft): the ground beside things is not checked, the faces are."""
    from name_blockout.pipeline import run_blockout

    data = json.loads((ROOT / "examples" / "develop" / "指示.json").read_text(encoding="utf-8"))
    shot = data["shots"][0]
    shot["objects"][0]["label"] = "ソファ"
    shot["look"] = {"setting": "indoor", "timeOfDay": "evening", "light": {"key": "interior"}}
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None, develop=True)[0]
    check = json.loads(Path(r["check"]).read_text(encoding="utf-8"))
    light = next(c for c in check["checks"] if c["name"] == "影の向き")
    assert r["pass"] and light["pass"], light
    assert light["shadowSide"][1] == 0 and light["sunnySide"][1] == 0 and light["faces"]["sunny"][1] >= 20, light
    assert "天井の明かり" in r["note"]


@needs_blender
def test_develop_a_room_with_a_window(tmp_path):
    """Indoors: the room's walls, ceiling and window drawn round the things, lit through the window; the check passes
    (the walls cast no shadow, and the check looks through them the same way)."""
    import bpy
    import numpy as np

    from name_blockout.pipeline import run_blockout

    shutil.copy(ROOT / "examples" / "indoor" / "指示.json", tmp_path / "指示.json")
    r = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None, develop=True)[0]
    check = json.loads(Path(r["check"]).read_text(encoding="utf-8"))
    light = next(c for c in check["checks"] if c["name"] == "影の向き")
    assert r["pass"] and light["pass"], r["note"]
    assert light["faces"]["shadow"][1] >= 50 and light["faces"]["sunny"][1] >= 50, light
    assert "明かりは窓から" in r["note"] and "room.windows" in r["note"]
    image = bpy.data.images.load(str(tmp_path / "案" / "panel1" / "1" / "線画.png"))
    w, h = image.size
    lines = np.array(image.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1]
    # The ceiling's corners are drawn high in the picture (above everything standing in the room).
    assert (lines[: h * 3 // 10, :, 3] > 0.5).sum() > w // 2
