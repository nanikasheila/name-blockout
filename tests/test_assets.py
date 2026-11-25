# SPDX-License-Identifier: GPL-3.0-or-later
"""素材.json: only 素材 free to use for work that is sold get in; what needs a credit says so."""

import json

from name_blockout.assets import license_id, read_assets


def write(folder, assets, **more):
    (folder / "素材.json").write_text(json.dumps({"assets": assets, **more}, ensure_ascii=False), encoding="utf-8")


def test_license_gate(tmp_path):
    write(
        tmp_path,
        [
            {"name": "空", "kind": "panorama", "file": "a.hdr", "license": "CC0"},
            {"name": "箱", "file": "b.blend", "license": "CC-BY-4.0", "author": "A", "source": "https://example.org/b"},
            {"name": "非商用", "file": "c.blend", "license": "CC-BY-NC-4.0"},
            {"name": "継承", "file": "d.blend", "license": "CC-BY-SA-4.0"},
            {"name": "自分の", "file": "e.blend"},
        ],
    )
    assets, problems = read_assets(tmp_path)
    assert [a.name for a in assets] == ["空", "箱", "自分の"]
    assert len(problems) == 2 and "CC-BY-NC-4.0" in problems[0]
    by = {a.name: a for a in assets}
    assert by["空"].kind == "panorama" and by["空"].license == "CC0-1.0" and not by["空"].needs_credit
    assert by["箱"].needs_credit and by["箱"].credit() == "「箱」 by A https://example.org/b (CC-BY-4.0)"
    everything, _ = read_assets(tmp_path, usable_only=False)
    assert len(everything) == 5


def test_allow_more_licenses(tmp_path):
    write(tmp_path, [{"name": "継承", "file": "d.blend", "license": "CC-BY-SA-4.0"}], allowLicenses=["CC-BY-SA-4.0"])
    assets, problems = read_assets(tmp_path)
    assert [a.name for a in assets] == ["継承"] and not problems


def test_license_words():
    assert license_id("CC BY 4.0") == "CC-BY-4.0"
    assert license_id("自作") == "own"
    assert license_id("MIT") == "MIT"
    assert license_id("") is None
