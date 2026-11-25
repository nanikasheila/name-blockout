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
from .plan import build_plan, folder_of, instruction_dir
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


def last_built(folder: Path, shot_id: str) -> dict | None:
    root = folder / WORK_DIR / shot_id
    if not root.is_dir():
        return None
    takes = sorted((p for p in root.iterdir() if p.name.isdigit() and (p / "built.json").exists()), key=lambda p: int(p.name))
    return json.loads((takes[-1] / "built.json").read_text(encoding="utf-8")) if takes else None


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
) -> list[dict]:
    import bpy

    from .blender import measure as bmeasure
    from .blender import render as brender
    from .blender import scene as bscene

    instruction_path = Path(instruction_path).resolve()
    data = read_instruction(instruction_path)
    folder = Path(folder).resolve() if folder else background_folder(data, instruction_path)
    request_id = (data.get("request") or {}).get("id")
    reports = []
    for raw in data["shots"]:
        if shots and raw["id"] not in shots:
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
        before = last_built(folder, shot["id"])
        scope = redo_scope(before.get("shot") if before else None, shot)
        if only_changed and scope["redo"] != "design":
            reports.append({"shot": shot["id"], "label": label, "status": "unchanged", "scope": scope})
            log(f"{label}: 設計に関わる変更がないので組み直しません（{scope['redo']}）")
            continue
        started = time.time()
        plan = build_plan(data, shot, instruction_path, preview_dpi)
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
        if render:
            rendered = brender.render_passes(plan, work / "render")
            takes_dir.mkdir(parents=True, exist_ok=True)
            for name, path in rendered.items():
                shutil.copyfile(path, takes_dir / f"{name}.png")
                files[name] = f"{TAKES_DIR}/{shot['id']}/{number}/{name}.png"
        bpy.ops.wm.save_as_mainfile(filepath=str(work / "scene.blend"), compress=True)
        assumed = "・".join(f"{a['path']}={a['value']}" for a in plan["assumptions"])
        note = f"Blockout（箱のあたり、name-blockout）。{summary_words(result)}" + (f"。仮: {assumed}" if assumed else "")
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
