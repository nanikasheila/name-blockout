# SPDX-License-Identifier: GPL-3.0-or-later
"""Usual sizes of things a manga background shows, by the words of their names.

Only a hint for a box whose size was not given: the box still fills what the
author marked, but among the boxes that do, the one nearest these
proportions (and size) is taken, so a sofa does not come out as a flat board.
[width, depth, height] in metres, width being the side that runs to the
thing's vanishing point.
"""

from __future__ import annotations

SIZES: list[tuple[tuple[str, ...], tuple[float, float, float]]] = [
    (("ビル", "マンション", "団地"), (30.0, 15.0, 30.0)),
    (("家", "住宅", "屋敷", "豪邸", "建物", "建屋", "校舎", "店"), (12.0, 9.0, 7.0)),
    (("倉庫", "工場"), (30.0, 20.0, 10.0)),
    (("小屋", "物置"), (3.0, 2.5, 2.5)),
    (("バス", "トラック"), (10.0, 2.5, 3.2)),
    (("バン", "ワゴン"), (4.8, 1.9, 1.9)),
    (("車", "自動車", "タクシー"), (4.5, 1.8, 1.5)),
    (("自転車", "バイク"), (1.8, 0.6, 1.1)),
    (("電柱", "街灯"), (0.3, 0.3, 9.0)),
    (("木", "樹"), (4.0, 4.0, 7.0)),
    (("塀", "壁", "フェンス"), (6.0, 0.2, 1.8)),
    (("門",), (4.0, 0.5, 2.5)),
    (("ドア", "扉", "玄関"), (0.9, 0.1, 2.0)),
    (("窓",), (1.6, 0.1, 1.2)),
    (("ソファ", "ソファー"), (2.0, 0.9, 0.8)),
    (("ベッド",), (2.0, 1.0, 0.5)),
    (("机", "デスク", "テーブル", "食卓"), (1.2, 0.7, 0.72)),
    (("椅子", "いす", "イス"), (0.45, 0.5, 0.85)),
    (("棚", "本棚", "書棚", "ロッカー"), (0.9, 0.4, 1.8)),
    (("冷蔵庫",), (0.7, 0.7, 1.8)),
    (("テレビ", "画面", "モニター", "スクリーン"), (1.4, 0.1, 0.8)),
    (("黒板", "ホワイトボード"), (3.6, 0.1, 1.2)),
    (("箱", "段ボール"), (0.5, 0.4, 0.4)),
    (("階段",), (1.2, 3.0, 2.8)),
    (("自販機", "自動販売機"), (1.0, 0.8, 1.8)),
    (("ベンチ",), (1.6, 0.5, 0.8)),
]


def usual_size(label: str) -> tuple[float, float, float] | None:
    """The usual size for a name (the longest word it contains), if any."""
    best, best_len = None, 0
    for words, size in SIZES:
        for word in words:
            if word in label and len(word) > best_len:
                best, best_len = size, len(word)
    return best
