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
    # The ceiling's corners are drawn high in the picture (above everything standing in the room): folds, so thin
    # ones (paler than a full line at this size).
    assert (lines[: h * 3 // 10, :, 3] > 0.1).sum() > w // 2


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
        "Roof": ((0, 6, 3.4), (13, 13, 0.6), "Roof_tiles"),
        "Tree_leaves": ((-8, 20, 4), (4, 4, 4), "Leaf"),
        "VAN": ((400, 0, 1), (4.5, 1.8, 2), "Paint"),
        "Sign_board": ((3, 8, 1), (1, 0.1, 1), "Paint"),
        "D_Aunt": ((1, 5, 0.8), (0.4, 0.3, 1.6), "Skin"),
        "Old_take": ((-3, 8, 1), (1, 1, 2), "Paint"),
        "Solar_panel": ((2, 6, 3.4), (3, 2, 0.05), "Panel"),
        # A loft's floor under the camera: the room's floor is still the one below it.
        "Loft": ((0, 0, 0.95), (2, 2, 0.1), "Wood"),
    }
    for name, (centre, size, mat) in boxes.items():
        mesh = bpy.data.meshes.new(name)
        hx, hy, hz = (v / 2 for v in size)
        verts = [(centre[0] + sx * hx, centre[1] + sy * hy, centre[2] + sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        mesh.from_pydata(verts, [], [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
        mesh.materials.append(bpy.data.materials.new(mat))
        coll.objects.link(bpy.data.objects.new(name, mesh))
    bpy.data.objects["Old_take"].hide_render = True
    bpy.data.objects["VAN"].hide_render = True
    # The van's paint is black only in the viewport's colour (as a .blend drawn with an emission shader keeps it).
    bpy.data.materials["Paint"].diffuse_color = (0.03, 0.03, 0.03, 1.0)
    # The room's floor at the light's ground's height (z 0): they must not shade each other.
    floor = bpy.data.meshes.new("Floor")
    floor.from_pydata([(-6, -6, 0), (6, -6, 0), (6, 14, 0), (-6, 14, 0)], [], [(0, 1, 2, 3)])
    floor.materials.append(bpy.data.materials.new("Lawn"))
    coll.objects.link(bpy.data.objects.new("Floor", floor))
    # A lot's ground with a bank down to a lower level (0.8 m): still a ground.
    bank = bpy.data.meshes.new("site_ground")
    bank.from_pydata(
        [(-20, -30, 0), (20, -30, 0), (20, -10, 0), (-20, -10, 0), (-20, -31, -0.8), (20, -31, -0.8)],
        [],
        [(0, 1, 2, 3), (4, 5, 1, 0)],
    )
    bank.materials.append(bpy.data.materials.new("Grass"))
    coll.objects.link(bpy.data.objects.new("site_ground", bank))
    # A shell: a wall and the ceiling over it in one mesh (as models often are).
    shell = bpy.data.meshes.new("Shell")
    shell.from_pydata([(-6, 14, 0), (6, 14, 0), (6, 14, 2.6), (-6, 14, 2.6), (-6, 2, 2.6), (6, 2, 2.6)], [], [(0, 1, 2, 3), (3, 2, 5, 4)])
    shell.materials.append(bpy.data.materials.new("Plaster"))
    coll.objects.link(bpy.data.objects.new("Shell", shell))
    # A roof kit: a parapet and a solar array modelled cell by cell (4 × 6 faces of 0.16 m) in one mesh.
    kit = bpy.data.meshes.new("Roof_kit")
    verts, faces, mats = [(4, 0, 3.0), (5, 0, 3.0), (5, 0, 3.4), (4, 0, 3.4)], [(0, 1, 2, 3)], [0]
    for i in range(4):
        for j in range(6):
            k = len(verts)
            x, y = 4 + i * 0.16, 1 + j * 0.16
            verts += [(x, y, 3.7), (x + 0.16, y, 3.7), (x + 0.16, y + 0.16, 3.7), (x, y + 0.16, 3.7)]
            faces.append((k, k + 1, k + 2, k + 3))
            mats.append(1)
    kit.from_pydata(verts, [], faces)
    kit.materials.append(bpy.data.materials.new("Parapet"))
    kit.materials.append(bpy.data.materials.new("solar"))
    for poly, m in zip(kit.polygons, mats):
        poly.material_index = m
    coll.objects.link(bpy.data.objects.new("Roof_kit", kit))
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
    shot["place"] = {
        "asset": "家",
        "moves": [{"object": "VAN", "positionM": [8.4, -18.7, 1], "turnDeg": 90, "show": True}],
        "hide": ["Sign"],
    }
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
    # Left out of the .blend's renders: not in the place (unless shown); a dark paint is ベタ; panels outline only.
    assert "Old_take" not in names and not van.hide_render and van["nb_place_materials"] == ["黒い塗装"]
    assert bpy.data.objects["Solar_panel"].get("nb_foliage")
    # …its cells a grid in its tone.
    panel = bpy.data.objects["Solar_panel"]
    assert list(panel["nb_cell_slots"]) == [0] and not panel.get("nb_cell_faces")
    assert panel.material_slots[0].material.name.startswith("NB_dev_cells_"), panel.material_slots[0].material
    # A roof kit whose solar slot's faces are the cells: only that slot is dark, the joints come from its faces.
    kit = bpy.data.objects["Roof_kit"]
    assert list(kit["nb_cell_slots"]) == [1] and kit.get("nb_cell_faces")
    assert kit.material_slots[1].material.name.startswith("NB_dev_cell_faces_")
    assert not kit.material_slots[0].material.name.startswith("NB_dev_cell")
    marks = [v.value for v in kit.data.attributes["freestyle_face"].data]
    assert not marks[0] and all(marks[1:])  # the parapet keeps its lines, the cells are outline only
    # A large flat lawn is ground: white, not the grass's grey.
    assert bpy.data.objects["Floor"]["nb_place_materials"] == ["白地"]
    assert bpy.data.objects["site_ground"]["nb_place_materials"] == ["白地"] and not bpy.data.objects["site_ground"].get("nb_foliage")
    assert bpy.data.objects["Shell"]["nb_place_materials"] == ["白壁"]
    # A ベタ thing's folds are drawn (white over it).
    assert bpy.data.objects["site_ground"].get("nb_ground")
    assert all(v.value for v in van.data.attributes["freestyle_edge"].data)
    # The development's line sets: the texture lines only (marked edges, fading with distance); none for far things.
    sets = [ls.name for ls in bpy.context.view_layer.freestyle_settings.linesets]
    assert "NB_lines_near_texture" in sets and not [n for n in sets if n.startswith("NB_lines_far")], sets
    check = json.loads((tmp_path / "blockout" / "panel1" / "2" / "check.json").read_text(encoding="utf-8"))
    lines = next(c for c in check["checks"] if c["name"] == "影の向き")["lines"]
    assert 1.5 <= lines["foregroundM"] <= 25 and lines["inkShare"] > 0, lines
    far = bpy.data.collections["NB_band_far"].all_objects
    assert far and all(o.data.materials[0].name == "NB_dev_far" for o in far if o.type == "MESH")

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
    assert bpy.data.objects["NB_light_ground"].data.vertices[0].co.z < -0.01
    light = json.loads((tmp_path / "blockout" / "panel1" / r["take"] / "check.json").read_text(encoding="utf-8"))
    faces = next(c for c in light["checks"] if c["name"] == "影の向き")["faces"]
    assert faces["sunny"][1] > 0 and faces["sunny"][0] / faces["sunny"][1] > 0.85, faces


@needs_blender
def test_joints_grey_and_outlines_black():
    """A line inside a floor (up on both sides) turns grey; the floor's edge against a wall stays black; a line inside
    ベタ turns white, the ベタ's outline stays black."""
    import numpy as np

    from name_blockout.blender.develop import grey_joints, white_on_beta

    h, w = 40, 60
    lines = np.zeros((h, w, 4), dtype=np.float32)
    lines[:, 20, 3] = 1.0  # a joint across the floor
    lines[30, :, 3] = 1.0  # the floor's edge: below it a wall
    up = np.zeros((h, w), dtype=bool)
    up[:30] = True
    out = grey_joints(lines, up, 3)
    assert out[10, 20, 0] > 0.2 and out[10, 20, 3] < 1.0
    assert out[30, 40, 0] == 0.0 and out[30, 40, 3] == 1.0
    tone = np.ones((h, w, 4), dtype=np.float32)
    tone[5:25, 30:55, :3] = 0.0  # a ベタ block
    lines = np.zeros((h, w, 4), dtype=np.float32)
    lines[15, 30:55, 3] = 1.0  # a seam across it, reaching its edges
    done = white_on_beta(lines, tone, 3)
    assert done[15, 42, 0] == 1.0 and done[15, 30, 0] == 0.0


@needs_blender
def test_a_joint_greys_up_to_the_wall_and_a_narrow_beta_keeps_black_lines():
    """A joint's end by a wall's foot greys too (no black whisker), the foot stays black; on a strip of ベタ
    narrower than a few reaches (a dark fascia) the lines stay black (white ones would be specks)."""
    import numpy as np

    from name_blockout.blender.develop import grey_joints, white_on_beta

    h, w = 40, 60
    lines = np.zeros((h, w, 4), dtype=np.float32)
    lines[:, 20, 3] = 1.0  # a joint across the floor
    lines[30, :, 3] = 1.0  # the wall's foot: below it the wall
    up = np.zeros((h, w), dtype=bool)
    up[:30] = True
    plain = grey_joints(lines, up, 4)
    tipped = grey_joints(lines, up, 4, tip=2)
    assert plain[28, 20, 0] == 0.0 and tipped[28, 20, 0] > 0.2
    assert tipped[30, 40, 0] == 0.0 and tipped[30, 20, 0] == 0.0
    tone = np.ones((h, w, 4), dtype=np.float32)
    tone[10:16, 5:55, :3] = 0.0  # a dark fascia, 6 px high
    lines = np.zeros((h, w, 4), dtype=np.float32)
    lines[13, 5:55, 3] = 1.0
    assert white_on_beta(lines, tone, 2)[13, 30, 0] == 0.0


@needs_blender
def test_cell_gaps_between_faces_not_at_the_panel_edge():
    import numpy as np

    from name_blockout.blender.develop import cell_gaps

    ids = np.zeros((40, 40), dtype=np.float32)
    for i in range(4):
        for j in range(4):
            ids[5 + i * 8 : 13 + i * 8, 5 + j * 8 : 13 + j * 8] = 0.1 + 0.05 * (i * 4 + j)
    gaps = cell_gaps(ids, 4.0)
    assert gaps[12, 8] and gaps[8, 12]  # between two cells
    assert not gaps[4, 8] and not gaps[8, 8]  # the panel's edge, a cell's middle
    assert not cell_gaps(ids, 20.0).any()  # cells too small to show their joints


@needs_blender
def test_majority_removes_speckles_keeps_edges():
    import numpy as np

    from name_blockout.blender.develop import majority

    mask = np.zeros((30, 30), dtype=bool)
    mask[:, 15:] = True
    mask[5, 5] = True  # a speck in the light
    mask[20, 25] = False  # a speck in the shadow
    out = majority(mask, 2)
    assert not out[5, 5] and out[20, 25]
    assert (out[:, 15:] == True).all() and not out[:, :15].any()  # noqa: E712


@needs_blender
def test_a_step_edge_is_not_a_joint():
    """A line between two surfaces looking up at two heights (a step's edge) stays black; a joint in one floor greys."""
    import numpy as np

    from name_blockout.blender.develop import grey_joints

    h, w = 40, 60
    lines = np.zeros((h, w, 4), dtype=np.float32)
    lines[20, :, 3] = 1.0  # the step's edge
    lines[:, 40, 3] = 1.0  # a joint
    up = np.ones((h, w), dtype=bool)
    height = np.zeros((h, w), dtype=np.float32)
    height[:20] = 0.2  # the step's top, 20 cm over the floor
    out = grey_joints(lines, up, 3, height)
    assert out[20, 10, 0] == 0.0 and out[20, 10, 3] == 1.0
    assert out[5, 40, 0] > 0.2 and out[30, 40, 0] > 0.2


@needs_blender
def test_device_cpu_when_asked_or_no_gpu(monkeypatch):
    from name_blockout.blender import render

    monkeypatch.setenv(render.DEVICE_ENV, "cpu")
    monkeypatch.setattr(render, "_chosen", None)
    assert render.choose_device() == "CPU"
    monkeypatch.setenv(render.DEVICE_ENV, "auto")
    monkeypatch.setattr(render, "_chosen", "GPU")  # as if a GPU were found
    assert render.choose_device(1098 * 482) == "CPU"  # a 150 dpi panel: readying the GPU costs more
    assert render.choose_device(4394 * 1928) == "GPU"
    monkeypatch.setattr(render, "_chosen", None)
    assert render.choose_device() in ("CPU", "GPU")
