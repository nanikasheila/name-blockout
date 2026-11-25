# SPDX-License-Identifier: GPL-3.0-or-later
"""Picture sizes from headers."""

import struct

from name_blockout.imagesize import image_size


def test_hdr(tmp_path):
    p = tmp_path / "a.hdr"
    p.write_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\nEXPOSURE=1\n\n-Y 2048 +X 4096\n\x02\x02")
    assert image_size(p) == (4096, 2048)


def test_png(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 320) + b"\x08\x06\0\0\0")
    assert image_size(p) == (640, 320)


def test_exr(tmp_path):
    def attr(name, kind, value):
        return name + b"\0" + kind + b"\0" + struct.pack("<i", len(value)) + value

    header = b"\x76\x2f\x31\x01" + struct.pack("<i", 2)
    header += attr(b"compression", b"compression", b"\x03")
    header += attr(b"dataWindow", b"box2i", struct.pack("<iiii", 0, 0, 8191, 4095))
    header += b"\0"
    p = tmp_path / "a.exr"
    p.write_bytes(header)
    assert image_size(p) == (8192, 4096)


def test_jpeg(tmp_path):
    p = tmp_path / "a.jpg"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0" + b"\0" * 9
    sof = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 300, 500) + b"\0" * 10
    p.write_bytes(b"\xff\xd8" + app0 + sof)
    assert image_size(p) == (500, 300)


def test_unknown(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"nothing")
    assert image_size(p) is None
    assert image_size(tmp_path / "none") is None
