# SPDX-License-Identifier: GPL-3.0-or-later
"""name-blockout's commands (python -m name_blockout …, or inside Blender through blender/run.py).

  validate  <指示.json>                    the instruction follows the schema
  check     <指示.json> [--questions N]     要求の点検: what is missing or contradicts, and the next questions
  camera    <指示.json> [--shot ID]         the camera each ruler gives (and how it compares with the name tool's)
  plan      <指示.json> --shot ID           the Blockout plan as data (no Blender)
  answer    <指示.json> --shot ID --set path=value …   answer a question (要求/<ID>.json)
  confirm   <指示.json> --shot ID           confirm the requirement (a new version when it changed)
  scope     <指示.json> --shot ID           what a rebuild would redo (design / develop / none)
  blockout  <指示.json> [--shot ID …]       build, check in numbers and draw the Blockout (needs Blender)
  develop   <指示.json> [--shot ID …]       the development: the same layout with light and materials (needs Blender)
  materials                               the material library (3D and how a manga draws it)

Commands print JSON with --json; otherwise words for people.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .camera import CameraError, fit_camera, hint_differences
from .checks import check_instruction, pick_questions
from .instruction import InstructionError, find_shot, frame_of, read_instruction
from .plan import build_plan, instruction_dir


def _print(value, as_json: bool, words=None):
    if as_json or words is None:
        print(json.dumps(value, ensure_ascii=False, indent=1))
    else:
        print(words)


def _values(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        if not key or not _:
            raise SystemExit(f"--set は path=value の形で: {pair}")
        try:
            out[key] = json.loads(raw)
        except json.JSONDecodeError:
            out[key] = raw
    return out


def full_speed(child: subprocess.Popen) -> bool:
    """On Windows, keep the Blender we started out of power throttling (EcoQoS): a background process without a
    window may be put on the efficiency cores at a low clock, and draws 2–3 times slower. Elsewhere nothing."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class Throttling(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

        process_power_throttling = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
        execution_speed = 0x1  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        state = Throttling(1, execution_speed, 0)  # controlled, and off
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = wintypes.HANDLE(int(child._handle))  # type: ignore[attr-defined]
        return bool(kernel32.SetProcessInformation(handle, process_power_throttling, ctypes.byref(state), ctypes.sizeof(state)))
    except (OSError, AttributeError, ValueError):
        return False


def find_blender() -> str | None:
    """Blender's program: NAME_BLOCKOUT_BLENDER, then on PATH, then the usual place on Windows (the newest)."""
    given = os.environ.get("NAME_BLOCKOUT_BLENDER")
    if given and Path(given).exists():
        return given
    found = shutil.which("blender")
    if found:
        return found
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation"
    if root.is_dir():
        candidates = sorted(
            root.glob("Blender */blender.exe"), key=lambda p: [int(x) if x.isdigit() else x for x in p.parent.name.split()[-1].split(".")]
        )
        if candidates:
            return str(candidates[-1])
    return None


def _has_bpy() -> bool:
    try:
        import bpy  # noqa: F401
    except ImportError:
        return False
    return True


def cmd_validate(a) -> int:
    data = read_instruction(a.instruction)
    _print({"ok": True, "shots": [s["id"] for s in data["shots"]]}, a.json, f"OK（コマ {len(data['shots'])} 個）")
    return 0


def cmd_check(a) -> int:
    from .pipeline import background_folder
    from .requirement import answered

    data = read_instruction(a.instruction)
    findings = check_instruction(data, a.instruction)
    questions = pick_questions(findings, a.questions, answered(data, background_folder(data, Path(a.instruction).resolve())))
    if a.json:
        _print({"findings": findings, "questions": questions}, True)
    else:
        marks = {"error": "✗", "warn": "!", "info": "・"}
        for f in findings:
            print(f"{marks[f['level']]} {f['label']} {f['path']}: {f['message']}")
        if not findings:
            print("点検: 問題なし")
        for q in questions:
            print(f"\n? {q['label']}: {q['text']}")
            for i, o in enumerate(q["options"]):
                print(f"  {i + 1}. {o['label']}{'（おすすめ）' if i == q['recommended'] else ''}")
    return 1 if any(f["level"] == "error" for f in findings) else 0


def cmd_camera(a) -> int:
    data = read_instruction(a.instruction)
    out = []
    for shot in data["shots"]:
        if a.shot and shot["id"] not in a.shot:
            continue
        try:
            camera = fit_camera(shot, frame_of(shot["frame"]))
        except CameraError as error:
            out.append({"shot": shot["id"], "error": str(error)})
            continue
        if camera is None:
            out.append({"shot": shot["id"], "camera": None})
            continue
        out.append(
            {
                "shot": shot["id"],
                "camera": camera.summary(),
                "hintDifferences": hint_differences(camera, (shot.get("camera") or {}).get("hint")),
            }
        )
    _print(out, True)
    return 1 if any(o.get("error") or o.get("hintDifferences") for o in out) else 0


def cmd_plan(a) -> int:
    data = read_instruction(a.instruction)
    shot = find_shot(data, a.shot)
    plan = build_plan(data, shot, a.instruction, a.dpi)
    text = json.dumps(plan, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def _folder(a, data) -> Path:
    from .pipeline import background_folder

    return Path(a.folder) if a.folder else background_folder(data, Path(a.instruction).resolve())


def cmd_answer(a) -> int:
    from .requirement import answer

    data = read_instruction(a.instruction)
    shot = find_shot(data, a.shot)
    version = answer(_folder(a, data), shot, _values(a.set), by=a.by)
    _print(version, a.json, f"{shot.get('label', shot['id'])}: 要求の版 {version['version']}（下書き）に {', '.join(a.set)}")
    return 0


def cmd_confirm(a) -> int:
    from .requirement import confirm

    data = read_instruction(a.instruction)
    shot = find_shot(data, a.shot)
    version = confirm(_folder(a, data), shot)
    _print(version, a.json, f"{shot.get('label', shot['id'])}: 要求の版 {version['version']} を確定")
    return 0


def cmd_scope(a) -> int:
    from .pipeline import last_built
    from .requirement import current, effective, read_requirement
    from .scope import redo_scope

    data = read_instruction(a.instruction)
    folder = _folder(a, data)
    shot = find_shot(data, a.shot)
    version = current(read_requirement(folder, shot["id"]))
    shot_now, replaced = effective(shot, (version or {}).get("answers", {}))
    before = last_built(folder, shot["id"])
    scope = redo_scope(before.get("shot") if before else None, shot_now)
    words = {"design": "設計（Blockout）から組み直す", "develop": "開発（見た目）だけやり直す", "none": "やり直しなし"}[scope["redo"]]
    _print(
        {**scope, "replacedAnswers": replaced},
        a.json,
        f"{shot.get('label', shot['id'])}: {words}（変わった所: {', '.join(scope['changed']) or 'なし'}）",
    )
    return 0


def cmd_blockout(a) -> int:
    if not _has_bpy():
        blender = a.blender or find_blender()
        if not blender:
            print("Blender が見つかりません（--blender か NAME_BLOCKOUT_BLENDER で場所を指定）", file=sys.stderr)
            return 2
        run = Path(__file__).resolve().parent / "blender" / "run.py"
        argv = [blender, "-b", "--factory-startup", "--python", str(run), "--"] + a.raw
        child = subprocess.Popen(argv)
        full_speed(child)
        return child.wait()
    from .pipeline import run_blockout

    reports = run_blockout(
        a.instruction,
        shots=a.shot,
        folder=a.folder,
        take=a.take,
        preview_dpi=a.dpi,
        force=a.force,
        only_changed=a.only_changed,
        render=not a.no_render,
        log=(lambda *_: None) if a.json else print,
        develop=a.command == "develop",
    )
    if a.json:
        _print(reports, True)
    built = [r for r in reports if r["status"] == "built"]
    return 0 if built and all(r["pass"] for r in built) and not any(r["status"] == "blocked" for r in reports) else 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="name-blockout", description="ネームの指示から Blender で背景の Blockout を組み、数値で確かめる")
    p.add_argument("--version", action="version", version=f"name-blockout {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def command(name, func, help_):
        c = sub.add_parser(name, help=help_)
        c.add_argument("instruction", help="指示書（指示.json）")
        c.add_argument("--json", action="store_true", help="結果を JSON で")
        c.set_defaults(func=func)
        return c

    command("validate", cmd_validate, "指示書がスキーマどおりか")
    c = command("check", cmd_check, "要求の点検と次の質問")
    c.add_argument("--questions", type=int, default=2, help="一度に出す質問の数（既定 2）")
    c = command("camera", cmd_camera, "定規から決まるカメラ")
    c.add_argument("--shot", action="append")
    c = command("plan", cmd_plan, "Blockout の組み立てをデータで")
    c.add_argument("--shot", required=True)
    c.add_argument("--dpi", type=float)
    c.add_argument("--out")
    for name, func, help_ in (
        ("answer", cmd_answer, "質問に答える"),
        ("confirm", cmd_confirm, "要求を確定する"),
        ("scope", cmd_scope, "やり直す範囲"),
    ):
        c = command(name, func, help_)
        c.add_argument("--shot", required=True)
        c.add_argument("--folder", help="作業フォルダー（既定: 指示書から）")
        if name == "answer":
            c.add_argument("--set", action="append", required=True, help="path=value（値は JSON か文字）")
            c.add_argument("--by", default="author", choices=["author", "ai", "tool"])
    for name, help_, dpi in (
        ("blockout", "Blockout を組んで照合し描き出す（Blender）", "既定 150"),
        ("develop", "開発: 同じ配置に光と材質（既定: stage が develop のコマ、Blender）", "既定 300、指示の dpi まで"),
    ):
        c = command(name, cmd_blockout, help_)
        c.add_argument("--shot", action="append", help="このコマだけ（何度でも）")
        c.add_argument("--folder", help="作業フォルダー（既定: 指示書から）")
        c.add_argument("--take", help="案の番号（既定: 次の番号）")
        c.add_argument("--dpi", type=float, help=f"描き出す解像度（{dpi}）")
        c.add_argument("--force", action="store_true", help="点検のエラーがあっても組む")
        c.add_argument("--only-changed", action="store_true", help="前に組んだときから変わったコマだけ")
        c.add_argument("--no-render", action="store_true", help="組んで照合するだけ（描き出さない）")
        c.add_argument("--blender", help="Blender の場所")
    m = sub.add_parser("materials", help="材質のライブラリ（3D と漫画での描き方の組）")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=cmd_materials)
    return p


def cmd_materials(a) -> int:
    from .materials import LIBRARY

    if a.json:
        _print({name: m.as_dict() for name, m in LIBRARY.items()}, True)
        return 0
    for m in LIBRARY.values():
        draw = "ベタ" if m.beta else f"トーン {m.tone * 100:.0f}%・影 {m.shadowTone * 100:.0f}%"
        lines = "描き込む" if m.lines == "detail" else "輪郭だけ"
        print(f"{m.name}: {draw}・線は{lines}" + (f"（{m.note}）" if m.note else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(argv)
    args.raw = argv
    try:
        return args.func(args)
    except InstructionError as error:
        print(str(error), file=sys.stderr)
        for problem in error.problems:
            print(f"  {problem}", file=sys.stderr)
        return 2
    except (CameraError, KeyError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2


__all__ = ["main", "find_blender", "instruction_dir"]
