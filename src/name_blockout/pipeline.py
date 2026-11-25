# SPDX-License-Identifier: GPL-3.0-or-later
"""The design phase end to end for the shots of an instruction: check,
plan, build in Blender, measure, compare, draw out, and hand the take to
name-studio (案/ and 背景.json). Runs inside Blender (needs bpy)."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .checks import check_shot, is_buildable
from .instruction import read_instruction
from .look import KEY_LABELS
from .plan import build_develop_plan, build_plan, folder_of, instruction_dir
from .requirement import current, effective, read_requirement
from .scope import redo_scope
from .takes import TAKES_DIR, WORK_DIR, add_take, next_take
from .verify import summary_words, verify


def background_folder(data: dict, instruction_path: Path) -> Path:
    """The work folder: as the instruction says, else the one holding 依頼/<id>/ (where name-studio writes it), else beside it."""
    base = instruction_dir(instruction_path)
    given = folder_of(data, "background", base)
    if given:
        return given
    if base.parent.name == "依頼":
        return base.parent.parent
    return base


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def last_built(folder: Path, shot_id: str, mode: str = "blockout") -> dict | None:
    """What was built last for a shot in this mode (blockout / develop)."""
    root = folder / WORK_DIR / shot_id
    if not root.is_dir():
        return None
    takes = sorted((p for p in root.iterdir() if p.name.isdigit() and (p / "built.json").exists()), key=lambda p: int(p.name))
    for take in reversed(takes):
        built = json.loads((take / "built.json").read_text(encoding="utf-8"))
        if built.get("mode", "blockout") == mode:
            return built
    return None


TIME_WORDS = {"dawn": "明け方", "morning": "朝", "noon": "昼", "afternoon": "午後", "evening": "夕方", "dusk": "日暮れ", "night": "夜"}
WEATHER_WORDS = {"clear": "晴れ", "cloudy": "くもり", "overcast": "どんより", "rain": "雨", "snow": "雪", "fog": "霧", "haze": "かすみ"}


def light_words(light: dict) -> str:
    """The light in a few words: 夕方・晴れ・太陽は左から 12°."""
    parts = [TIME_WORDS.get(light.get("timeOfDay"), ""), WEATHER_WORDS.get(light.get("weather"), "")]
    sun = light.get("sun")
    if light.get("setting") == "indoor":
        parts = ["屋内", TIME_WORDS.get(light.get("timeOfDay"), "")]
        if sun and sun.get("strength"):
            parts.append(f"明かりは{KEY_LABELS.get(sun.get('side'), '')}")
        else:
            parts.append("明かりなし")
    elif sun and sun.get("strength"):
        parts.append(f"日差しは{KEY_LABELS.get(sun.get('side'), '')}・高さ {sun['elevationDeg']:.0f}°")
    elif light.get("timeOfDay"):
        parts.append("日差しなし")
    return "・".join(p for p in parts if p)


def run_blockout(
    instruction_path: str | Path,
    shots: list[str] | None = None,
    folder: str | Path | None = None,
    take: str | None = None,
    preview_dpi: float | None = None,
    force: bool = False,
    only_changed: bool = False,
    render: bool = True,
    log=print,
    develop: bool = False,
) -> list[dict]:
    """The design phase (Blockout) for the shots; with `develop`, the development: the same camera and layout, with
    the light and materials (by default only the shots whose stage is develop)."""
    import bpy

    from .blender import measure as bmeasure
    from .blender import render as brender
    from .blender import scene as bscene

    mode = "develop" if develop else "blockout"

    instruction_path = Path(instruction_path).resolve()
    data = read_instruction(instruction_path)
    folder = Path(folder).resolve() if folder else background_folder(data, instruction_path)
    request_id = (data.get("request") or {}).get("id")
    reports = []
    for raw in data["shots"]:
        if shots and raw["id"] not in shots:
            continue
        if develop and not shots and raw.get("stage") != "develop":
            continue
        label = raw.get("label", raw["id"])
        if (raw.get("intent") or {}).get("none"):
            reports.append({"shot": raw["id"], "label": label, "status": "skipped", "why": "背景なし"})
            continue
        req = read_requirement(folder, raw["id"])
        version = current(req)
        shot, replaced = effective(raw, (version or {}).get("answers", {}))
        findings = check_shot(data, shot, instruction_dir(instruction_path))
        if not is_buildable(findings, shot["id"]) and not force:
            reports.append(
                {"shot": shot["id"], "label": label, "status": "blocked", "findings": [f for f in findings if f["level"] == "error"]}
            )
            log(f"{label}: 点検でエラーがあるので組みません（--force で組む）")
            continue
        before = last_built(folder, shot["id"], mode)
        scope = redo_scope(before.get("shot") if before else None, shot)
        if only_changed and (scope["redo"] == "none" or (not develop and scope["redo"] != "design")):
            reports.append({"shot": shot["id"], "label": label, "status": "unchanged", "scope": scope})
            log(f"{label}: {'変更' if develop else '設計に関わる変更'}がないので組み直しません（{scope['redo']}）")
            continue
        started = time.time()
        plan = (build_develop_plan if develop else build_plan)(data, shot, instruction_path, preview_dpi)
        number = take or (shot.get("output") or {}).get("take") or next_take(folder, shot["id"])
        work = folder / WORK_DIR / shot["id"] / number
        takes_dir = folder / TAKES_DIR / shot["id"] / number
        built = bscene.build(plan)
        measured = bmeasure.measure(plan, built)
        result = verify(plan, measured)
        write_json(work / "plan.json", plan)
        write_json(work / "measured.json", measured)
        write_json(work / "check.json", result)
        files = {}
        if render and develop:
            from .blender import develop as bdevelop

            rendered, light_check = bdevelop.develop_passes(plan, built, work / "render")
            result["checks"].append({"name": "影の向き", "value": None, "unit": "words", **light_check})
            result["pass"] = result["pass"] and light_check["pass"]
            write_json(work / "check.json", result)
            takes_dir.mkdir(parents=True, exist_ok=True)
            for name, path in rendered.items():
                shutil.copyfile(path, takes_dir / f"{name}.png")
                files[name] = f"{TAKES_DIR}/{shot['id']}/{number}/{name}.png"
        elif render:
            rendered = brender.render_passes(plan, work / "render", passes=plan["render"]["passes"])
            takes_dir.mkdir(parents=True, exist_ok=True)
            for name, path in rendered.items():
                shutil.copyfile(path, takes_dir / f"{name}.png")
                files[name] = f"{TAKES_DIR}/{shot['id']}/{number}/{name}.png"
        bpy.ops.wm.save_as_mainfile(filepath=str(work / "scene.blend"), compress=True)
        assumed = "・".join(f"{a['path']}={a['value']}" for a in plan["assumptions"])
        head = (
            f"開発（光と材質、name-blockout）: {light_words(plan['develop']['lighting'])}"
            if develop
            else "Blockout（箱のあたり、name-blockout）"
        )
        note = f"{head}。{summary_words(result)}" + (f"。仮: {assumed}" if assumed else "")
        credits = [c["credit"] for c in plan.get("credits", []) if c.get("needsCredit")]
        if credits:
            note += "。クレジット: " + " / ".join(credits)
        if plan.get("credits"):
            write_json(work / "credits.json", plan["credits"])
            if render:
                write_json(takes_dir / "credits.json", plan["credits"])
        if files:
            add_take(
                folder,
                request_id,
                {
                    "panel": shot["id"],
                    "take": number,
                    "box": plan["frame"]["boxMm"],
                    "files": files,
                    "note": note,
                    **({"request": request_id} if request_id else {}),
                },
            )
        write_json(
            work / "built.json",
            {
                "shot": shot,
                "mode": mode,
                "requirementVersion": (version or {}).get("version"),
                "hashes": plan["hashes"],
                "take": number,
                "instruction": str(instruction_path),
                "seconds": round(time.time() - started, 2),
            },
        )
        report = {
            "shot": shot["id"],
            "label": label,
            "status": "built",
            "take": number,
            "pass": result["pass"],
            "scope": scope,
            "replacedAnswers": replaced,
            "check": str(work / "check.json"),
            "files": files,
            "note": note,
            "seconds": round(time.time() - started, 2),
        }
        reports.append(report)
        log(f"{label}: 案{number} {note}（{report['seconds']} 秒）")
    return reports
