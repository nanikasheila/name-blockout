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
    # Outdoors without far layers asked for, the development adds them (and draws 遠景 on its own).
    assert set(r["files"]) == {"完成", "線画", "トーン", "影", "遠景"}
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
    assert "屋内・夕方・明かりは窓から" in r["note"] and "look.materials/ground=白地" in r["note"]

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
    # The take's note says the room and where its light comes in, as the plan does.
    assert "。部屋 " in r["note"] and "窓の光は" in r["note"], r["note"]
    image = bpy.data.images.load(str(tmp_path / "案" / "panel1" / "1" / "線画.png"))
    w, h = image.size
    lines = np.array(image.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1]
    # The ceiling's corners are drawn high in the picture (above everything standing in the room).
    assert (lines[: h * 3 // 10, :, 3] > 0.5).sum() > w // 2


def _chair_blend(folder: Path) -> None:
    """A 素材 made here: a chair (seat, back, four legs) in a collection 椅子, its front toward −Y."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    coll = bpy.data.collections.new("椅子")
    bpy.context.scene.collection.children.link(coll)
    parts = {
        "座面": ((0, 0, 0.45), (0.45, 0.45, 0.05)),
        "背もたれ": ((0, 0.2, 0.75), (0.45, 0.05, 0.55)),
        **{f"脚{i}": ((x, y, 0.21), (0.04, 0.04, 0.42)) for i, (x, y) in enumerate(((-0.2, -0.2), (0.2, -0.2), (-0.2, 0.2), (0.2, 0.2)))},
    }
    for name, (centre, size) in parts.items():
        mesh = bpy.data.meshes.new(name)
        hx, hy, hz = (v / 2 for v in size)
        verts = [(centre[0] + sx * hx, centre[1] + sy * hy, centre[2] + sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        mesh.from_pydata(verts, [], faces)
        coll.objects.link(bpy.data.objects.new(name, mesh))
    folder.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "chair.blend"))
    (folder / "素材.json").write_text(
        json.dumps({"assets": [{"name": "椅子", "kind": "thing", "file": "chair.blend", "license": "own"}]}, ensure_ascii=False),
        encoding="utf-8",
    )


@needs_blender
def test_develop_draws_a_thing_as_its_asset(tmp_path):
    """A thing with a 素材: the Blockout keeps its box, the development puts the 素材 in its place (turned to the
    camera, fitted in the box), with a part given its own material; the checks still pass."""
    import bpy
    from mathutils import Vector

    from name_blockout.pipeline import run_blockout

    _chair_blend(tmp_path / "素材")
    data = json.loads((ROOT / "examples" / "indoor" / "指示.json").read_text(encoding="utf-8"))
    data["folders"] = {"assets": "素材"}
    shot = data["shots"][0]
    shot["objects"][1]["label"] = "椅子"
    shot["objects"][1]["sizeM"] = [0.6, 0.6, 1.0]
    shot["look"]["materials"].append({"target": "座面", "material": "黒い塗装"})
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    blockout = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None)[0]
    assert blockout["pass"], blockout["note"]
    bpy.ops.wm.open_mainfile(filepath=str(tmp_path / "blockout" / "panel1" / "1" / "scene.blend"))
    assert "NB_obj_o2" in bpy.data.objects and "NB_thing_o2" not in bpy.data.objects

    r = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None, develop=True)[0]
    assert r["pass"], r["note"]
    plan = json.loads((tmp_path / "blockout" / "panel1" / "2" / "plan.json").read_text(encoding="utf-8"))
    assert "素材に差し替え: 椅子（椅子）" in plan["notes"]
    assert "素材に差し替え: 椅子（椅子）" in r["note"]
    bpy.ops.wm.open_mainfile(filepath=str(tmp_path / "blockout" / "panel1" / "2" / "scene.blend"))
    # Things without a 素材 get the tool's detailed shapes: the sofa its cushions, the shelf its books.
    sofa = [o for o in bpy.data.objects["NB_thing_o1"].children if o.get("nb_part") == "座面のクッション"]
    books = [o for o in bpy.data.objects["NB_thing_o3"].children if o.get("nb_part") == "本"]
    assert sofa and len(books) > 20 and books[0]["nb_material"] == "布"
    holder = bpy.data.objects["NB_thing_o2"]
    seat = next(o for o in holder.children if o.name.startswith("座面"))
    back = next(o for o in holder.children if o.name.startswith("背もたれ"))
    # Fitted in the box (1.0 m high: the chair's 1.025 m scaled a little down), standing on the floor.
    points = [o.matrix_world @ Vector(c) for o in holder.children for c in o.bound_box]
    assert abs(min(p.z for p in points)) < 1e-3 and 0.9 < max(p.z for p in points) <= 1.0 + 1e-3
    # Its front toward the camera: the back rest is farther from the camera than the seat's middle.
    cam = Vector(plan["camera"]["positionM"])
    seat_c = seat.matrix_world @ Vector((0, 0, 0.45))
    back_c = back.matrix_world @ Vector((0, 0.2, 0.75))
    assert (back_c.xy - cam.xy).length > (seat_c.xy - cam.xy).length
    assert seat.data.materials[0].name.startswith("NB_dev_part_座面")


def _house_blend(folder: Path) -> None:
    """A place made here: walls, a ceiling and a roof above the eye, a tree's leaves, a van to move, a sign to hide,
    a light and a mannequin (D_Aunt) the modeller left in."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    coll = bpy.data.collections.new("家")
    bpy.context.scene.collection.children.link(coll)
    boxes = {
        "Wall_N": ((0, 12, 1.4), (12, 0.2, 2.8), "Plaster"),
        "Ceiling": ((0, 6, 2.5), (12, 12, 0.1), "Plaster"),
        "Roof": ((0, 6, 3.2), (13, 13, 0.2), "Roof_tiles"),
        "Tree_leaves": ((-8, 20, 4), (4, 4, 4), "Leaf"),
        "VAN": ((400, 0, 1), (4.5, 1.8, 2), "Paint"),
        "Sign_board": ((3, 8, 1), (1, 0.1, 1), "Paint"),
        "D_Aunt": ((1, 5, 0.8), (0.4, 0.3, 1.6), "Skin"),
    }
    for name, (centre, size, mat) in boxes.items():
        mesh = bpy.data.meshes.new(name)
        hx, hy, hz = (v / 2 for v in size)
        verts = [(centre[0] + sx * hx, centre[1] + sy * hy, centre[2] + sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        mesh.from_pydata(verts, [], [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
        mesh.materials.append(bpy.data.materials.new(mat))
        coll.objects.link(bpy.data.objects.new(name, mesh))
    # A shell: a wall and the ceiling over it in one mesh (as models often are).
    shell = bpy.data.meshes.new("Shell")
    shell.from_pydata([(-6, 14, 0), (6, 14, 0), (6, 14, 2.6), (-6, 14, 2.6), (-6, 2, 2.6), (6, 2, 2.6)], [], [(0, 1, 2, 3), (3, 2, 5, 4)])
    shell.materials.append(bpy.data.materials.new("Plaster"))
    coll.objects.link(bpy.data.objects.new("Shell", shell))
    lamp = bpy.data.objects.new("SUN", bpy.data.lights.new("SUN", "SUN"))
    coll.objects.link(lamp)
    folder.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "house.blend"))
    (folder / "素材.json").write_text(
        json.dumps({"assets": [{"name": "家", "kind": "place", "file": "house.blend", "license": "own"}]}, ensure_ascii=False),
        encoding="utf-8",
    )


@needs_blender
def test_develop_in_a_place(tmp_path):
    """A place (.blend): its light and mannequin left out, its van moved and sign hidden, its parts toned by their
    names, the leaves drawn by their outline; the eye level shows, so far layers go past it; the development does not
    draw over the Blockout's take; under the ceiling's light the ceiling and roof let it through."""
    import bpy

    from name_blockout.pipeline import run_blockout

    _house_blend(tmp_path / "素材")
    data = json.loads((ROOT / "examples" / "develop" / "指示.json").read_text(encoding="utf-8"))
    data["folders"] = {"assets": "素材"}
    shot = data["shots"][0]
    shot["objects"], shot["figures"] = [], []
    shot["camera"] = {"heightM": 1.5, "positionM": [0, 0, 1.5]}
    shot["place"] = {"asset": "家", "moves": [{"object": "VAN", "positionM": [8.4, -18.7, 1], "turnDeg": 90}], "hide": ["Sign"]}
    shot["look"]["materials"] = []
    shot["output"] = {"take": "1"}
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None)[0]["take"] == "1"
    r = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None, develop=True)[0]
    assert r["take"] == "2", r
    assert (tmp_path / "案" / "panel1" / "1" / "完成.png").exists()
    plan = json.loads((tmp_path / "blockout" / "panel1" / "2" / "plan.json").read_text(encoding="utf-8"))
    assert plan["far"] and any("遠景が決まっていないので" in n for n in plan["notes"])
    bpy.ops.wm.open_mainfile(filepath=str(tmp_path / "blockout" / "panel1" / "2" / "scene.blend"))
    names = {o.name for o in bpy.data.objects}
    assert (
        "D_Aunt" not in names
        and "Sign_board" not in names
        and not [o for o in bpy.data.objects if o.type == "LIGHT" and not o.name.startswith("NB_")]
    )
    van = bpy.data.objects["VAN"]
    assert tuple(round(v, 3) for v in van.location) == (8.4, -18.7, 1.0) and abs(van.rotation_euler.z - 1.5708) < 1e-3
    assert bpy.data.objects["Roof"]["nb_place_materials"] == ["瓦"] and bpy.data.objects["Tree_leaves"].get("nb_foliage")
    assert "NB_lines_near_foliage" in [ls.name for ls in bpy.context.view_layer.freestyle_settings.linesets]

    shot["look"] = {"setting": "indoor", "light": {"key": "interior"}}
    shot["output"] = {}
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = run_blockout(tmp_path / "指示.json", preview_dpi=60, log=lambda *_: None, develop=True)[0]
    bpy.ops.wm.open_mainfile(filepath=str(tmp_path / "blockout" / "panel1" / r["take"] / "scene.blend"))
    assert not bpy.data.objects["Ceiling"].visible_shadow and not bpy.data.objects["Roof"].visible_shadow
    assert bpy.data.objects["Wall_N"].visible_shadow
    # The shell's ceiling split off from its wall: the ceiling lets the light through, the wall still casts.
    assert bpy.data.objects["Shell"].visible_shadow and len(bpy.data.objects["Shell"].data.polygons) == 1
    assert not bpy.data.objects["Shell_above"].visible_shadow and len(bpy.data.objects["Shell_above"].data.polygons) == 1
