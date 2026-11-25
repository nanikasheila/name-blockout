# SPDX-License-Identifier: GPL-3.0-or-later
"""The size of a picture from its header (no image library): Radiance .hdr, OpenEXR, PNG, JPEG."""

from __future__ import annotations

import re
import struct
from pathlib import Path


def image_size(path: str | Path) -> tuple[int, int] | None:
    """(width, height) in pixels, or None when the file is not one of these or cannot be read."""
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return None
    if head.startswith(b"#?"):
        return _hdr(head)
    if head.startswith(b"\x76\x2f\x31\x01"):
        return _exr(head)
    if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
        w, h = struct.unpack(">II", head[16:24])
        return w, h
    if head.startswith(b"\xff\xd8"):
        return _jpeg(head)
    return None


def _hdr(head: bytes) -> tuple[int, int] | None:
    # The header ends with an empty line, then the size: "-Y <height> +X <width>" (or turned: "+X <w> -Y <h>" etc).
    end = head.find(b"\n\n")
    if end < 0:
        return None
    line = head[end + 2 :].split(b"\n", 1)[0].decode("ascii", "replace")
    m = re.match(r"([-+][XY])\s+(\d+)\s+([-+][XY])\s+(\d+)", line)
    if not m:
        return None
    first, a, _, b = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
    return (b, a) if first[1] == "Y" else (a, b)


def _exr(head: bytes) -> tuple[int, int] | None:
    # Attributes after the magic and version: name\0 type\0 size(int32) value; ends with an empty name.
    i = 8
    while i < len(head):
        end = head.find(b"\0", i)
        if end <= i:
            return None
        name = head[i:end]
        tend = head.find(b"\0", end + 1)
        if tend < 0 or tend + 5 > len(head):
            return None
        kind = head[end + 1 : tend]
        (size,) = struct.unpack("<i", head[tend + 1 : tend + 5])
        value = head[tend + 5 : tend + 5 + size]
        if name == b"dataWindow" and kind == b"box2i" and len(value) == 16:
            x0, y0, x1, y1 = struct.unpack("<iiii", value)
            return x1 - x0 + 1, y1 - y0 + 1
        i = tend + 5 + size
    return None


def _jpeg(head: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(head):
        if head[i] != 0xFF:
            return None
        marker = head[i + 1]
        (length,) = struct.unpack(">H", head[i + 2 : i + 4])
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", head[i + 5 : i + 9])
            return w, h
        i += 2 + length
    return None
