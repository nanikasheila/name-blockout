# SPDX-License-Identifier: GPL-3.0-or-later
"""The material library: each material pairs how it is in 3D with how a manga
draws it. A development render takes the light from the 3D side (which faces
are lit, where shadows fall) and draws with the manga side:

- tone: the screen tone of its lit faces (0 white … 1 black, as a density);
- shadowTone: of its faces in shadow (form and cast shadows);
- beta: drawn solid black (ベタ) instead of toned (dark paint, tyres, glass at night);
- lines: "outline" (only its edges) or "detail" (the pen goes into it: wood
  grain, tiles; for whoever finishes it, a note for now).

Things are matched to a material by look.materials (the author's), else by
the words of their names (GUESSES), else DEFAULT.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Material:
    name: str
    #: 3D: the base colour as a grey (0 black … 1 white) and how rough (0 mirror … 1 matte).
    grey: float
    roughness: float
    tone: float
    shadowTone: float
    beta: bool = False
    lines: str = "outline"
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


LIBRARY = {
    m.name: m
    for m in (
        Material("白壁", 0.85, 0.9, 0.0, 0.3, note="漆喰・白い塗装。光の面は白のまま、影だけトーン"),
        Material("コンクリート", 0.6, 0.9, 0.1, 0.4, lines="detail", note="打ち放しなら型枠の目地と穴を描き込む"),
        Material("木", 0.45, 0.7, 0.2, 0.5, lines="detail", note="木目を線で。板の継ぎ目"),
        Material("金属", 0.55, 0.3, 0.15, 0.5, note="映り込みは白抜きの帯で"),
        Material("トタン", 0.5, 0.6, 0.15, 0.45, lines="detail", note="波板の筋を線で"),
        Material(
            "ガラス",
            0.3,
            0.05,
            0.3,
            0.6,
            note="昼に外から見る窓は濃く、室内から見る窓は白く（seen）。映り込みの斜めの白抜き。夜は内側の明かり",
        ),
        Material("瓦", 0.35, 0.8, 0.35, 0.6, lines="detail", note="瓦の段を線で"),
        Material("アスファルト", 0.25, 0.95, 0.1, 0.4, note="白線は白抜き。一面を濃く塗らない"),
        Material("白地", 0.9, 1.0, 0.0, 0.25, note="地面・床は白地のまま、影だけ薄いトーン。目地や舗装の継ぎ目は線で"),
        Material("土", 0.4, 1.0, 0.2, 0.45),
        Material("草", 0.35, 1.0, 0.2, 0.4, lines="detail", note="草むらは線の束で、影はトーン"),
        Material("布", 0.6, 1.0, 0.1, 0.4, note="しわは線で"),
        Material("黒い塗装", 0.08, 0.3, 1.0, 1.0, beta=True, note="ベタ。映り込みはホワイトで"),
        Material("水", 0.3, 0.02, 0.2, 0.5, note="映り込みと波の線"),
    )
}
DEFAULT = "白壁"

#: Glass is as dark as what shows through it. By day from outside, the room behind it is dark: a dark tone, a
#: little darker in the shade (under the eaves), so a house's windows read as its dark shapes against the white
#: walls and roofs, and their black bars still stand out on them (a solid black would swallow the bars). By day
#: from inside, the daylight outside is the brightest thing in the room: almost
#: white. (At dawn, dusk and night the library's own tones stay: who lights which window is the author's to say.)
GLASS = "ガラス"
GLASS_BY_DAY = {"outdoor": (0.5, 0.6), "indoor": (0.05, 0.2)}
NO_DAYLIGHT = ("dawn", "dusk", "night")


def seen(material: dict, setting: str | None, time_of_day: str | None) -> dict:
    """A material's tones as they show in this light: glass by day by the side it is seen from; the rest as the
    library has them."""
    if material.get("name") != GLASS or material.get("beta") or time_of_day in NO_DAYLIGHT:
        return material
    tones = GLASS_BY_DAY.get(setting or "outdoor")
    return {**material, "tone": tones[0], "shadowTone": tones[1]} if tones else material


#: Words in a thing's name → a material (the longest word found wins).
GUESSES = {
    "家": "白壁",
    "建物": "コンクリート",
    "ビル": "コンクリート",
    "団地": "コンクリート",
    "壁": "白壁",
    "塀": "コンクリート",
    "倉庫": "トタン",
    "小屋": "木",
    "車": "黒い塗装",
    "バン": "黒い塗装",
    "タイヤ": "黒い塗装",
    "机": "木",
    "椅子": "木",
    "棚": "木",
    "ソファ": "布",
    "ベッド": "布",
    "窓": "ガラス",
    "道": "アスファルト",
    "道路": "アスファルト",
    "地面": "土",
    "草": "草",
    "芝": "草",
    "川": "水",
    "池": "水",
    "柵": "金属",
    "フェンス": "金属",
    "電柱": "コンクリート",
    "給水塔": "コンクリート",
    "屋根": "瓦",
    "床": "木",
    "テーブル": "木",
    "本棚": "木",
    "布団": "布",
    "カーテン": "布",
    "冷蔵庫": "金属",
    "テレビ": "黒い塗装",
}
GROUND = "ground"
#: A room's walls and ceiling (room.py).
WALLS = "walls"
#: The ground and a floor stay white (the shadows on them toned), as a manga's background leaves them: a whole
#: ground in a mid grey weighs the picture down and the things no longer stand out.
DEFAULT_GROUND = "白地"
DEFAULT_FLOOR = "白地"

#: Words in the names of a place's objects and their materials (a .blend made in English, often) → a material.
PLACE_WORDS = {
    "roof": "瓦",
    "tile": "瓦",
    "glass": "ガラス",
    "window": "ガラス",
    "tire": "黒い塗装",
    "tyre": "黒い塗装",
    "wheel": "黒い塗装",
    "rubber": "黒い塗装",
    "leaf": "草",
    "leaves": "草",
    "foliage": "草",
    "bush": "草",
    "hedge": "草",
    "canopy": "草",
    "crown": "草",
    "grass": "草",
    "lawn": "草",
    "plant": "草",
    "shrub": "草",
    "ivy": "草",
    "conifer": "草",
    "pine": "草",
    "trunk": "木",
    "bark": "木",
    "wood": "木",
    "timber": "木",
    "deck": "木",
    "concrete": "コンクリート",
    "stone": "コンクリート",
    "retaining": "コンクリート",
    "asphalt": "アスファルト",
    "metal": "金属",
    "steel": "金属",
    "rail": "金属",
    "fence": "金属",
    "solar": "ガラス",
    "water": "水",
    "fabric": "布",
    "cloth": "布",
    "sofa": "布",
    "curtain": "布",
    "葉": "草",
    "茂み": "草",
    "植栽": "草",
    "生垣": "草",
    "芝": "草",
}
#: The materials whose things are drawn by their outline only (the pen does not go into a crown's facets).
FOLIAGE = ("草",)
#: Words in the names of natural things in a place (besides whatever has leaves): told by their shade, not by an
#: outline (lines.py).
NATURAL_WORDS = ("tree", "trunk", "bark", "bush", "shrub", "hedge", "plant", "rock", "boulder", "木", "幹", "植栽", "岩")
#: Words of things too fine to draw line by line at a name's size (a solar panel's cells, a louvre): their outline
#: only, the rest left to the tone.
FINE_WORDS = ("solar", "louver", "louvre", "grating", "grille", "mesh", "ソーラー", "ルーバー")
#: Words of a solar panel: its cells drawn as a grid in its tone (develop.py).
CELL_WORDS = ("solar", "pv_panel", "photovoltaic", "ソーラー", "太陽光")


def guess_part(*names: str) -> str:
    """A place's part's material from its names (the object's, its material's): the longest word found, else DEFAULT."""
    text = " ".join(n for n in names if n).lower()
    found = [w for w in PLACE_WORDS if w in text]
    if found:
        return PLACE_WORDS[max(found, key=len)]
    return guess(" ".join(names)) or DEFAULT


def guess(label: str) -> str | None:
    found = [word for word in GUESSES if word in (label or "")]
    return GUESSES[max(found, key=len)] if found else None


def assign(shot: dict, setting: str = "outdoor", room: bool = False) -> tuple[dict[str, dict], list[dict]]:
    """Each thing's material (by id; the ground as "ground", a floor indoors; a room's walls and ceiling as "walls"),
    and what was guessed (as assumptions)."""
    given = {m["target"]: m["material"] for m in ((shot.get("look") or {}).get("materials") or [])}
    out: dict[str, dict] = {}
    assumed: list[dict] = []
    indoor = setting == "indoor"
    targets = [(o["id"], o.get("label", "")) for o in shot.get("objects") or []] + [(GROUND, "床" if indoor else "地面")]
    if room:
        targets.append((WALLS, "壁"))
    # Parts of a 素材 named by the author (a target that is no thing's id): as given, when the library has it.
    ids = {ident for ident, _ in targets}
    for target, name in given.items():
        if target not in ids and name in LIBRARY:
            out[target] = {**LIBRARY[name].as_dict(), "part": True}
    for ident, label in targets:
        name = given.get(ident)
        if name and name in LIBRARY:
            out[ident] = LIBRARY[name].as_dict()
            continue
        guessed = (DEFAULT_FLOOR if indoor else DEFAULT_GROUND) if ident == GROUND else (guess(label) or DEFAULT)
        out[ident] = LIBRARY[guessed].as_dict()
        why = f"材質「{name}」がライブラリにない" if name else "材質が決まっていない"
        assumed.append(
            {"path": f"look.materials/{ident}", "value": guessed, "by": "tool", "note": f"{label or ident}: {why}ので「{guessed}」"}
        )
    return out, assumed
