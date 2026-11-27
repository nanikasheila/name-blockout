# SPDX-License-Identifier: GPL-3.0-or-later
"""部品: the parts as numbers, the three views, and no part floating (synthetic)."""

import json
import random
import shutil
from pathlib import Path

import pytest

from name_blockout.cli import main
from name_blockout.instruction import read_instruction
from name_blockout.parts import TOUCH, assembly, floating_words, gap, table, three_views
from name_blockout.plan import build_develop_plan
from name_blockout.shapes import BUILDERS, KIND_LABELS, fit
from name_blockout.sizes import usual_size

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _box(name, c, s):
    return {"name": name, "c": list(c), "s": list(s)}


def test_a_part_stands_on_the_ground_or_on_one_that_does():
    legs = [_box("脚", (x, 0, 0.35), (0.05, 0.05, 0.7)) for x in (-0.5, 0.5)]
    top = _box("天板", (0, 0, 0.72), (1.2, 0.6, 0.04))
    vase = _box("花瓶", (0, 0, 0.84), (0.1, 0.1, 0.2))
    r = assembly(legs + [top, vase])
    assert r["pass"] and r["on"] == ["地面", "地面", "脚", "天板"]
    assert r["sizeM"] == [1.2, 0.6, 0.94]
    # The vase 2 cm over the table floats, and the lamp hung beside nothing too.
    r = assembly(legs + [top, _box("花瓶", (0, 0, 0.86), (0.1, 0.1, 0.2))])
    assert not r["pass"] and r["floating"][0]["name"] == "花瓶" and abs(r["floating"][0]["gapM"] - 0.02) < 1e-6
    assert r["floating"][0]["nearest"] == "天板"
    assert "花瓶" in floating_words("机", r)[0] and "2.0 cm" in floating_words("机", r)[0]
    assert gap(top, vase) == 0.0


@pytest.mark.parametrize("kind", sorted(BUILDERS))
def test_no_built_in_shape_has_a_floating_part(kind):
    """Every kind of shape, small and large, either way round: each part touches the ground or a part that does."""
    base = usual_size(KIND_LABELS[kind]) or (1.0, 1.0, 1.0)
    for k in (0.5, 0.7, 1.0, 1.6):
        for swap in (False, True):
            for seed in (1, 2, 3):
                w, d, h = (v * k for v in base)
                if swap:
                    w, d = d, w
                parts = fit(BUILDERS[kind](w, d, h, random.Random(seed)), w, d, h)
                r = assembly(parts)
                assert r["pass"], (kind, k, swap, seed, r["floating"][:3])
                assert all(abs(r["sizeM"][i] - (w, d, h)[i]) < 2 * TOUCH for i in range(3))


def test_the_table_and_the_three_views():
    parts = fit(BUILDERS["van"](4.7, 1.7, 1.95, random.Random(1)), 4.7, 1.7, 1.95)
    rows = table(parts)
    assert len(rows) == len(parts) and rows[0]["on"] and {"name", "sizeCm", "centreCm", "on"} <= set(rows[0])
    svg = three_views("バン", parts)
    assert svg == three_views("バン", parts)
    assert all(word in svg for word in ("正面", "側面", "上から", "470 cm", "170 cm", "195", "浮いている部品なし"))
    broken = parts + [_box("ふた", (0, 0, 3.0), (0.3, 0.3, 0.05))]
    assert "ふた」が浮いている" in three_views("バン", broken) and "stroke-dasharray" in three_views("バン", broken)


def test_parts_command_and_the_plan_s_note(tmp_path, capsys):
    shutil.copytree(EXAMPLES / "develop", tmp_path / "w")
    path = tmp_path / "w" / "指示.json"
    assert main(["parts", str(path)]) == 0
    said = capsys.readouterr().out
    assert "浮いている部品なし" in said
    files = sorted((tmp_path / "w" / "部品" / "panel1").glob("*"))
    assert [f.suffix for f in files] == [".json", ".svg", ".json", ".svg"]
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["pass"] and data["parts"] and data["format"] == "name-blockout/parts"
    # A shape the author wrote with a part in the air: the plan says so, and the command fails.
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["shots"][0]["objects"][0]["shape"] = {
        "unit": "box",
        "parts": [{"name": "台", "c": [0.5, 0.5, 0.2], "s": [1, 1, 0.4]}, {"name": "看板", "c": [0.5, 0.5, 0.9], "s": [0.6, 0.1, 0.2]}],
    }
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    data = read_instruction(path)
    plan = build_develop_plan(data, data["shots"][0], path)
    assert any("看板」が浮いている" in n for n in plan["notes"])
    assert main(["parts", str(path)]) == 1
    assert "看板」が浮いている" in capsys.readouterr().out
