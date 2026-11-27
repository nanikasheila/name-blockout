# SPDX-License-Identifier: GPL-3.0-or-later
"""講評 (the critique): whoever built a picture does not grade it.

A take is handed to a critic who has seen nothing of how it was made: the picture beside its reference, the
numbers measured from both, and the author's rules. The critic returns at most five problems, each with where it
is, what is wrong and the fix as a number. The builder fixes, draws a new take and asks again; after three rounds
the picture goes to the author instead of round and round.

  講評/<コマ>/<回>/
    並べた絵.png   the reference (left) and the take (right); the take alone when there is no reference
    拡大_….png     the emptiest cells closer (a small take's pixels made larger)
    数字.json      the numbers (density.py; the lines' widths from check.json)
    依頼.md        what the critic is asked (fixed words: the same pack gives the same request)
    講評.json      the critic's answer, once it is recorded (critique --answer)
    round.json     which take, which reference

This module makes no pictures itself: `load` and `save` come from the caller (Blender's, in blender/picture.py).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import density
from .criteria import all_criteria
from .takes import TAKES_DIR, WORK_DIR

CRITIQUE_DIR = "講評"
SHEET_FILE = "並べた絵.png"
NUMBERS_FILE = "数字.json"
BRIEF_FILE = "依頼.md"
ANSWER_FILE = "講評.json"
ROUND_FILE = "round.json"
PICTURE = "完成"

#: A critic names at most this many problems (the ones that count), and a picture is fixed at most this many times.
MAX_PROBLEMS = 5
MAX_ROUNDS = 3
#: The sheet's widest side in pixels (a critic reads pictures of about this size; the cells closer keep the rest).
SHEET_MAX_PX = 2400
ZOOMS = 2
ZOOM_MIN_PX = 600
PAPER = 1.0
GAP_SHARE = 0.02


class CritiqueError(Exception):
    pass


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def rounds(folder: Path, shot_id: str) -> list[dict]:
    """The rounds so far, in order: {"round", "take", "answered", "problems"}."""
    root = Path(folder) / CRITIQUE_DIR / shot_id
    if not root.is_dir():
        return []
    out = []
    for path in sorted((p for p in root.iterdir() if p.name.isdigit() and (p / ROUND_FILE).exists()), key=lambda p: int(p.name)):
        info = _read(path / ROUND_FILE)
        answer = _read(path / ANSWER_FILE) if (path / ANSWER_FILE).exists() else None
        out.append(
            {
                "round": int(path.name),
                "take": info.get("take"),
                "answered": answer is not None,
                "problems": len(answer["problems"]) if answer else None,
            }
        )
    return out


def next_round(folder: Path, shot_id: str, more: bool = False) -> int:
    """The round a new pack is for: the last one again while it has no answer, else the one after it. After
    MAX_ROUNDS answered rounds the picture goes to the author (`more`: the author said to go on)."""
    done = rounds(folder, shot_id)
    if not done:
        return 1
    last = done[-1]
    if not last["answered"]:
        return last["round"]
    if last["problems"] == 0:
        raise CritiqueError(f"{last['round']} 回目の講評は「直すところなし」でした。もう一度講評するなら --more")
    if last["round"] >= MAX_ROUNDS and not more:
        raise CritiqueError(f"{MAX_ROUNDS} 回講評して直しました。ここからは作者に見せます（続けるなら --more）")
    return last["round"] + 1


def latest_take(folder: Path, shot_id: str) -> str | None:
    """The newest take of a shot that has a finished picture: the development's if there is one."""
    from .pipeline import last_built

    for mode in ("develop", "blockout"):
        built = last_built(folder, shot_id, mode)
        if built and (Path(folder) / TAKES_DIR / shot_id / str(built["take"]) / f"{PICTURE}.png").exists():
            return str(built["take"])
    root = Path(folder) / TAKES_DIR / shot_id
    if root.is_dir():
        takes = sorted((p for p in root.iterdir() if p.name.isdigit() and (p / f"{PICTURE}.png").exists()), key=lambda p: int(p.name))
        if takes:
            return takes[-1].name
    return None


def _lines_of(folder: Path, shot_id: str, take: str) -> dict | None:
    """What the development wrote about its lines (their widths per band), from the take's check.json."""
    path = Path(folder) / WORK_DIR / shot_id / take / "check.json"
    if not path.exists():
        return None
    for check in _read(path).get("checks", []):
        if isinstance(check.get("lines"), dict):
            return check["lines"]
    return None


def _rgb(picture: np.ndarray) -> np.ndarray:
    """A picture on white paper, as (h, w, 3)."""
    a = np.asarray(picture, dtype=np.float32)
    if a.ndim == 2:
        return np.repeat(a[..., None], 3, axis=2)
    rgb = a[..., :3]
    if a.shape[-1] == 4:
        rgb = rgb * a[..., 3:4] + (1.0 - a[..., 3:4])
    return np.clip(rgb, 0.0, 1.0)


def side_by_side(left: np.ndarray | None, right: np.ndarray, max_px: int = SHEET_MAX_PX) -> np.ndarray:
    """The reference (left) and the take (right) at the same height on white, a gap between; no wider than max_px."""
    pictures = [_rgb(p) for p in (left, right) if p is not None]
    h = min(p.shape[0] for p in pictures)
    pictures = [density.shrink(p, h, max(1, round(p.shape[1] * h / p.shape[0]))) for p in pictures]
    gap = max(2, round(pictures[0].shape[1] * GAP_SHARE)) if len(pictures) > 1 else 0
    width = sum(p.shape[1] for p in pictures) + gap
    if width > max_px:
        scale = max_px / width
        h = max(1, round(h * scale))
        pictures = [density.shrink(p, h, max(1, round(p.shape[1] * scale))) for p in pictures]
        gap = max(2, round(gap * scale)) if gap else 0
    sheet = np.full((h, sum(p.shape[1] for p in pictures) + gap, 4), PAPER, dtype=np.float32)
    x = 0
    for p in pictures:
        sheet[: p.shape[0], x : x + p.shape[1], :3] = p[:h]
        x += p.shape[1] + gap
    return sheet


def _cell(picture: np.ndarray, row: int, column: int) -> np.ndarray:
    """A grid cell of a picture, its pixels made larger (each one a square of pixels, nothing invented) until it
    is at least ZOOM_MIN_PX high: a cell of a small take is otherwise a stamp nobody can read a line's weight from."""
    y0, y1, x0, x1 = density.cell_box(picture.shape[:2], row, column)
    cell = picture[y0:y1, x0:x1]
    times = max(1, -(-ZOOM_MIN_PX // max(cell.shape[0], 1)))
    return np.repeat(np.repeat(cell, times, axis=0), times, axis=1) if times > 1 else cell


def brief(label: str, take: str, round_number: int, numbers: dict, criteria: list[dict], zooms: list[str]) -> str:
    """What the critic is asked, in fixed words."""
    has_reference = numbers.get("density", {}).get("reference") is not None
    lines = [
        f"# 講評の依頼（{label}・案{take}・{round_number} 回目）",
        "",
        "あなたは講評役です。この絵を作った側ではありません。どう作ったか、何に苦労したかは知らされませんし、考えに入れません。"
        "見るのは、このフォルダーの絵と数字だけです。",
        "",
        "## 見るもの",
        "",
    ]
    if has_reference:
        lines.append(f"- `{SHEET_FILE}`: 左が参考（作者が目安にしている絵）、右が今の絵。")
    else:
        lines.append(f"- `{SHEET_FILE}`: 今の絵（参考の絵はありません。下の基準だけで見ます）。")
    for name in zooms:
        lines.append(f"- `{name}`: 参考よりいちばん薄いマスの拡大（左が参考、右が今の絵）。")
    lines += [
        f"- `{NUMBERS_FILE}`: 絵を測った数字。`density` は黒（線とベタ）・トーン・白の割合と、絵を 3×3 のマスに分けた値"
        "（行は上から、列は左から）。"
        + (f"`ratios` は 今の絵 ÷ 参考 で、黒が {density.FAIL_UNDER} 未満のマスは `tooEmpty` に挙がっています。" if has_reference else "")
        + "`lines` は線の太さ（mm、距離帯ごとの中央値と 95%）と線の量です。",
        "",
        "## 基準（作者の言葉）",
        "",
    ]
    lines += [f"{i}. {c['text']}（`{c['id']}`）" for i, c in enumerate(criteria, 1)]
    lines += [
        "",
        "## 返すもの",
        "",
        f"このフォルダーに `{ANSWER_FILE}` を次の形で書いてください。",
        "",
        f"- 問題は **最大 {MAX_PROBLEMS} つ**、効く順に。褒め言葉や総評は要りません。直すところがなければ `problems` を空にします。",
        "- 問題ごとに「どこ」「何が」「数字での直し」。数字のない直し（「もっと良く」「少し太く」）は受け取りません。",
        "- `where`: マスの名前（上段・中段・下段 × 左・中・右）か、物の名前。",
        "- `criterion`: どの基準に反するか（上の括弧の中の id。基準にない問題なら省く）。",
        "- `fix.what`: 何を変えるか。`fix.from`: 今の値（数字にあればその値、なければ絵から見積もった値）。"
        "`fix.to`: 直した後の値。`fix.unit`: mm・%・倍・px・度・個 など。",
        "",
        "```json",
        json.dumps(
            {
                "problems": [
                    {
                        "where": "下段・右",
                        "what": "手前の地面が白いままで、参考にある草と影の黒がない",
                        "criterion": "realism",
                        "fix": {"what": "このマスの黒の割合", "from": 0.02, "to": 0.06, "unit": "割合"},
                    }
                ]
            },
            ensure_ascii=False,
            indent=1,
        ),
        "```",
        "",
    ]
    return "\n".join(lines)


def check_answer(data) -> list[str]:
    """What is wrong with a critic's answer (nothing: it can be recorded)."""
    if not isinstance(data, dict) or not isinstance(data.get("problems"), list):
        return ['{"problems": […]} の形ではありません']
    problems = data["problems"]
    out = []
    if len(problems) > MAX_PROBLEMS:
        out.append(f"問題が {len(problems)} 個あります（最大 {MAX_PROBLEMS} つ。効く順に絞ってください）")
    for i, p in enumerate(problems, 1):
        if not isinstance(p, dict):
            out.append(f"問題 {i}: 形が違います")
            continue
        for key in ("where", "what"):
            if not isinstance(p.get(key), str) or not p[key].strip():
                out.append(f"問題 {i}: {key} がありません")
        fix = p.get("fix")
        if not isinstance(fix, dict) or not isinstance(fix.get("what"), str) or not fix["what"].strip():
            out.append(f"問題 {i}: fix.what（何を変えるか）がありません")
            continue
        to = fix.get("to")
        if isinstance(to, bool) or not isinstance(to, (int, float)):
            out.append(f"問題 {i}: fix.to が数字ではありません（直しは数字で）")
        if "from" in fix and fix["from"] is not None and (isinstance(fix["from"], bool) or not isinstance(fix["from"], (int, float))):
            out.append(f"問題 {i}: fix.from が数字ではありません")
        if not isinstance(fix.get("unit"), str) or not fix["unit"].strip():
            out.append(f"問題 {i}: fix.unit（単位）がありません")
    return out


def record_answer(folder: Path, shot_id: str, answer_path: Path) -> dict:
    """Record the critic's answer in the open round (the last one made that has no answer yet)."""
    done = rounds(folder, shot_id)
    if not done:
        raise CritiqueError("講評の依頼がまだありません（先に critique で依頼を作る）")
    last = done[-1]
    target = Path(folder) / CRITIQUE_DIR / shot_id / str(last["round"]) / ANSWER_FILE
    answer_path = Path(answer_path)
    if last["answered"] and answer_path.resolve() != target.resolve():
        raise CritiqueError(f"{last['round']} 回目の講評はもう記録してあります（直した絵で critique をもう一度）")
    try:
        data = _read(answer_path)
    except (OSError, json.JSONDecodeError) as error:
        raise CritiqueError(f"講評を読めません: {error}") from error
    wrong = check_answer(data)
    if wrong:
        raise CritiqueError("講評を受け取れません:\n  " + "\n  ".join(wrong))
    if answer_path.resolve() != target.resolve():
        _write(target, data)
    left = MAX_ROUNDS - last["round"]
    return {
        "round": last["round"],
        "take": last["take"],
        "problems": data["problems"],
        "roundsLeft": max(0, left),
        "next": "done" if not data["problems"] else ("fix" if left > 0 else "author"),
    }


def make_pack(
    folder: Path,
    shot: dict,
    load: Callable[[Path], np.ndarray],
    save: Callable[[Path, np.ndarray], Path],
    take: str | None = None,
    reference: Path | None = None,
    more: bool = False,
) -> dict:
    """Make what a critic gets for a take: the pictures side by side, the numbers and the request."""
    folder = Path(folder)
    shot_id = shot["id"]
    take = take or latest_take(folder, shot_id)
    picture_path = folder / TAKES_DIR / shot_id / str(take) / f"{PICTURE}.png" if take else None
    if not picture_path or not picture_path.exists():
        raise CritiqueError(f"{shot.get('label', shot_id)}: 講評する絵がありません（先に develop か blockout で描く）")
    if reference is not None and not Path(reference).exists():
        raise CritiqueError(f"参考の絵がありません: {reference}")
    number = next_round(folder, shot_id, more)
    out = folder / CRITIQUE_DIR / shot_id / str(number)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        if old.is_file():
            old.unlink()

    mine = load(picture_path)
    theirs = load(Path(reference)) if reference is not None else None
    numbers: dict = {"shot": shot_id, "take": str(take), "round": number}
    zooms = []
    if theirs is not None:
        compared = density.compare(mine, theirs)
        numbers["density"] = compared
        if compared["sameFraming"]:
            for row, column in density.emptiest_cells(compared, ZOOMS):
                name = f"拡大_{density.ROWS[row]}{density.COLUMNS[column]}.png"
                save(out / name, side_by_side(_cell(_rgb(theirs), row, column), _cell(_rgb(mine), row, column)))
                zooms.append(name)
    else:
        numbers["density"] = {"take": density.measure(density.grey(mine)), "reference": None}
    lines = _lines_of(folder, shot_id, str(take))
    if lines:
        numbers["lines"] = lines
    save(out / SHEET_FILE, side_by_side(theirs, mine))
    _write(out / NUMBERS_FILE, numbers)
    criteria = all_criteria(folder)
    (out / BRIEF_FILE).write_text(brief(shot.get("label", shot_id), str(take), number, numbers, criteria, zooms), encoding="utf-8")
    _write(out / ROUND_FILE, {"round": number, "take": str(take), "reference": str(reference) if reference is not None else None})
    return {
        "shot": shot_id,
        "label": shot.get("label", shot_id),
        "take": str(take),
        "round": number,
        "folder": str(out),
        "brief": str(out / BRIEF_FILE),
        "sheet": str(out / SHEET_FILE),
        "zooms": zooms,
        "numbers": numbers,
    }
