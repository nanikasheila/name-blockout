# SPDX-License-Identifier: GPL-3.0-or-later
"""要求の点検: rule-based checks of what a shot's instruction says, before
anything is modelled. No AI: the same instruction gives the same findings.

Each finding has a code, a level (error: cannot be built as said / warn:
contradicts itself or its neighbours / info: left open, a guess will be
made), where it is, the words for people, and for the open ones a question
with choices. The AI (or the name tool) asks one or two at a time
(`pick_questions`), answers go to the requirement (requirement.py), and the
check runs again on what changed.
"""

from __future__ import annotations

from pathlib import Path

from .assets import allowed_licenses, license_problem, object_asset, read_assets
from .camera import DEFAULT_HEIGHT_M, CameraError, fit_camera, hint_differences
from .far import panorama_width_needed
from .imagesize import image_size
from .instruction import frame_of, pixels
from .look import KEY_LABELS, PLACES, indoor_words, lighting, norths_for_key, setting_of
from .materials import DEFAULT, LIBRARY, guess
from .plan import folder_of, instruction_dir, targets, vanishing_axes
from .sizes import usual_size
from .solve import DEFAULT_FIGURE_M, camera_height_from_figure, fit_box
from .vec import box_iou, point_line_distance

# Where an eye can be, indoors (floor to under the ceiling) and out (the ground to a high roof), in metres.
EYE_HEIGHTS = {"indoor": (0.1, 2.6), "outdoor": (0.05, 60.0)}
SETTING_WORDS = {"indoor": "屋内", "outdoor": "屋外"}

LEVELS = ("error", "warn", "info")
TIMES = ["dawn", "morning", "noon", "afternoon", "evening", "dusk", "night"]
TIME_LABELS = {"dawn": "明け方", "morning": "朝", "noon": "昼", "afternoon": "午後", "evening": "夕方", "dusk": "日暮れ", "night": "夜"}
WEATHER_LABELS = {"clear": "晴れ", "cloudy": "くもり", "overcast": "どんより", "rain": "雨", "snow": "雪", "fog": "霧", "haze": "かすみ"}


def finding(code, level, shot, path, message, question=None) -> dict:
    out = {"code": code, "level": level, "shot": shot["id"], "label": shot.get("label", shot["id"]), "path": path, "message": message}
    if question:
        out["question"] = question
    return out


def question(text: str, options: list[tuple[str, dict | None]], recommended: int = 0, why: str = "") -> dict:
    """A multiple-choice question: each option sets values (path → value) or nothing (おまかせ: the guess stands)."""
    return {
        "text": text,
        "options": [{"label": label, "set": values} for label, values in options],
        "recommended": recommended,
        **({"why": why} if why else {}),
    }


def check_shot(data: dict, shot: dict, base: Path | None = None) -> list[dict]:
    base = base or Path.cwd()
    out: list[dict] = []
    intent = shot.get("intent") or {}
    if intent.get("none"):
        return out
    frame = frame_of(shot["frame"])

    # --- the frame --------------------------------------------------------------------------
    given = shot["frame"].get("sizePx")
    if given and tuple(given) != pixels(frame.box, frame.dpi):
        out.append(
            finding(
                "frame.size",
                "error",
                shot,
                "frame.sizePx",
                f"絵の大きさ {given} が boxMm と dpi から計算した {list(pixels(frame.box, frame.dpi))} と合いません",
            )
        )

    # --- the ruler and the camera ------------------------------------------------------------
    ruler = shot.get("ruler")
    word = intent.get("camera")
    camera = None
    if not ruler or not ruler.get("horizonMm"):
        if not word:
            out.append(
                finding(
                    "camera.none",
                    "info",
                    shot,
                    "ruler",
                    "透視の定規もカメラの言葉もありません。目の高さのカメラで仮に組みます",
                    question(
                        "このコマのカメラは？",
                        [
                            ("目の高さ", {"intent.camera": "eye"}),
                            ("あおり（見上げ）", {"intent.camera": "low"}),
                            ("俯瞰（見下ろし）", {"intent.camera": "high"}),
                            ("おまかせ", None),
                        ],
                        0,
                        "定規があればそこから決まります。ネームで定規を引くのがいちばん確か",
                    ),
                )
            )
    else:
        points = int(ruler.get("points", 0))
        vanishing = ruler.get("vanishingMm") or []
        if points != len(vanishing):
            out.append(finding("ruler.count", "error", shot, "ruler.points", f"{points} 点透視なのに消失点が {len(vanishing)} 個あります"))
        a, b = ruler["horizonMm"]
        for i, v in enumerate(vanishing[:2]):
            off = point_line_distance(v, a, b)
            if off > 0.5:
                out.append(
                    finding(
                        "ruler.off-horizon",
                        "error",
                        shot,
                        f"ruler.vanishingMm/{i}",
                        f"消失点 {i + 1} がアイレベルから {off:.1f}mm 離れています（1・2 はアイレベルの上）",
                    )
                )
        try:
            camera = fit_camera(shot, frame)
        except CameraError as error:
            out.append(finding("camera.unsolvable", "error", shot, "ruler", str(error)))
        if camera:
            lens = camera.lens_mm
            if camera.lens_from_points and lens < 12:
                out.append(
                    finding(
                        "camera.wide",
                        "warn",
                        shot,
                        "ruler.vanishingMm",
                        f"消失点どうしが近く、レンズ {lens:.0f}mm の強い広角になります（端が大きくゆがむ）。消失点を離すと自然に",
                    )
                )
            if camera.lens_from_points and lens > 300:
                out.append(
                    finding(
                        "camera.tele",
                        "warn",
                        shot,
                        "ruler.vanishingMm",
                        f"消失点が遠く、レンズ {lens:.0f}mm の望遠になります（奥行きがつぶれる）",
                    )
                )
            rows = camera.horizon_rows()
            mid = (rows[0] + rows[1]) / 2 / frame.height
            looking = camera.tilt_deg
            if word == "low" and (mid < 0.4 or looking > 1):
                out.append(
                    finding(
                        "camera.word-low",
                        "warn",
                        shot,
                        "intent.camera",
                        f"「あおり」なのに、アイレベルがコマの上から {mid * 100:.0f}%{'・見下ろし' if looking > 1 else ''}です（あおりならアイレベルは下の方）",
                    )
                )
            if word == "high" and (mid > 0.6 or looking < -1):
                out.append(
                    finding(
                        "camera.word-high",
                        "warn",
                        shot,
                        "intent.camera",
                        f"「俯瞰」なのに、アイレベルがコマの上から {mid * 100:.0f}%{'・見上げ' if looking < -1 else ''}です（俯瞰ならアイレベルは上の方か外）",
                    )
                )
            for diff in hint_differences(camera, (shot.get("camera") or {}).get("hint")):
                out.append(
                    finding(
                        "camera.hint",
                        "error",
                        shot,
                        f"camera.hint.{diff['field']}",
                        f"指示を書いた道具のカメラの計算（{diff['field']} = {diff['hint']}）と、定規から name-blockout が計算した値（{diff['ours']}）が合いません",
                    )
                )
            axes = (shot.get("place") or {}).get("axes") or []
            if len(axes) >= 2 and camera.points >= 2:
                got = vanishing_axes(camera, targets(shot, frame)["vanishingPx"])[1]
                if got and got != axes[1]:
                    out.append(
                        finding(
                            "place.axes",
                            "error",
                            shot,
                            "place.axes/1",
                            f"消失点 2 の向きが場所の {axes[1]} と合いません（消失点 1 を {axes[0]} にすると、2 は {got}）",
                        )
                    )

    cam_cfg = shot.get("camera") or {}
    # --- the camera's height ----------------------------------------------------------------
    figures = shot.get("figures") or []
    if camera and "heightM" not in cam_cfg and "positionM" not in cam_cfg:
        setting, _ = setting_of(shot)
        low, high = EYE_HEIGHTS[setting]
        options = []
        odd = []  # estimates no eye could be at here (a 物 drawn small, or the eye level drawn off)
        for fig in figures:
            if fig.get("cut"):
                continue
            h = camera_height_from_figure(camera, frame.px_box(fig["shapeMm"]), float(fig.get("heightM") or DEFAULT_FIGURE_M))
            if h is not None and 0.05 < h < 200:
                source = f"人物「{fig.get('name') or fig['id']}」の大きさから"
                if low <= h <= high:
                    options.append((f"{round(h, 2)}m（{source}）", {"camera.heightM": round(h, 2)}))
                else:
                    odd.append((round(h, 2), source))
                break
        from_things = height_from_things(camera, shot, frame)
        if from_things is not None:
            h, names = from_things
            source = f"{'・'.join(names)}のふつうの大きさから"
            if low <= h <= high:
                options.append((f"{h}m（{source}）", {"camera.heightM": h}))
            else:
                odd.append((h, source))
        for h, source in odd:
            out.append(
                finding(
                    "camera.height-odd",
                    "warn",
                    shot,
                    "camera.heightM",
                    f"{source}だとカメラは {h}m になり、{SETTING_WORDS[setting]}の目の高さ（{low}〜{high}m）から外れます。"
                    "描いた大きさか、アイレベルの位置を確かめてください",
                )
            )
        hints = "、".join(label for label, _ in options)
        options += [
            ("1.5m（立った人の目）", {"camera.heightM": 1.5}),
            ("1.1m（座った人の目）", {"camera.heightM": 1.1}),
            ("0.3m（地面すれすれ）", {"camera.heightM": 0.3}),
            ("おまかせ", None),
        ]
        out.append(
            finding(
                "camera.height",
                "info",
                shot,
                "camera.heightM",
                f"カメラの高さが決まっていません。仮に {DEFAULT_HEIGHT_M}m で組みます" + (f"（目安: {hints}）" if hints else ""),
                question(
                    "カメラ（目）の高さは？",
                    options[:4],
                    0,
                    "アイレベル（地平線）はいつもカメラの高さを通ります。高さを変えると場の大きさが変わります",
                ),
            )
        )
    elif camera and cam_cfg.get("heightM") is not None:
        for fig in figures:
            if fig.get("cut"):
                continue
            height = float(fig.get("heightM") or DEFAULT_FIGURE_M)
            h = camera_height_from_figure(camera, frame.px_box(fig["shapeMm"]), height)
            given_h = float(cam_cfg["heightM"])
            if h is not None and abs(h - given_h) > max(0.15, 0.15 * given_h):
                out.append(
                    finding(
                        "figure.height",
                        "warn",
                        shot,
                        f"figures/{fig['id']}",
                        f"人物「{fig.get('name', fig['id'])}」（{height}m）の大きさからはカメラの高さ {h:.2f}m ですが、{given_h}m と指示されています（人物の頭の位置かカメラの高さが合わない）",
                        question(
                            f"「{fig.get('name', fig['id'])}」とカメラの高さ、どちらに合わせますか？",
                            [
                                (f"カメラを {h:.2f}m に", {"camera.heightM": round(h, 2)}),
                                (f"カメラは {given_h}m のまま（人物の大きさは描き直す）", None),
                            ],
                            0,
                        ),
                    )
                )

    # --- things -----------------------------------------------------------------------------
    box = (0.0, 0.0, frame.width, frame.height)
    assets_dir = folder_of(data, "assets", base)
    # All of them (also those whose license is not allowed: a shot naming one is told so, not that it is missing).
    assets, asset_problems = read_assets(assets_dir, usable_only=False) if assets_dir else ([], [])
    allowed = allowed_licenses(assets_dir) if assets_dir else frozenset()
    for problem in asset_problems:
        out.append(finding("assets.read", "warn", shot, "folders.assets", problem))
    named_assets = []
    for i, obj in enumerate(shot.get("objects") or []):
        region = frame.px_box(obj["shapeMm"])
        if box_iou(region, box) == 0:
            out.append(finding("object.outside", "warn", shot, f"objects/{i}", f"物「{obj['label']}」の範囲がコマの絵の外です"))
        if assets_dir and object_asset(obj, assets):
            named_assets.append((f"objects/{i}/asset", object_asset(obj, assets)))
        if obj.get("asset") and assets_dir and not object_asset(obj, assets):
            out.append(
                finding(
                    "object.asset",
                    "error",
                    shot,
                    f"objects/{i}/asset",
                    f"物「{obj['label']}」の素材「{obj['asset']}」が素材.json にありません",
                )
            )
        if camera and camera.mode == "level" and obj.get("onGround", True):
            rows = camera.horizon_rows()
            cx = (region[0] + region[2]) / 2
            horizon = rows[0] + (rows[1] - rows[0]) * cx / frame.width
            if region[3] < horizon - 1:
                out.append(
                    finding(
                        "object.above-horizon",
                        "warn",
                        shot,
                        f"objects/{i}",
                        f"物「{obj['label']}」の範囲がアイレベルより上で終わっています。地面に置く物ならアイレベルより下まで届くはず（宙の物なら onGround=false）",
                        question(
                            f"「{obj['label']}」は宙にある物？",
                            [
                                ("宙にある（看板・照明など）", {f"objects/{obj['id']}/onGround": False}),
                                ("地面に置く（範囲を描き直す）", None),
                            ],
                            0,
                        ),
                    )
                )

    # --- the place --------------------------------------------------------------------------
    place = shot.get("place") or {}
    if place.get("asset"):
        found = next((a for a in assets if a.kind == "place" and a.name == place["asset"]), None)
        if found:
            named_assets.append(("place.asset", found))
        if assets_dir and not found:
            out.append(finding("place.asset", "error", shot, "place.asset", f"場所「{place['asset']}」が素材.json にありません"))
        elif not cam_cfg.get("positionM"):
            out.append(
                finding(
                    "place.position",
                    "info",
                    shot,
                    "camera.positionM",
                    f"場所「{place['asset']}」の中のカメラの位置が決まっていません。Blockout は箱だけで組みます（開発では AI が場所の中に置きます）",
                )
            )
    elif not (intent.get("brief") or "").strip():
        places = [a.name for a in assets if a.kind == "place"]
        out.append(
            finding(
                "place.none",
                "info",
                shot,
                "place",
                "場所が決まっていません（素材も言葉もない）",
                question(
                    "このコマの場所は？", [(name, {"place.asset": name}) for name in places[:3]] + [("新しい場所（言葉で書く）", None)], 0
                )
                if places
                else None,
            )
        )

    # --- the far layers ---------------------------------------------------------------------
    for i, layer in enumerate(shot.get("far") or []):
        if layer.get("kind") != "panorama":
            continue
        found = next((a for a in assets if a.name == (layer.get("asset") or "")), None)
        if not layer.get("asset") or (assets_dir and not found):
            panoramas = [a.name for a in assets if a.kind == "panorama" and not license_problem(a, allowed)]
            out.append(
                finding(
                    "far.asset",
                    "warn",
                    shot,
                    f"far/{i}/asset",
                    f"遠景の全天球の画像「{layer.get('asset', '')}」が素材.json にありません（画像なしで組みます）",
                    question(
                        "遠景をどうしますか？",
                        [(name, {f"far/{i}/asset": name}) for name in panoramas[:3]] + [("全天球の画像なし（白い空のまま）", None)],
                        0,
                    )
                    if panoramas
                    else None,
                )
            )
            continue
        if found is None:
            continue
        if found.kind != "panorama":
            out.append(
                finding(
                    "far.asset",
                    "warn",
                    shot,
                    f"far/{i}/asset",
                    f"素材「{found.name}」は全天球の画像（kind panorama）ではありません（画像なしで組みます）",
                )
            )
            continue
        named_assets.append((f"far/{i}/asset", found))
        size = image_size(Path(assets_dir) / found.file) if assets_dir else None
        if size and camera:
            preview = float((shot.get("render") or {}).get("previewDpi") or 150.0)
            for name, dpi, level in (("下見", min(preview, frame.dpi), "warn"), ("本番", frame.dpi, "info")):
                need = panorama_width_needed(camera.focal_px * dpi / frame.dpi)
                if size[0] < need:
                    out.append(
                        finding(
                            "far.resolution",
                            level,
                            shot,
                            f"far/{i}/asset",
                            f"全天球の画像「{found.name}」は幅 {size[0]}px です。{name}（{dpi:g}dpi）でこのレンズなら幅 {need}px 要るので、遠景が粗く見えます",
                        )
                    )
                    break

    # --- the licenses of the 素材 this shot uses ------------------------------------------------
    for path, asset in named_assets:
        problem = license_problem(asset, allowed)
        if problem:
            out.append(finding("asset.license", "warn", shot, path, problem + "。代わりに箱（遠景なら画像なし）で組みます"))
        elif asset.license is None and (asset.by or "").upper() != "AI":
            out.append(
                finding(
                    "asset.license-unknown",
                    "info",
                    shot,
                    path,
                    f"素材「{asset.name}」のライセンスが書かれていません。自分で作ったものとして使います"
                    "（配布されている素材なら、素材.json に license と source を）",
                )
            )

    # --- the look (development) ---------------------------------------------------------------
    if shot.get("stage") == "develop":
        look = shot.get("look") or {}
        if not look.get("timeOfDay"):
            out.append(
                finding(
                    "look.time",
                    "warn",
                    shot,
                    "look.timeOfDay",
                    "開発（本番の作画）に進むのに、時間帯が決まっていません（光と影が決まらない）",
                    question(
                        "時間帯は？",
                        [
                            ("昼", {"look.timeOfDay": "noon"}),
                            ("夕方", {"look.timeOfDay": "evening"}),
                            ("夜", {"look.timeOfDay": "night"}),
                            ("朝", {"look.timeOfDay": "morning"}),
                        ],
                        0,
                    ),
                )
            )
        if not look.get("weather"):
            out.append(finding("look.weather", "info", shot, "look.weather", "天気が決まっていません。晴れで組みます"))
        out += _look_findings(shot, look, camera)
    return out


SEASONS = [("春分（3月21日）", "03-21"), ("夏至（6月21日）", "06-21"), ("秋分（9月23日）", "09-23"), ("冬至（12月22日）", "12-22")]


def _look_findings(shot: dict, look: dict, camera) -> list[dict]:
    """The development's look: what the light still needs (place, date, north), whether the sun comes from the side
    the author asked for, and the things without a material."""
    out = []
    word = look.get("timeOfDay")
    setting, _ = setting_of(shot)
    key = (look.get("light") or {}).get("key")
    if not look.get("setting"):
        words = indoor_words(shot)
        if words:
            out.append(
                finding(
                    "look.setting",
                    "info",
                    shot,
                    "look.setting",
                    f"屋内か屋外か決まっていません。{'・'.join(words[:3])} から屋内として、床と室内の明かりで組みます",
                    question("このコマは？", [("屋内", {"look.setting": "indoor"}), ("屋外", {"look.setting": "outdoor"})], 0),
                )
            )
    if setting == "indoor":
        if key not in ("window", "interior", "street", "front", "back", "side-left", "side-right", "top"):
            out.append(
                finding(
                    "look.indoor-key",
                    "info",
                    shot,
                    "look.light.key",
                    "屋内の明かりが決まっていません。天井の明かり（上からやわらかく）で照らします",
                    question(
                        "明かりは？",
                        [(KEY_LABELS[k], {"look.light.key": k}) for k in ("interior", "window", "street")],
                        0,
                    ),
                )
            )
        return out + _material_findings(shot, look)
    if word and word != "night":
        if not look.get("location"):
            out.append(
                finding(
                    "look.location",
                    "info",
                    shot,
                    "look.location",
                    "場所（緯度・経度）が決まっていません。東京で太陽の位置を出します",
                    question(
                        "どこの太陽？",
                        [(name, {"look.location": {"latDeg": lat, "lonDeg": lon}}) for name, (lat, lon) in PLACES.items()],
                        0,
                    ),
                )
            )
        if not look.get("date"):
            out.append(
                finding(
                    "look.date",
                    "info",
                    shot,
                    "look.date",
                    "日付（季節）が決まっていません。春分で太陽の高さを出します",
                    question("季節は？", [(label, {"look.date": value}) for label, value in SEASONS], 0),
                )
            )
    if camera is not None and (word or (look.get("light") or {}).get("key")):
        light, _ = lighting(look, camera.heading_deg)
        sun = light.get("sun")
        if sun and word and key in KEY_LABELS and key != "top" and sun["strength"] and sun["side"] != key:
            norths = norths_for_key(key, camera.heading_deg, sun["azimuthDeg"])
            out.append(
                finding(
                    "look.key",
                    "warn",
                    shot,
                    "look.north",
                    f"光は「{KEY_LABELS[key]}」の指示ですが、この時間・場所の向きでは太陽は{KEY_LABELS[sun['side']]}です",
                    question(
                        "どちらに合わせますか？",
                        [(f"北の向きを {n} に（太陽が{KEY_LABELS[key]}）", {"look.north": n}) for n in norths[:2]]
                        + [(f"太陽のまま（{KEY_LABELS[sun['side']]}）", None)],
                        0,
                    ),
                )
            )
        elif sun and word and not look.get("north") and sun["strength"]:
            options = []
            for side in ("side-right", "side-left", "back", "front"):
                found = norths_for_key(side, camera.heading_deg, sun["azimuthDeg"])
                if found and found[0] not in [o[1]["look.north"] for o in options]:
                    options.append((f"日差しを{KEY_LABELS[side]}", {"look.north": found[0]}))
            out.append(
                finding(
                    "look.north",
                    "info",
                    shot,
                    "look.north",
                    f"北の向きが決まっていません。+Y を北として、太陽は{KEY_LABELS[sun['side']]}です",
                    question("日差しはどちらから？", options[:4], 0) if options else None,
                )
            )
    return out + _material_findings(shot, look)


def _material_findings(shot: dict, look: dict) -> list[dict]:
    """Materials named that the library lacks, and the things without one."""
    out = []
    given = {m["target"]: m["material"] for m in (look.get("materials") or [])}
    for target, name in given.items():
        if name not in LIBRARY:
            out.append(
                finding(
                    "look.material-unknown",
                    "warn",
                    shot,
                    f"look.materials/{target}",
                    f"材質「{name}」はライブラリにありません（{'・'.join(LIBRARY)}）",
                )
            )
    open_things = [o for o in shot.get("objects") or [] if o["id"] not in given]
    if open_things:
        first = open_things[0]
        guessed = guess(first.get("label", "")) or DEFAULT
        others = [n for n in ("コンクリート", "木", "金属", "白壁") if n != guessed][:2]
        out.append(
            finding(
                "look.materials",
                "info",
                shot,
                "look.materials",
                "材質が決まっていない物: " + "・".join(f"{o['label']}（仮に{guess(o.get('label', '')) or DEFAULT}）" for o in open_things),
                question(
                    f"「{first['label']}」の材質は？",
                    [(name, {f"look.materials/{first['id']}": name}) for name in [guessed, *others]],
                    0,
                ),
            )
        )
    return out


def height_from_things(camera, shot: dict, frame):
    """The camera height that gives the marked things their usual sizes (the whole scene scales with it), if any have one."""
    import statistics

    ratios, names = [], []
    for obj in shot.get("objects") or []:
        usual = None if obj.get("sizeM") else usual_size(obj["label"])
        if not usual or not obj.get("onGround", True):
            continue
        placed = fit_box(camera, frame.px_box(obj["shapeMm"]), prior=usual)
        if placed.iou < 0.8:
            continue
        got = (placed.size[0] * placed.size[1] * placed.size[2]) ** (1 / 3)
        want = (usual[0] * usual[1] * usual[2]) ** (1 / 3)
        ratios.append(want / got)
        names.append(obj["label"])
    if not ratios:
        return None
    h = round(camera.position[2] * statistics.median(ratios), 2)
    return (h, names) if 0.05 < h < 500 else None


def check_sequence(data: dict) -> list[dict]:
    """Across shots: the same place next to each other should agree on its time and weather."""
    out = []
    shots = sorted(data["shots"], key=lambda s: (s.get("page", 0), s.get("order", 0)))
    for before, after in zip(shots, shots[1:]):
        pa, pb = (before.get("place") or {}).get("asset"), (after.get("place") or {}).get("asset")
        if not pa or pa != pb:
            continue
        la, lb = before.get("look") or {}, after.get("look") or {}
        for key, labels in (("timeOfDay", TIME_LABELS), ("weather", WEATHER_LABELS)):
            if la.get(key) and lb.get(key) and la[key] != lb[key]:
                out.append(
                    finding(
                        f"sequence.{key}",
                        "warn",
                        after,
                        f"look.{key}",
                        f"前のコマ（{before.get('label', before['id'])}）と同じ場所「{pa}」なのに、{'時間帯' if key == 'timeOfDay' else '天気'}が {labels.get(la[key], la[key])} → {labels.get(lb[key], lb[key])} です（時間が飛ぶなら構いません）",
                    )
                )
    return out


def check_instruction(data: dict, instruction_path=None) -> list[dict]:
    base = instruction_dir(instruction_path)
    out = []
    for shot in data["shots"]:
        out += check_shot(data, shot, base)
    out += check_sequence(data)
    order = {level: i for i, level in enumerate(LEVELS)}
    return sorted(out, key=lambda f: (order[f["level"]], data["shots"].index(next(s for s in data["shots"] if s["id"] == f["shot"]))))


def pick_questions(findings: list[dict], count: int = 2, answered: set[str] | None = None) -> list[dict]:
    """The next questions to ask (one or two at a time; errors and contradictions first; not what was answered)."""
    answered = answered or set()
    out = []
    for f in findings:
        if "question" not in f:
            continue
        key = f"{f['shot']}:{f['path']}"
        if key in answered:
            continue
        out.append({**f["question"], "shot": f["shot"], "label": f["label"], "path": f["path"], "code": f["code"]})
        if len(out) >= count:
            break
    return out


def is_buildable(findings: list[dict], shot_id: str) -> bool:
    return not any(f["level"] == "error" and f["shot"] == shot_id for f in findings)


__all__ = ["check_instruction", "check_shot", "check_sequence", "pick_questions", "is_buildable", "TIMES"]
