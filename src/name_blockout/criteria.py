# SPDX-License-Identifier: GPL-3.0-or-later
"""What the author judges a background by: the rules a critic reads before looking at a take.

These are the author's own corrections, kept in their words. When the author corrects a picture, the correction
goes in here (for every work) or into the work's own 基準.md in its background folder (for that work only), so
that the next picture does not repeat the mistake. A critic gets both.
"""

from __future__ import annotations

from pathlib import Path

#: The work's own rules, in its background folder: one rule a line (lines starting with - or a number), in words.
FOLDER_FILE = "基準.md"

#: id, the rule, the day the author said it.
CRITERIA: tuple[dict, ...] = (
    {
        "id": "perspective",
        "text": "パースがネームと合っていること。あおりと俯瞰を逆にしない。",
        "since": "2026-11-26",
    },
    {
        "id": "not-boxes",
        "text": "ただの箱で済ませてよいのは Blockout まで。開発では、素材がなければ詳しい形を自分で作って置く。",
        "since": "2026-11-26",
    },
    {
        "id": "far",
        "text": "遠景があること。開発の絵が Blockout とほぼ変わらないのはだめ。",
        "since": "2026-11-26",
    },
    {
        "id": "realism",
        "text": "写実性を上げる。物が、それと分かる形と細かさを持つこと。",
        "since": "2026-11-26",
    },
    {
        "id": "line-is-boundary",
        "text": "線は境界。境界が深いほど太く、境界が浅いほど細い（ここでいう線はハッチングとは別）。",
        "since": "2026-11-26",
    },
    {
        "id": "near-by-shape",
        "text": "線を使えるのは、近景でオブジェクトをシェイプやシルエットで認識させたい場合。",
        "since": "2026-11-26",
    },
    {
        "id": "middle-by-negative-space",
        "text": "中景は、ネガティブスペースで描写したときに、描いているものが認識できるのが好ましい。",
        "since": "2026-11-26",
    },
    {
        "id": "far-without-lines",
        "text": "遠景は、線での表現はほぼなくなる。",
        "since": "2026-11-26",
    },
    {
        "id": "natural-by-shade",
        "text": "木のような自然物は、輪郭線ではなく陰での表現を優先する。",
        "since": "2026-11-27",
    },
    {
        "id": "reads-without-context",
        "text": "コンテキストがない状態で完成した絵を見たときに、何が描いてあるか十分に判断できること。",
        "since": "2026-11-28",
    },
    {
        "id": "townscape-of-the-setting",
        "text": "町並みは舞台の土地のものであること。舞台は日本なのに、住宅街の町並みが日本じゃないのはだめ。",
        "since": "2026-11-28",
    },
)


def folder_criteria(folder: Path | None) -> list[dict]:
    """The work's own rules from its 基準.md: every list line is one rule."""
    if not folder:
        return []
    path = Path(folder) / FOLDER_FILE
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith(("-", "・", "*")):
            text = line[1:].strip()
        elif line[:1].isdigit() and "." in line[:4]:
            text = line.split(".", 1)[1].strip()
        else:
            continue
        if text:
            out.append({"id": f"work-{len(out) + 1}", "text": text, "from": FOLDER_FILE})
    return out


def all_criteria(folder: Path | None = None) -> list[dict]:
    return [dict(c) for c in CRITERIA] + folder_criteria(folder)
