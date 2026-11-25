# SPDX-License-Identifier: GPL-3.0-or-later
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from name_blockout.camera import Camera  # noqa: E402
from name_blockout.instruction import frame_of  # noqa: E402
from name_blockout.vec import cross, scale, unit  # noqa: E402


def has_bpy() -> bool:
    try:
        import bpy  # noqa: F401
    except ImportError:
        return False
    return True


needs_blender = pytest.mark.skipif(not has_bpy(), reason="bpy（Blender）がない")


def true_camera(width, height, focal, heading_deg, tilt_deg, roll_deg, principal, position=(0.0, 0.0, 1.5)) -> Camera:
    """A camera made from its angles (heading 0 = +X, tilt + = looking down, roll + = picture's horizon clockwise)."""
    h, t, r = (math.radians(v) for v in (heading_deg, tilt_deg, roll_deg))
    forward = (math.cos(t) * math.cos(h), math.cos(t) * math.sin(h), -math.sin(t))
    right = unit(cross(forward, (0.0, 0.0, 1.0)))
    up = cross(right, forward)
    # Turning the camera counter-clockwise about its view turns the picture's horizon clockwise.
    c, s = math.cos(r), math.sin(r)
    right, up = (
        tuple(a * c + b * s for a, b in zip(right, up)),
        tuple(-a * s + b * c for a, b in zip(right, up)),
    )
    back = scale(forward, -1)
    world_x = (right[0], up[0], back[0])
    world_y = (right[1], up[1], back[1])
    world_z = (right[2], up[2], back[2])
    return Camera(
        width=width,
        height=height,
        focal_px=focal,
        principal=principal,
        world_x=world_x,
        world_y=world_y,
        world_z=world_z,
        position=position,
    )


def shot_from_camera(camera: Camera, points: int, box=(10.0, 20.0, 210.0, 120.0), dpi=100.0) -> dict:
    """The instruction a ruler drawn to `camera` gives (horizon, and vanishing points of +X, ±Y, ±Z)."""
    frame = frame_of({"boxMm": list(box), "dpi": dpi})
    assert (frame.width, frame.height) == (camera.width, camera.height)
    rows = camera.horizon_rows()
    horizon = [list(frame.mm((0.0, rows[0]))), list(frame.mm((float(camera.width), rows[1])))]
    vps = []
    for d in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))[:points]:
        p = camera.project(d, direction=True) or camera.project(scale(d, -1), direction=True)
        vps.append(list(frame.mm(p)))
    return {
        "id": "s",
        "frame": {"boxMm": list(box), "dpi": dpi},
        "ruler": {"points": points, "horizonMm": horizon, "vanishingMm": vps},
        "camera": {"heightM": camera.position[2]},
    }
