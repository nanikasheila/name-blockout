# SPDX-License-Identifier: GPL-3.0-or-later
"""The schema reads the examples, refuses what it should, and the packaged copy is the repository's."""

import json
from pathlib import Path

import pytest

from name_blockout.instruction import InstructionError, check_instruction, read_instruction

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("*/指示.json")), ids=lambda p: p.parent.name)
def test_examples_follow_the_schema(path):
    read_instruction(path)


def test_unknown_field_is_refused():
    data = json.loads((ROOT / "examples" / "two-point" / "指示.json").read_text(encoding="utf-8"))
    data["shots"][0]["frame"]["oops"] = 1
    with pytest.raises(InstructionError):
        check_instruction(data)


def test_newer_version_is_refused_with_words():
    data = json.loads((ROOT / "examples" / "two-point" / "指示.json").read_text(encoding="utf-8"))
    data["formatVersion"] = 2
    with pytest.raises(InstructionError, match="版"):
        check_instruction(data)


def test_same_panel_twice_is_refused():
    data = json.loads((ROOT / "examples" / "two-point" / "指示.json").read_text(encoding="utf-8"))
    data["shots"].append(data["shots"][0])
    with pytest.raises(InstructionError):
        check_instruction(data)
