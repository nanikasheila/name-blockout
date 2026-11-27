# SPDX-License-Identifier: GPL-3.0-or-later
"""読み取り (the cold reading): can someone who knows nothing tell what a picture shows?

Whoever built a picture knows what is in it, and reads it into the picture; so does a critic who was handed the
instruction, the numbers and the rules. A reader of the manga has none of that. So before a picture goes to the
author, it is shown alone to a reader who knows nothing of the work (a fresh conversation), who says what they
see; what they could not tell, or told wrongly, against what the instruction says is there, is what the picture
fails to say.

  読み取り/<コマ>/<案>/
    絵だけ/絵.png     the finished picture, alone (its name says nothing)
    絵だけ/問い.md    what the reader is asked: fixed words, nothing about the work
    答え合わせ.md     what the instruction says is there; never shown to the reader, compared with the reading after

Only the folder 絵だけ goes to the reader. Nothing here needs Blender.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .checks import TIME_LABELS, WEATHER_LABELS
from .criteria import folder_criteria
from .critique import PICTURE, latest_take
from .takes import TAKES_DIR
from .town import KIND_LABELS

READING_DIR = "読み取り"
ALONE_DIR = "絵だけ"
PICTURE_FILE = "絵.png"
QUESTIONS_FILE = "問い.md"
INTENDED_FILE = "答え合わせ.md"

#: What the reader is asked. Nothing in it tells what the picture is of, where the story is set, or how the picture
#: was made.
QUESTIONS = """\
# 絵だけを見て答えてください

あなたは漫画の読者です。この絵が何の絵かは、何も知らされていません。同じフォルダーの「絵.png」（漫画の 1 コマの背景になる白黒の絵）だけを見て、絵から読み取れることを正直に書いてください。ほかのファイルは見ない。作った人の意図を調べない。推測は推測と書き、わからないものは「わからない」と書く。

1. ひとことで、何の絵か。
2. どこから見ているか（高さ・向き・見下ろしか見上げか）。
3. どこの国・地域の、どんな所に見えるか（都会・住宅地・郊外・山の中・海辺・一軒だけ建つ所 など）。そう読んだ手がかりは絵のどこか。
4. 手前・中ほど・奥に、それぞれ何があるか。1 つずつ、「何に見えるか」と確かさ（はっきり・たぶん・わからない）。
5. 灰色の塊や面、線の束で、何なのか判断できないもの・ほかの物に見えてしまうものを、絵のどの辺りか（左上・中央下 など）と一緒に全部挙げる。
6. 地面は何か（道・庭・土・舗装・水…）。どこが道でどこが敷地か、区別できるか。
7. 季節・天気・時間帯は読み取れるか。光はどちらから来ているか。
8. 奥行き（近い・遠い）は感じられるか。どこで感じて、どこで感じないか。
9. この絵だけを渡されて、上に人物を描き足して漫画の 1 コマに仕上げる人が、迷う所・足りない所を、困る順に最大 5 つ。

最後に、「この絵だけで、何が描いてあるか十分に判断できるか」を 5 段階（5 = 迷わず読める、1 = ほとんど読めない）で答え、理由を 2〜3 文で。
"""


class ReadingError(Exception):
    pass


def intended(data: dict, shot: dict, folder: Path | None = None) -> list[str]:
    """What the instruction says the picture shows, a line each: what a reading is compared with."""
    out = []
    world = (data.get("work") or {}).get("worldBrief")
    if world:
        out.append(f"作品の設定: {world}")
    brief = (shot.get("intent") or {}).get("brief")
    if brief:
        out.append(f"このコマ: {brief}")
    if (shot.get("place") or {}).get("asset"):
        out.append(f"場所: {shot['place']['asset']}")
    look = shot.get("look") or {}
    light = [labels[look[key]] for key, labels in (("timeOfDay", TIME_LABELS), ("weather", WEATHER_LABELS)) if look.get(key) in labels]
    if light:
        out.append("時間帯・天気: " + "・".join(light))
    around = (shot.get("surroundings") or {}).get("kind")
    if around in KIND_LABELS:
        out.append("場所のまわり: " + KIND_LABELS[around] + ("（日本の住宅街）" if around == "town" else ""))
    things = [o.get("label") or o["id"] for o in shot.get("objects") or []]
    if things:
        out.append("物: " + "・".join(things))
    far = [layer.get("kind") for layer in shot.get("far") or [] if layer.get("kind")]
    if far:
        out.append("遠景: " + "・".join(far))
    out += [f"作品の基準: {c['text']}" for c in folder_criteria(folder)]
    return out


def make_reading(folder: Path, data: dict, shot: dict, take: str | None = None) -> dict:
    """Make what a cold reader gets for a take (the picture alone and the questions), and beside it what the
    instruction says is there."""
    folder = Path(folder)
    shot_id = shot["id"]
    take = take or latest_take(folder, shot_id)
    picture = folder / TAKES_DIR / shot_id / str(take) / f"{PICTURE}.png" if take else None
    if not picture or not picture.exists():
        raise ReadingError(f"{shot.get('label', shot_id)}: 読み取る絵がありません（先に develop か blockout で描く）")
    out = folder / READING_DIR / shot_id / str(take)
    alone = out / ALONE_DIR
    alone.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(picture, alone / PICTURE_FILE)
    (alone / QUESTIONS_FILE).write_text(QUESTIONS, encoding="utf-8")
    lines = intended(data, shot, folder)
    words = "# 答え合わせ（読み手には見せない）\n\n指示書では、この絵はこうです。読み取りと食い違う所・読み手が判断できなかった所が、絵が伝えていない所です。\n\n"
    (out / INTENDED_FILE).write_text(words + "".join(f"- {line}\n" for line in lines), encoding="utf-8")
    return {
        "shot": shot_id,
        "label": shot.get("label", shot_id),
        "take": str(take),
        "folder": str(out),
        "alone": str(alone),
        "picture": str(alone / PICTURE_FILE),
        "questions": str(alone / QUESTIONS_FILE),
        "intended": lines,
    }
