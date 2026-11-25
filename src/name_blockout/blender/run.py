# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry for Blender: blender -b --factory-startup --python run.py -- <command> [args]

Same commands as `python -m name_blockout`; this file only makes the package
importable in Blender's own Python (no install needed) and passes the
arguments after `--`.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from name_blockout.cli import main  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
code = main(args)
sys.stdout.flush()
if code:
    sys.exit(code)
