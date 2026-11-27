# SPDX-License-Identifier: GPL-3.0-or-later
"""講評: the pack a critic who did not build the picture gets, and the answer that comes back."""

import json

import numpy as np
import pytest

from name_blockout.criteria import CRITERIA, all_criteria
from name_blockout.critique import (
    ANSWER_FILE,
    BRIEF_FILE,
    MAX_PROBLEMS,
    MAX_ROUNDS,
    NUMBERS_FILE,
    SHEET_FILE,
    CritiqueError,
    check_answer,
    make_pack,
    record_answer,
    rounds,
    side_by_side,
)

SHOT = {"id": "panel1", "label": "p1 コマ1"}


def _picture(black=()):
    p = np.ones((90, 150, 4), dtype=np.float32)
    for y0, y1, x0, x1 in black:
        p[y0:y1, x0:x1, :3] = 0.0
    return p


class Store:
    """Pictures kept in memory in place of Blender's loading and saving."""

    def __init__(self, pictures):
        self.pictures = dict(pictures)
        self.saved = {}

    def load(self, path):
        return self.pictures[path.name]

    def save(self, path, rgba):
        self.saved[path.name] = rgba
        path.write_bytes(b"png")
        return path


def _folder(tmp_path, take="1"):
    (tmp_path / "案" / "panel1" / take).mkdir(parents=True)
    (tmp_path / "案" / "panel1" / take / "完成.png").write_bytes(b"png")
    return tmp_path


def _problem(**fix):
    return {"where": "下段・右", "what": "黒がない", "fix": {"what": "黒の割合", "from": 0.02, "to": 0.06, "unit": "割合", **fix}}


def test_the_pack_holds_the_pictures_the_numbers_and_the_request(tmp_path):
    folder = _folder(tmp_path)
    reference = tmp_path / "参考.png"
    reference.write_bytes(b"png")
    store = Store({"完成.png": _picture([(0, 30, 0, 50)]), "参考.png": _picture([(0, 30, 0, 50), (60, 90, 100, 150)])})
    (folder / "blockout" / "panel1" / "1").mkdir(parents=True)
    (folder / "blockout" / "panel1" / "1" / "check.json").write_text(
        json.dumps({"checks": [{"name": "影の向き", "lines": {"foregroundM": 5.0, "widthsMm": {"near": {"median": 0.3}}}}]}),
        encoding="utf-8",
    )
    pack = make_pack(folder, SHOT, store.load, store.save, reference=reference)
    out = folder / "講評" / "panel1" / "1"
    assert pack["round"] == 1 and pack["take"] == "1"
    numbers = json.loads((out / NUMBERS_FILE).read_text(encoding="utf-8"))
    assert numbers["density"]["ratios"]["dark"] == 0.5 and not numbers["density"]["pass"]
    assert numbers["lines"]["foregroundM"] == 5.0
    assert pack["zooms"] == ["拡大_下右.png"] and "拡大_下右.png" in store.saved
    # A cell closer is large enough to read (a small take's pixels made larger, not a stamp).
    assert store.saved["拡大_下右.png"].shape[0] >= 600
    # The reference left, the take right, on one sheet.
    sheet = store.saved[SHEET_FILE]
    assert sheet.shape[1] > 300 and sheet[75, 140, 0] < 0.1 and sheet[75, sheet.shape[1] - 10, 0] > 0.9
    brief = (out / BRIEF_FILE).read_text(encoding="utf-8")
    assert "作った側ではありません" in brief and f"最大 {MAX_PROBLEMS} つ" in brief and "左が参考" in brief
    assert all(c["text"] in brief for c in CRITERIA)
    assert "拡大_下右.png" in brief


def test_without_a_reference_the_critic_reads_the_rules_alone(tmp_path):
    folder = _folder(tmp_path)
    (folder / "基準.md").write_text("# この作品の基準\n\n- 屋根瓦は 1 枚ずつ描かない\n1. 夜のコマは空にトーン\n", encoding="utf-8")
    store = Store({"完成.png": _picture([(0, 30, 0, 50)])})
    make_pack(folder, SHOT, store.load, store.save)
    brief = (folder / "講評" / "panel1" / "1" / BRIEF_FILE).read_text(encoding="utf-8")
    assert "参考の絵はありません" in brief and "屋根瓦は 1 枚ずつ描かない" in brief and "夜のコマは空にトーン" in brief
    assert [c["id"] for c in all_criteria(folder)][-2:] == ["work-1", "work-2"]


def test_an_answer_needs_numbers_and_at_most_five_problems():
    assert check_answer({"problems": []}) == []
    assert check_answer({"problems": [_problem()]}) == []
    assert any("最大" in w for w in check_answer({"problems": [_problem()] * (MAX_PROBLEMS + 1)}))
    assert any("数字" in w for w in check_answer({"problems": [_problem(to="もっと太く")]}))
    assert any("unit" in w for w in check_answer({"problems": [_problem(unit="")]}))
    assert any("where" in w for w in check_answer({"problems": [{**_problem(), "where": ""}]}))
    assert check_answer(["x"]) and check_answer({"problems": ["x"]})


def test_three_rounds_and_then_the_author(tmp_path):
    folder = _folder(tmp_path)
    store = Store({"完成.png": _picture()})
    answer = tmp_path / "答え.json"
    answer.write_text(json.dumps({"problems": [_problem()]}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CritiqueError):
        record_answer(folder, "panel1", answer)  # nothing was asked yet
    for number in range(1, MAX_ROUNDS + 1):
        assert make_pack(folder, SHOT, store.load, store.save)["round"] == number
        # Asking again before the answer makes the same round again.
        assert make_pack(folder, SHOT, store.load, store.save)["round"] == number
        got = record_answer(folder, "panel1", answer)
        assert got["round"] == number and got["next"] == ("fix" if number < MAX_ROUNDS else "author")
        assert (folder / "講評" / "panel1" / str(number) / ANSWER_FILE).exists()
    with pytest.raises(CritiqueError, match="作者に見せます"):
        make_pack(folder, SHOT, store.load, store.save)
    assert make_pack(folder, SHOT, store.load, store.save, more=True)["round"] == MAX_ROUNDS + 1
    assert [r["answered"] for r in rounds(folder, "panel1")] == [True, True, True, False]


def test_nothing_to_fix_ends_the_rounds_and_a_bad_answer_is_refused(tmp_path):
    folder = _folder(tmp_path)
    store = Store({"完成.png": _picture()})
    make_pack(folder, SHOT, store.load, store.save)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"problems": [_problem(to=None)]}), encoding="utf-8")
    with pytest.raises(CritiqueError, match="受け取れません"):
        record_answer(folder, "panel1", bad)
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"problems": []}), encoding="utf-8")
    assert record_answer(folder, "panel1", good)["next"] == "done"
    with pytest.raises(CritiqueError, match="直すところなし"):
        make_pack(folder, SHOT, store.load, store.save)


def test_no_picture_no_pack(tmp_path):
    store = Store({})
    with pytest.raises(CritiqueError, match="講評する絵がありません"):
        make_pack(tmp_path, SHOT, store.load, store.save)


def test_side_by_side_is_capped():
    sheet = side_by_side(np.ones((1000, 3000, 4), dtype=np.float32), np.zeros((500, 1500, 3), dtype=np.float32), max_px=1200)
    assert sheet.shape[1] <= 1200 and sheet.shape[2] == 4


def test_a_cold_reading_gets_the_picture_alone_and_nothing_of_the_work(tmp_path):
    """読み取り: a reader who knows nothing gets a folder with the picture and the questions only; what the
    instruction says is there is kept beside it, for comparing afterwards."""
    from name_blockout.reading import ALONE_DIR, INTENDED_FILE, PICTURE_FILE, QUESTIONS_FILE, ReadingError, intended, make_reading

    folder = tmp_path
    shot = {
        **SHOT,
        "intent": {"brief": "坂の上の家を見下ろす"},
        "place": {"asset": "坂の上の家"},
        "look": {"timeOfDay": "afternoon", "weather": "clear"},
        "surroundings": {"kind": "town"},
        "objects": [{"id": "o1", "label": "給水塔"}],
    }
    data = {"work": {"title": "例", "worldBrief": "舞台は日本の地方都市"}, "shots": [shot]}
    with pytest.raises(ReadingError, match="読み取る絵がありません"):
        make_reading(folder, data, shot)
    take = folder / "案" / "panel1" / "2"
    take.mkdir(parents=True)
    (take / "完成.png").write_bytes(b"picture")
    (folder / "基準.md").write_text("- この家のまわりは市街地\n", encoding="utf-8")
    made = make_reading(folder, data, shot)
    alone = folder / "読み取り" / "panel1" / "2" / ALONE_DIR
    assert made["take"] == "2" and sorted(p.name for p in alone.iterdir()) == sorted([PICTURE_FILE, QUESTIONS_FILE])
    assert (alone / PICTURE_FILE).read_bytes() == b"picture"
    # The questions tell nothing of the work: no place, no country, no time of day, no rule of the author's.
    asked = (alone / QUESTIONS_FILE).read_text(encoding="utf-8")
    for word in ("坂の上", "日本", "市街地", "午後", "給水塔", "例"):
        assert word not in asked.replace("例えば", ""), word
    assert "どこの国・地域" in asked and "5 段階" in asked
    # What it is compared with afterwards.
    assert (
        intended(data, shot, folder)
        == made["intended"]
        == [
            "作品の設定: 舞台は日本の地方都市",
            "このコマ: 坂の上の家を見下ろす",
            "場所: 坂の上の家",
            "時間帯・天気: 午後・晴れ",
            "場所のまわり: 市街地（日本の住宅街）",
            "物: 給水塔",
            "作品の基準: この家のまわりは市街地",
        ]
    )
    answers = (folder / "読み取り" / "panel1" / "2" / INTENDED_FILE).read_text(encoding="utf-8")
    assert "読み手には見せない" in answers and "- 場所のまわり: 市街地（日本の住宅街）" in answers
