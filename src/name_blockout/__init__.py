# SPDX-License-Identifier: GPL-3.0-or-later
"""name-blockout: backgrounds for manga panels from a name's instructions.

Three phases: requirements (check what the instruction says and ask what is
missing), design (Blockout: a quick box model whose camera comes from the
panel's perspective ruler, checked in numbers), and development (the
production drawing, built on the design without moving its camera or
layout). The pure parts (this package except `blender/`) run in any Python
3.11+, including Blender's own; `blender/` runs inside Blender.
"""

__version__ = "0.1.0"

FORMAT = "name-blockout/instruction"
FORMAT_VERSION = 1
