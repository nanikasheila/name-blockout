# SPDX-License-Identifier: GPL-3.0-or-later
"""End to end in Blender (bpy): build, measure independently, draw out, hand to name-studio."""

import json
import math
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
    # The layout from above is written with the take (俯瞰図), and the take can go to a critic: beside a reference
    # (here the Blockout-like line picture of the same take: emptier than the finished one, so nothing is too empty).
    assert (tmp_path / "俯瞰図" / "panel1.svg").exists() and (tmp_path / "blockout" / "panel1" / "1" / "俯瞰図.svg").exists()
    from name_blockout.cli import main

    reference = tmp_path / "案" / "panel1" / "1" / "線画.png"
    assert main(["critique", str(tmp_path / "指示.json"), "--shot", "panel1", "--reference", str(reference), "--json"]) == 0
    pack = tmp_path / "講評" / "panel1" / "1"
    numbers = json.loads((pack / "数字.json").read_text(encoding="utf-8"))
    assert numbers["take"] == "1" and numbers["density"]["sameFraming"] and numbers["density"]["pass"], numbers["density"]
    assert numbers["lines"]["widthsMm"] and numbers["density"]["take"]["dark"] > 0
    sheet = bpy.data.images.load(str(pack / "並べた絵.png"))
    assert sheet.size[0] > 2 * 0.9 * fw and sheet.size[1] == fh
    answer = tmp_path / "答え.json"
    answer.write_text(json.dumps({"problems": []}), encoding="utf-8")
    assert main(["critique", str(tmp_path / "指示.json"), "--shot", "panel1", "--answer", str(answer)]) == 0
    assert (pack / "講評.json").exists()


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
    # The top view holds what the place holds, as it stands in the scene (the van where it was moved to).
    top = json.loads((tmp_path / "俯瞰図" / "panel1.json").read_text(encoding="utf-8"))
    outlines = {o["name"]: o for o in top["place"]["outlines"]}
    assert outlines["site_ground"]["ground"] and not outlines["VAN"]["ground"]
    assert "D_Aunt" not in outlines and "Sign_board" not in outlines
    assert (tmp_path / "blockout" / "panel1" / "2" / "俯瞰図.svg").exists()
    bpy.ops.wm.open_mainfile(filepath=str(tmp_path / "blockout" / "panel1" / "2" / "scene.blend"))
    names = {o.name for o in bpy.data.objects}
    assert (
        "D_Aunt" not in names
        and "Sign_board" not in names
        and not [o for o in bpy.data.objects if o.type == "LIGHT" and not o.name.startswith("NB_")]
    )
    van = bpy.data.objects["VAN"]
    from mathutils import Vector

    corners = [van.matrix_world @ Vector(c) for c in van.bound_box]
    # Each thing by its own outline (rings), not one convex blob; a ground by its edge alone.
    assert outlines["VAN"]["ringsM"] and "ringsM" not in outlines["site_ground"] and not top["place"]["cut"]
    van_x, van_y = ([q[i] for q in outlines["VAN"]["footprintM"]] for i in range(2))
    assert abs(min(van_x) - min(c.x for c in corners)) < 0.06 and abs(max(van_y) - max(c.y for c in corners)) < 0.06
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
def test_a_place_indoors_is_cut_as_a_floor_plan():
    """A camera in a room: the place is cut 1.2 m over the floor (walls as lines, the roof and the lamp left out,
    the table by its outline); a camera in the garden sees the place whole."""
    import bpy

    from name_blockout.blender import measure as bmeasure
    from name_blockout.blender import scene as bscene

    bscene.reset()

    def boxes(name, items):
        verts, faces = [], []
        for x0, y0, z0, x1, y1, z1 in items:
            k = len(verts)
            verts += [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
            faces += [(k, k + 1, k + 3, k + 2), (k + 4, k + 5, k + 7, k + 6), (k, k + 1, k + 5, k + 4)]
            faces += [(k + 2, k + 3, k + 7, k + 6), (k, k + 2, k + 6, k + 4), (k + 1, k + 3, k + 7, k + 5)]
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, [], faces)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    floor = 0.3
    walls = [(-4, -3, floor, 4, -2.8, 2.9), (-4, 2.8, floor, 4, 3, 2.9), (-4, -3, floor, -3.8, 3, 2.9), (3.8, -3, floor, 4, 3, 2.9)]
    things = [
        boxes("shell", walls + [(-4, -3, 0, 4, 3, floor)]),
        boxes("roof", [(-4.5, -3.5, 2.9, 4.5, 3.5, 3.1)]),
        boxes("table", [(-1, -0.5, floor, 1, 0.5, floor + 0.7)]),
        boxes("lamp", [(-0.1, -0.1, 2.3, 0.1, 0.1, 2.9)]),
        boxes("tree", [(9.8, -0.2, 0, 10.2, 0.2, 2.5), (8.5, -1.5, 2.5, 11.5, 1.5, 5.5)]),
    ]
    bpy.context.view_layer.update()

    cut = bmeasure.indoor_cut((0.5, 0.2, 1.9))
    assert cut and abs(cut["floorM"] - floor) < 1e-3 and abs(cut["cutM"] - (floor + 1.2)) < 1e-3
    assert abs(cut["ceilingM"] - 2.9) < 1e-3 and 3.5 < cut["roomReachM"] < 5.5
    assert bmeasure.indoor_cut((10.0, 6.0, 1.6)) is None  # in the garden
    assert bmeasure.indoor_cut((11.0, 0.5, 1.6)) is None  # under the tree's crown is not a room

    whole = {o["name"]: o for o in bmeasure.footprints(things)}
    assert set(whole) == {"shell", "roof", "table", "lamp", "tree"} and "sectionM" not in whole["shell"]
    plan = {o["name"]: o for o in bmeasure.footprints(things, cut["cutM"])}
    assert set(plan) == {"shell", "table", "tree"}  # the roof and the lamp are over the cut
    assert plan["shell"]["sectionM"] and not plan["table"]["sectionM"]
    xs = [q[0] for line in plan["shell"]["sectionM"] for q in line]
    ys = [q[1] for line in plan["shell"]["sectionM"] for q in line]
    assert (min(xs), max(xs), min(ys), max(ys)) == (-4.0, 4.0, -3.0, 3.0)
    # The tree by its trunk alone (its crown starts over the cut), and the trunk cut.
    tx = [q[0] for ring in plan["tree"]["ringsM"] for q in ring]
    assert max(tx) - min(tx) < 0.6 and plan["tree"]["sectionM"]
    wx = [q[0] for ring in whole["tree"]["ringsM"] for q in ring]
    assert max(wx) - min(wx) > 2.9


@needs_blender
def test_lines_on_beta_turn_white_and_a_narrow_beta_keeps_black_lines():
    """A line inside ベタ turns white, the ベタ's outline stays black; on a strip of ベタ narrower than a few reaches
    (a dark fascia) the lines stay black (white ones would be specks)."""
    import numpy as np

    from name_blockout.blender.develop import white_on_beta

    h, w = 40, 60
    tone = np.ones((h, w, 4), dtype=np.float32)
    tone[5:25, 30:55, :3] = 0.0  # a ベタ block
    lines = np.zeros((h, w, 4), dtype=np.float32)
    lines[15, 30:55, 3] = 1.0  # a seam across it, reaching its edges
    done = white_on_beta(lines, tone, 3)
    assert done[15, 42, 0] == 1.0 and done[15, 30, 0] == 0.0
    tone = np.ones((h, w, 4), dtype=np.float32)
    tone[10:16, 5:55, :3] = 0.0  # a dark fascia, 6 px high
    lines = np.zeros((h, w, 4), dtype=np.float32)
    lines[13, 5:55, 3] = 1.0
    assert white_on_beta(lines, tone, 2)[13, 30, 0] == 0.0


@needs_blender
def test_texture_lines_end_with_distance_and_are_never_paler():
    """A floor's joints are kept whole up to TEXTURE_REACH foregrounds off and gone a little farther."""
    import numpy as np

    from name_blockout.blender.develop import TEXTURE_END, TEXTURE_REACH, texture_reach

    distance = np.array([[1.0, 5.0 * TEXTURE_REACH, 5.0 * TEXTURE_REACH * (1 + TEXTURE_END), 500.0]], dtype=np.float32)
    kept = texture_reach(distance, 5.0)
    assert kept.tolist() == [[1.0, 1.0, 0.0, 0.0]]
    # The band where a line ends is short: a tenth of its reach.
    between = texture_reach(np.linspace(1.0, 100.0, 1000, dtype=np.float32)[None], 5.0)
    assert ((between > 0) & (between < 1)).mean() < 0.03


@needs_blender
def test_tops_in_the_light_are_the_lightest():
    """A face looking up in the light is TOP_LIGHTER less dense (a concrete roof's top comes out white); a dark
    tone (a solar panel's cells) and ベタ stay."""
    import numpy as np

    from name_blockout.blender.develop import TOP_LIGHTER, top_lighter

    shown = np.ones((1, 5, 3), dtype=np.float32)
    for i, density in enumerate((0.1, 0.35, 0.55, 1.0, 0.1)):
        shown[0, i] = 1.0 - density
    tops = np.array([[True, True, True, True, False]])
    out = 1.0 - top_lighter(shown, tops)[0, :, 0]
    assert np.allclose(out, [0.0, 0.35 - TOP_LIGHTER, 0.55, 1.0, 0.1], atol=1e-6)


@needs_blender
def test_where_two_materials_meet_on_a_ground_the_edge_is_marked():
    import bpy

    from name_blockout.blender.scene import mark_material_borders

    mesh = bpy.data.meshes.new("lot")
    # Three squares in a row: lawn, lawn, path.
    verts = [(x, y, 0.0) for y in (0, 1) for x in (0, 1, 2, 3)]
    mesh.from_pydata(verts, [], [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6)])
    for name in ("grass", "pave"):
        mesh.materials.append(bpy.data.materials.new(name))
    mesh.polygons[2].material_index = 1
    obj = bpy.data.objects.new("lot", mesh)
    assert mark_material_borders(obj) == 1
    marked = [tuple(sorted(e.vertices)) for e, m in zip(mesh.edges, mesh.attributes["freestyle_edge"].data) if m.value]
    assert marked == [(2, 6)]
    # Two pieces that share no edge (a path laid beside a lawn, 1 cm higher): the edge where they lie against each
    # other is marked once; the lot's own outer edges are not.
    apart = bpy.data.meshes.new("apart")
    verts = [(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0), (2, 0, 0.01), (3, 0, 0.01), (3, 1, 0.01), (2, 1, 0.01)]
    apart.from_pydata(verts, [], [(0, 1, 2, 3), (4, 5, 6, 7)])
    for name in ("grass", "pave"):
        apart.materials.append(bpy.data.materials[name])
    apart.polygons[1].material_index = 1
    obj = bpy.data.objects.new("apart", apart)
    assert mark_material_borders(obj) == 1
    marked = [tuple(sorted(e.vertices)) for e, m in zip(apart.edges, apart.attributes["freestyle_edge"].data) if m.value]
    assert marked in ([(1, 2)], [(4, 7)])
    # A kerb standing on the paving (its foot's open edges lie on the paving's face): its foot is marked.
    kerb = bpy.data.meshes.new("kerb")
    verts = [(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)]
    verts += [(1, 1, 0), (3, 1, 0), (3, 1.2, 0), (1, 1.2, 0), (1, 1, 0.15), (3, 1, 0.15), (3, 1.2, 0.15), (1, 1.2, 0.15)]
    sides = [(4, 5, 9, 8), (5, 6, 10, 9), (6, 7, 11, 10), (7, 4, 8, 11), (8, 9, 10, 11)]
    kerb.from_pydata(verts, [], [(0, 1, 2, 3), *sides])
    for name in ("pave", "grass"):
        kerb.materials.append(bpy.data.materials[name])
    for poly in list(kerb.polygons)[1:]:
        poly.material_index = 1
    assert mark_material_borders(bpy.data.objects.new("kerb", kerb)) == 4
    # One material: nothing to tell apart.
    plain = bpy.data.meshes.new("plain")
    plain.from_pydata(verts, [], [(0, 1, 5, 4), (1, 2, 6, 5)])
    assert mark_material_borders(bpy.data.objects.new("plain", plain)) == 0


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


def _lot_from_above(folder: Path, half: float = 30.0, tree: bool = False) -> None:
    """A place seen from above: a flat-roofed block (its roof a concrete slab) with a glass front, on a lot (`half`
    across each way from its middle) that is lawn on one side and paving on the other; with `tree`, a tree in a
    planter before the block."""
    import bmesh
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    coll = bpy.data.collections.new("家")
    bpy.context.scene.collection.children.link(coll)

    def box(name, lo, hi, material):
        (x0, y0, z0), (x1, y1, z1) = lo, hi
        verts = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
        faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, [], faces)
        mesh.materials.append(bpy.data.materials.get(material) or bpy.data.materials.new(material))
        coll.objects.link(bpy.data.objects.new(name, mesh))

    box("shell", (-4, 0, 0), (4, 6, 3), "Plaster")
    box("slab", (-5, -1, 3), (5, 7, 3.3), "concrete")
    box("glass_front", (-3, -0.05, 0.3), (3, 0, 2.7), "Glass")
    if tree:
        box("tree_trunk", (-8.2, -8.2, 0), (-7.8, -7.8, 3), "bark")
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=2.2)
        bmesh.ops.translate(bm, vec=(-8.0, -8.0, 4.6), verts=bm.verts)
        # …standing in a planter (part of the same object, as a potted plant is modelled: a second slot).
        pot = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(1.4, 1.4, 0.9), verts=pot["verts"])
        bmesh.ops.translate(bm, vec=(-8.0, -8.0, 0.45), verts=pot["verts"])
        for face in {f for v in pot["verts"] for f in v.link_faces}:
            face.material_index = 1
        crown = bpy.data.meshes.new("tree_crown")
        bm.to_mesh(crown)
        bm.free()
        crown.materials.append(bpy.data.materials.new("leaf"))
        crown.materials.append(bpy.data.materials.get("concrete") or bpy.data.materials.new("concrete"))
        coll.objects.link(bpy.data.objects.new("tree_crown", crown))
    lot = bpy.data.meshes.new("site_ground")
    xs = (-half, 0, half)
    verts = [(x, y, 0.0) for y in (-half, half) for x in xs]
    lot.from_pydata(verts, [], [(0, 1, 4, 3), (1, 2, 5, 4)])
    for name in ("grass", "pave"):
        lot.materials.append(bpy.data.materials.new(name))
    lot.polygons[1].material_index = 1
    coll.objects.link(bpy.data.objects.new("site_ground", lot))
    folder.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "lot.blend"))
    (folder / "素材.json").write_text(
        json.dumps({"assets": [{"name": "家", "kind": "place", "file": "lot.blend", "license": "own"}]}, ensure_ascii=False),
        encoding="utf-8",
    )


@needs_blender
def test_develop_from_above_roof_white_windows_dark_lines_black(tmp_path):
    """A house seen from above by day, from an instruction written out at 150 dpi: developed at 300 dpi all the
    same; its concrete roof's top in the light is white, its glass front dark; where the lawn meets the paving the
    lot has a line; and no line is a pale hair."""
    import bpy

    from name_blockout.blender.picture import load
    from name_blockout.camera import fit_camera
    from name_blockout.instruction import frame_of
    from name_blockout.pipeline import run_blockout

    _lot_from_above(tmp_path / "素材")
    data = json.loads((ROOT / "examples" / "develop" / "指示.json").read_text(encoding="utf-8"))
    data["folders"] = {"assets": "素材"}
    shot = data["shots"][0]
    shot["objects"], shot["figures"] = [], []
    shot["frame"] = {"boxMm": [17, 17, 110, 77], "dpi": 150, "shapeMm": [[20, 20], [107, 20], [107, 74], [20, 74]]}
    shot["ruler"] = {"points": 2, "horizonMm": [[20, -23], [107, -23]], "vanishingMm": [[150, -23], [-40, -23]]}
    shot["camera"] = {"heightM": 15.0, "positionM": [-20, -22, 15.0], "lensMm": 37}
    shot["place"] = {"asset": "家"}
    shot["look"]["materials"] = []
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    r = run_blockout(tmp_path / "指示.json", log=lambda *_: None, develop=True)[0]
    plan = json.loads((tmp_path / "blockout" / "panel1" / r["take"] / "plan.json").read_text(encoding="utf-8"))
    assert plan["frame"]["dpi"] == 150 and plan["render"]["dpi"] == 300
    assert plan["render"]["sizePx"] == [frame_of({**shot["frame"], "dpi": 300}).width, frame_of({**shot["frame"], "dpi": 300}).height]
    assert any("300dpi で描きます" in n for n in plan["notes"])

    camera = fit_camera(shot)

    def at(point):
        x, y = camera.project(point)
        return round(y * 2), round(x * 2)  # the instruction's pixels (150 dpi) → the picture's (300 dpi)

    tone = load(tmp_path / "案" / "panel1" / r["take"] / "トーン.png")
    roof, glass = at((2.0, 4.0, 3.3)), at((0.0, -0.05, 1.5))
    assert tone[roof][3] > 0.99 and tone[roof][:3].min() > 0.99, tone[roof]  # コンクリート 0.1 − the top's 0.15: white
    assert 0.35 < tone[glass][:3].max() < 0.55, tone[glass]  # a dark tone (density 0.5–0.6), not a solid black
    # The lot's two materials are told apart by a line (both are left white).
    bpy.ops.wm.open_mainfile(filepath=str(tmp_path / "blockout" / "panel1" / r["take"] / "scene.blend"))
    lot = bpy.data.objects["site_ground"]
    assert lot["nb_place_materials"] == ["白地", "白地"] and sum(m.value for m in lot.data.attributes["freestyle_edge"].data) == 1
    lines = load(tmp_path / "案" / "panel1" / r["take"] / "線画.png")
    y, x = at((0.0, -12.0, 0.0))  # on the lawn's edge against the paving, before the house
    assert lines[y - 3 : y + 4, x - 3 : x + 4, 3].max() > 0.9
    # Lines are black: next to none of the picture is a faint line (a line's smooth edge is a pixel wide at most).
    alpha = lines[..., 3]
    faint, full = ((alpha > 0.05) & (alpha < 0.5)).sum(), (alpha >= 0.5).sum()
    assert full > 500 and faint < full, (faint, full)
    assert lines[alpha > 0.05][:, :3].max() < 0.05  # and none is grey
    # What the white lot is made of is said by a few marks: tufts on the lawn (sparse, the finest pen), none on
    # the paving; each face of the lot keeps its kind for them.
    assert list(lot["nb_ground_kinds"])[0] == "草"
    assert [round(v.value, 2) for v in lot.data.attributes["nb_ground_kind"].data] == [0.25, 0.0]
    check = json.loads((tmp_path / "blockout" / "panel1" / r["take"] / "check.json").read_text(encoding="utf-8"))
    said = next(c["groundMarks"] for c in check["checks"] if "groundMarks" in c)
    assert set(said) == {"草"} and 5 < said["草"]["marks"] < 200, said

    def inked(point) -> bool:
        if camera.project(point) is None:  # behind the camera
            return False
        y, x = at(point)
        return 0 <= y < alpha.shape[0] and 0 <= x < alpha.shape[1] and alpha[max(0, y - 30) : y + 31, max(0, x - 30) : x + 31].max() > 0.9

    lawn = [(float(x), float(y), 0.0) for x in range(-26, -2, 2) for y in range(-26, -3, 2)]
    paving = [(float(x), float(y), 0.0) for x in range(4, 27, 2) for y in range(-26, -7, 2)]
    assert sum(inked(p) for p in lawn) > 5 and not any(inked(p) for p in paving)


@needs_blender
def test_develop_a_town_round_the_place_and_a_tree_by_its_shade(tmp_path):
    """Looking down on a house whose lot ends inside the picture, with `surroundings: town`: houses stand beyond the
    lot (none on it, none before the house), toned and lined as built things; the place's tree (on the lawn before the house) has no outline of
    its own (a natural thing is told by its shade) while the house beside it keeps its lines."""
    import bpy

    from name_blockout.blender.picture import load
    from name_blockout.camera import fit_camera
    from name_blockout.pipeline import run_blockout
    from name_blockout.town import rect

    half = 14.0
    _lot_from_above(tmp_path / "素材", half=half, tree=True)
    data = json.loads((ROOT / "examples" / "develop" / "指示.json").read_text(encoding="utf-8"))
    data["folders"] = {"assets": "素材"}
    shot = data["shots"][0]
    shot["objects"], shot["figures"] = [], []
    shot["frame"] = {"boxMm": [17, 17, 110, 77], "dpi": 150, "shapeMm": [[20, 20], [107, 20], [107, 74], [20, 74]]}
    # The eye level 12 mm above the panel: the lot's far side and the ground beyond it are in the picture's top.
    shot["ruler"] = {"points": 2, "horizonMm": [[20, 8], [107, 8]], "vanishingMm": [[150, 8], [-40, 8]]}
    shot["camera"] = {"heightM": 14.0, "positionM": [-30, -30, 14.0], "lensMm": 37}
    shot["place"] = {"asset": "家"}
    shot["surroundings"] = {"kind": "town", "seed": 4, "street": {"axis": "X", "atM": -17.0}}
    shot["look"]["materials"] = []
    shot["look"]["north"] = "-X"  # the afternoon sun from the picture's right: the tree's shade side shows
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    r = run_blockout(tmp_path / "指示.json", log=lambda *_: None, develop=True)[0]
    work = tmp_path / "blockout" / "panel1" / r["take"]
    plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    around = plan["surroundings"]
    assert around["houses"] and any(n.startswith("まわりは市街地") for n in plan["notes"])
    # Nothing of the town on the lot, and every house beyond the place's things from the camera.
    for q in (
        [q for h in around["houses"] for q in rect(h)] + [t["centreM"] for t in around["trees"]] + [p["centreM"] for p in around["poles"]]
    ):
        assert not (-half < q[0] < half and -half < q[1] < half), q
    origin = plan["camera"]["positionM"][:2]
    assert around["houses"][0]["distanceM"] > math.hypot(-origin[0], 3 - origin[1])

    bpy.ops.wm.open_mainfile(filepath=str(work / "scene.blend"))
    houses = bpy.data.objects["NB_town_houses"]
    slots = ["白壁", "コンクリート", "木", "瓦", "トタン", "ガラス", "金属", "黒い塗装"]
    assert list(houses["nb_place_materials"]) == slots and houses["nb_band"] == "middle"
    assert {p.material_index for p in houses.data.polygons} >= {0, 3, 5}  # walls, tiled roofs and windows at the least
    # A Japanese quarter: the plots' walls, cars in their car spaces, poles, and the wires between them (hairlines:
    # solid black, no line drawn along them, no shadow).
    assert around["walls"] and around["cars"] and around["poles"] and around["wires"]
    assert list(bpy.data.objects["NB_town_walls"]["nb_place_materials"]) == ["コンクリート"]
    assert list(bpy.data.objects["NB_town_cars"]["nb_place_materials"]) == slots and bpy.data.objects["NB_town_poles"]
    wires = bpy.data.objects["NB_town_wires"]
    assert wires.get("nb_hairline") and wires.get("nb_noshadow") and list(wires["nb_place_materials"]) == ["黒い塗装"]
    assert not wires.hide_render
    if around["hedges"]:
        assert bpy.data.objects["NB_town_hedges"].get("nb_natural")
    assert bpy.data.objects["tree_crown"].get("nb_natural") and bpy.data.objects["tree_trunk"].get("nb_natural")
    assert not bpy.data.objects["shell"].get("nb_natural") and bpy.data.objects["NB_town_trees"].get("nb_natural")

    camera = fit_camera(shot)

    def at(point):
        x, y = camera.project(point)
        return round(y * 2), round(x * 2)

    takes = tmp_path / "案" / "panel1" / r["take"]
    lines, tone = load(takes / "線画.png"), load(takes / "トーン.png")
    alpha = lines[..., 3]
    # The tree's crown: toned (its lit side or its shade), and no line on or round it.
    y, x = at((-8.0, -8.0, 4.6))
    crown = (slice(max(0, y - 12), y + 13), slice(max(0, x - 12), x + 13))
    assert tone[crown][..., 3].mean() > 0.9 and tone[crown][..., :3].mean() < 0.9, tone[y, x]
    ys, xs = zip(*(at((-8.0 + 2.2 * math.cos(a), -8.0 + 2.2 * math.sin(a), 4.6)) for a in (0.0, 1.57, 3.14, 4.71)), strict=True)
    box = (slice(min(ys), max(ys) + 1), slice(min(xs), max(xs) + 1))
    assert alpha[box].max() < 0.05, alpha[box].max()
    assert {round(float(v), 2) for v in tone[crown][..., 0].ravel()} >= {0.8, 0.6}  # 草: its lit side and its shade
    # The planter it stands in is a made thing: lined as one.
    assert list(bpy.data.objects["tree_crown"]["nb_natural_slots"]) == [True, False]
    y, x = at((-8.7, -8.7, 0.9))
    assert alpha[y - 4 : y + 5, x - 4 : x + 5].max() > 0.9
    # The lot lies on the ground round it and casts no shadow of its own: no strip of shade along its edge, where
    # the town's ground begins (the town stands on that ground, just under the lot).
    assert around["levelM"] == -0.05 and {h["centreM"][2] for h in around["houses"]} == {-0.05}
    assert abs(min(v.co.z for v in houses.data.vertices) + 0.05) < 1e-6
    for along in (-10.0, -5.0, 5.0):
        y, x = at((-14.08, along, 0.0))
        if 2 <= y < alpha.shape[0] - 2 and 2 <= x < alpha.shape[1] - 2:
            assert tone[y - 2 : y + 3, x - 2 : x + 3, :3].min() > 0.99 or tone[y - 2 : y + 3, x - 2 : x + 3, 3].max() < 0.01
    # The house keeps its lines (its slab's near corner), and the town's houses have theirs and their tones.
    y, x = at((5.0, -1.0, 3.3))
    assert alpha[y - 4 : y + 5, x - 4 : x + 5].max() > 0.9
    seen = [
        h
        for h in around["houses"]
        if 0 <= at(h["centreM"][:2] + [h["sizeM"][2]])[0] < alpha.shape[0]
        and 0 <= at(h["centreM"][:2] + [h["sizeM"][2]])[1] < alpha.shape[1]
    ]
    assert seen
    inked = toned = 0
    for h in seen:
        corners = [at((x, y, z)) for x, y in rect(h) for z in (0.0, h["sizeM"][2])]
        area = (
            slice(max(0, min(c[0] for c in corners)), min(alpha.shape[0], max(c[0] for c in corners) + 1)),
            slice(max(0, min(c[1] for c in corners)), min(alpha.shape[1], max(c[1] for c in corners) + 1)),
        )
        inked += int((alpha[area] > 0.5).sum())
        toned += int(((tone[area][..., 3] > 0.5) & (tone[area][..., :3].max(axis=-1) < 0.8)).sum())
    assert inked > 50 and toned > 200, (inked, toned)
    # A wire between two poles is drawn: a black hair where it hangs (the lowest of them, the telephone cable, along
    # its sag).
    from name_blockout.blender.scene import TOWN_WIRES

    across, share, sag, _ = TOWN_WIRES[-1]
    poles = {p["id"]: p for p in around["poles"]}
    drawn = 0
    for wire in around["wires"]:
        a, b = (poles[i] for i in wire["poles"])
        for t in (0.2, 0.35, 0.5, 0.65, 0.8):
            point = [a["centreM"][i] + (b["centreM"][i] - a["centreM"][i]) * t + a["streetward"][i] * across for i in (0, 1)]
            y, x = at((*point, a["centreM"][2] + a["heightM"] * share - sag * 4 * t * (1 - t)))
            if 3 <= y < alpha.shape[0] - 3 and 3 <= x < alpha.shape[1] - 3:
                drawn += int(tone[y - 3 : y + 4, x - 3 : x + 4, :3].min() < 0.3)
    assert drawn, around["wires"]


@needs_blender
def test_a_town_stands_on_the_land_a_place_was_modelled_on(tmp_path):
    """A place whose ground goes out to the horizon (a plane 300 m across, 0.4 m up): that is land, not a lot, so
    the town stands on it, at its height, from just beyond the place's things."""
    from name_blockout.pipeline import run_blockout
    from name_blockout.town import rect

    _lot_from_above(tmp_path / "素材", half=150.0, tree=True)
    import bpy

    bpy.ops.wm.open_mainfile(filepath=str(tmp_path / "素材" / "lot.blend"))
    for obj in bpy.data.objects:
        obj.location.z += 0.4
    bpy.ops.wm.save_mainfile()
    data = json.loads((ROOT / "examples" / "develop" / "指示.json").read_text(encoding="utf-8"))
    data["folders"] = {"assets": "素材"}
    shot = data["shots"][0]
    shot["objects"], shot["figures"] = [], []
    shot["frame"] = {"boxMm": [17, 17, 110, 77], "dpi": 150, "shapeMm": [[20, 20], [107, 20], [107, 74], [20, 74]]}
    shot["ruler"] = {"points": 2, "horizonMm": [[20, 8], [107, 8]], "vanishingMm": [[150, 8], [-40, 8]]}
    shot["camera"] = {"heightM": 14.0, "positionM": [-30, -30, 14.0], "lensMm": 37}
    shot["place"] = {"asset": "家"}
    shot["surroundings"] = {"kind": "town", "seed": 4, "street": {"axis": "X", "atM": -20.0}}
    (tmp_path / "指示.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    r = run_blockout(tmp_path / "指示.json", log=lambda *_: None)[0]
    plan = json.loads((tmp_path / "blockout" / "panel1" / r["take"] / "plan.json").read_text(encoding="utf-8"))
    around = plan["surroundings"]
    assert around["street"] == {"axis": "X", "atM": -20.0, "widthM": 5.0}
    # From just outside the near band, beside and beyond the house and the tree (none among them, none before them
    # from the camera), not from the land's edge 170 m off.
    assert 25 < around["houses"][0]["distanceM"] < 80, around["houses"][0]
    origin = plan["camera"]["positionM"][:2]
    for house in around["houses"]:
        corners = rect(house)
        assert not (
            min(x for x, _ in corners) < 6.0
            and max(x for x, _ in corners) > -9.2
            and min(y for _, y in corners) < 8.0
            and max(y for _, y in corners) > -9.2
        )
        # The place's things are seen between 42° and 60° from the camera (from +X): a house in those directions is beyond them.
        for x, y in corners:
            if 42.0 < math.degrees(math.atan2(y - origin[1], x - origin[0])) < 60.0:
                assert math.hypot(x - origin[0], y - origin[1]) > 50.0, house
    for house in around["houses"]:
        on_land = all(-150 < x < 150 and -150 < y < 150 for x, y in rect(house))
        assert abs(house["centreM"][2] - (0.4 if on_land else 0.0)) < 2e-3, house  # off the land's edge: on the ground round it
    assert sum(h["centreM"][2] > 0.39 for h in around["houses"]) > 10
