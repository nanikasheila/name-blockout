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

from .assets import object_asset, read_assets
from .camera import DEFAULT_HEIGHT_M, CameraError, fit_camera, hint_differences
from .instruction import frame_of, pixels
from .plan import folder_of, instruction_dir, targets, vanishing_axes
from .sizes import usual_size
from .solve import DEFAULT_FIGURE_M, camera_height_from_figure, fit_box
from .vec import box_iou, point_line_distance

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
        options = []
        for fig in figures:
            if fig.get("cut"):
                continue
            h = camera_height_from_figure(camera, frame.px_box(fig["shapeMm"]), float(fig.get("heightM") or DEFAULT_FIGURE_M))
            if h is not None and 0.05 < h < 200:
                options.append((f"{round(h, 2)}m（人物「{fig.get('name') or fig['id']}」の大きさから）", {"camera.heightM": round(h, 2)}))
                break
        from_things = height_from_things(camera, shot, frame)
        if from_things is not None:
            h, names = from_things
            options.append((f"{h}m（{'・'.join(names)}のふつうの大きさから）", {"camera.heightM": h}))
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
    assets, asset_problems = read_assets(assets_dir) if assets_dir else ([], [])
    for problem in asset_problems:
        out.append(finding("assets.read", "warn", shot, "folders.assets", problem))
    for i, obj in enumerate(shot.get("objects") or []):
        region = frame.px_box(obj["shapeMm"])
        if box_iou(region, box) == 0:
            out.append(finding("object.outside", "warn", shot, f"objects/{i}", f"物「{obj['label']}」の範囲がコマの絵の外です"))
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
        if assets_dir and not any(a.kind == "place" and a.name == place["asset"] for a in assets):
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
