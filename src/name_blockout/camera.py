# SPDX-License-Identifier: GPL-3.0-or-later
"""The camera a panel's perspective ruler asks for.

The ruler (drawn by the author on the panel) holds the eye level (the
horizon) and 1 to 3 vanishing points. A pinhole camera puts them there when

- its principal point (where it looks) is: on the horizon for a level camera
  (1点: at the point itself, 2点: under the picture's middle when the two
  points lie either side of it, else between them, no point: under the
  middle), or the orthocentre of the three points' triangle (3点, looking up
  or down);
- its focal length is: from two points on the horizon, f² = (p − u1)(u2 − p)
  along it; from three, f² = d·e (d: the principal point to the horizon,
  e: to the third point); else the lens given, else 35 mm;
- it is turned so the world's up is the normal of the horizon's plane of rays
  and the world's level axes run to the vanishing points.

This is worked out independently of name-studio's bgcamera.ts (same choices,
its own algebra) so the two can be compared: `hint_differences`.

Picture coordinates: px from the top-left, x right, y down. Camera
coordinates: Blender's camera's own (x right, y up, z back: it looks down
−z), right-handed like the world. World: Z up, ground z = 0. Blender's
camera: 36 mm sensor across the longer side (sensor fit AUTO), lens shift
in shares of the longer side (+x moves the view right, +y up).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .instruction import Frame, frame_of
from .vec import add, cross, dot, line_at_x, scale, sub, unit

SENSOR_MM = 36.0
DEFAULT_LENS_MM = 35.0
DEFAULT_HEIGHT_M = 1.5
AXES = {"+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0), "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0)}


class CameraError(ValueError):
    pass


@dataclass
class Camera:
    """A pinhole camera for one panel's picture, placed in the world."""

    width: int
    height: int
    focal_px: float
    principal: tuple[float, float]
    #: The world's axes in camera coordinates (rows of world→camera).
    world_x: tuple[float, float, float]
    world_y: tuple[float, float, float]
    world_z: tuple[float, float, float]
    position: tuple[float, float, float] = (0.0, 0.0, DEFAULT_HEIGHT_M)
    mode: str = "level"
    points: int = 0
    lens_from_points: bool = False
    #: The horizon's roll in the picture (degrees, + clockwise).
    roll_deg: float = 0.0
    notes: list[str] = field(default_factory=list)

    # --- as Blender takes it -------------------------------------------------------------------

    @property
    def longer(self) -> int:
        return max(self.width, self.height)

    @property
    def lens_mm(self) -> float:
        return self.focal_px * SENSOR_MM / self.longer

    @property
    def shift(self) -> tuple[float, float]:
        px, py = self.principal
        return ((self.width / 2 - px) / self.longer, (py - self.height / 2) / self.longer)

    def camera_axes_world(self) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
        """The camera's right, up and forward in world coordinates."""
        right, up, back = list(zip(self.world_x, self.world_y, self.world_z))
        return tuple(right), tuple(up), tuple(-v for v in back)

    def blender_matrix(self) -> list[list[float]]:
        """The camera object's 4×4 world matrix (Blender looks down −Z with +Y up)."""
        right, up, forward = self.camera_axes_world()
        back = scale(forward, -1)
        p = self.position
        return [
            [right[0], up[0], back[0], p[0]],
            [right[1], up[1], back[1], p[1]],
            [right[2], up[2], back[2], p[2]],
            [0.0, 0.0, 0.0, 1.0],
        ]

    @property
    def tilt_deg(self) -> float:
        """Looking down (+) or up (−)."""
        _, _, forward = self.camera_axes_world()
        return -math.degrees(math.asin(max(-1.0, min(1.0, forward[2]))))

    @property
    def heading_deg(self) -> float:
        """The way it looks, as a bearing in the world (0 = +X, 90 = +Y)."""
        _, _, forward = self.camera_axes_world()
        return math.degrees(math.atan2(forward[1], forward[0])) % 360

    # --- projection ----------------------------------------------------------------------------

    def to_camera(self, v, direction: bool = False):
        """A world point (or direction) in camera coordinates."""
        d = v if direction else sub(v, self.position)
        return tuple(self.world_x[i] * d[0] + self.world_y[i] * d[1] + self.world_z[i] * d[2] for i in range(3))

    def project(self, v, direction: bool = False):
        """A world point (or a direction's point at infinity) in the picture; None behind the camera."""
        c = self.to_camera(v, direction)
        depth = -c[2]
        if depth <= 1e-9:
            return None
        return (self.principal[0] + self.focal_px * c[0] / depth, self.principal[1] - self.focal_px * c[1] / depth)

    def ray(self, q) -> tuple[float, float, float]:
        """The world direction through picture point q."""
        c = ((q[0] - self.principal[0]) / self.focal_px, -(q[1] - self.principal[1]) / self.focal_px, 1.0)
        right, up, forward = self.camera_axes_world()
        return unit(add(add(scale(right, c[0]), scale(up, c[1])), scale(forward, c[2])))

    def ground_point(self, q, z: float = 0.0):
        """Where the ray through q meets the level plane at height z (None if it does not, in front)."""
        r = self.ray(q)
        if abs(r[2]) < 1e-9:
            return None
        t = (z - self.position[2]) / r[2]
        if t <= 0:
            return None
        return add(self.position, scale(r, t))

    def horizon_rows(self) -> tuple[float, float]:
        """The horizon's row at the picture's left and right edges, as this camera draws it."""
        right, _, forward = self.camera_axes_world()
        level = unit((forward[0], forward[1], 0.0)) if math.hypot(forward[0], forward[1]) > 1e-6 else unit((right[0], right[1], 0.0))
        side = unit((-level[1], level[0], 0.0))
        a = self.project(add(scale(level, 1.0), scale(side, 0.3)), direction=True)
        b = self.project(add(scale(level, 1.0), scale(side, -0.3)), direction=True)
        return (line_at_x(a, b, 0.0), line_at_x(a, b, float(self.width)))

    def summary(self) -> dict:
        sx, sy = self.shift
        return {
            "sizePx": [self.width, self.height],
            "mode": self.mode,
            "points": self.points,
            "focalPx": round(self.focal_px, 2),
            "lensMm": round(self.lens_mm, 3),
            "lensFromPoints": self.lens_from_points,
            "principalPx": [round(self.principal[0], 2), round(self.principal[1], 2)],
            "shiftX": round(sx, 5),
            "shiftY": round(sy, 5),
            "tiltDeg": round(self.tilt_deg, 3),
            "rollDeg": round(self.roll_deg, 3),
            "headingDeg": round(self.heading_deg, 3),
            "positionM": [round(v, 4) for v in self.position],
            "notes": self.notes,
        }


# --- from the ruler --------------------------------------------------------------------------


def ruler_px(shot: dict, frame: Frame | None = None):
    """The ruler of a shot in its picture's pixels: (points, horizon (a, b), vanishing points)."""
    frame = frame or frame_of(shot["frame"])
    ruler = shot.get("ruler")
    if not ruler or not ruler.get("horizonMm"):
        return None
    a, b = (frame.px(p) for p in ruler["horizonMm"])
    vanishing = [frame.px(p) for p in ruler.get("vanishingMm") or []]
    points = int(ruler.get("points", len(vanishing)))
    return points, (a, b), vanishing


def fit_camera(shot: dict, frame: Frame | None = None) -> Camera | None:
    """The camera for a shot's ruler (None without an eye level)."""
    frame = frame or frame_of(shot["frame"])
    got = ruler_px(shot, frame)
    if got is None:
        return None
    points, (a, b), vanishing = got
    vanishing = vanishing[: max(0, min(3, points))] if points else []
    width, height, longer = frame.width, frame.height, frame.longer
    notes: list[str] = []

    if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-6:
        raise CameraError("アイレベルの 2 点が同じ場所にあります")
    if abs(b[0] - a[0]) < 1e-6:
        raise CameraError("アイレベルが縦です")
    slope = (b[1] - a[1]) / (b[0] - a[0])
    roll = math.atan(slope)
    cos, sin = math.cos(roll), math.sin(roll)
    cx, cy = width / 2, height / 2

    def s_of(p):
        return (p[0] - cx) * cos + (p[1] - cy) * sin

    def t_of(p):
        return -(p[0] - cx) * sin + (p[1] - cy) * cos

    def picture(s, t):
        return (cx + s * cos - t * sin, cy + s * sin + t * cos)

    th = t_of(a)
    camera_lens = (shot.get("camera") or {}).get("lensMm")
    focal = (camera_lens or DEFAULT_LENS_MM) * longer / SENSOR_MM
    from_points = False
    mode = "level"

    if len(vanishing) >= 3:
        s1, s2 = s_of(vanishing[0]), s_of(vanishing[1])
        s3, t3 = s_of(vanishing[2]), t_of(vanishing[2])
        if abs(t3 - th) < 1e-6:
            raise CameraError("消失点 3 がアイレベルの上にあります")
        ps = s3
        pt = th - ((s3 - s1) * (s3 - s2)) / (t3 - th)
        d = abs(pt - th)
        e = abs(t3 - pt)
        # The principal point must lie between the horizon and the third point (an acute triangle).
        if (pt - th) * (t3 - th) <= 0 or (t3 - pt) * (t3 - th) <= 0 or d * e <= 1:
            raise CameraError("3 つの消失点の三角形が鋭角でないため、カメラが決まりません（消失点 3 を離すか、1・2 を広げる）")
        focal = math.sqrt(d * e)
        from_points = True
        mode = "tilt"
    elif len(vanishing) == 2:
        u1, u2 = sorted((s_of(vanishing[0]), s_of(vanishing[1])))
        ps = 0.0 if u1 < 0 < u2 else (u1 + u2) / 2
        pt = th
        product = (ps - u1) * (u2 - ps)
        if product > 1:
            focal = math.sqrt(product)
            from_points = True
        else:
            notes.append("消失点 1・2 が近すぎてレンズが決まらないので、仮のレンズ")
    elif len(vanishing) == 1:
        ps = s_of(vanishing[0])
        pt = th
    else:
        ps = 0.0
        pt = th
    principal = picture(ps, pt)

    def ray_cam(q):
        return unit(((q[0] - principal[0]) / focal, -(q[1] - principal[1]) / focal, -1.0))

    # World up: the normal of the plane of rays through the horizon.
    up = unit(cross(ray_cam(a), ray_cam(b)))
    if up[1] < 0:
        up = scale(up, -1)
    if len(vanishing) >= 1:
        d1 = ray_cam(vanishing[0])
    else:
        d1 = (0.0, 0.0, -1.0)
    # Keep it level (the point is on the horizon, up to rounding).
    d1 = unit(sub(d1, scale(up, dot(d1, up))))
    # The world's axes: X to vanishing point 1 (or as the place says), Z up, Y = Z × X.
    shot_axes = (shot.get("place") or {}).get("axes") or []
    first = shot_axes[0] if shot_axes else "+X"
    second_axis_world = cross((0.0, 0.0, 1.0), AXES[first])  # the world axis 90° left of the first
    second_dir_cam = cross(up, d1)  # 90° left of d1 (both systems are right-handed)
    # world→camera: the first axis → d1, the second → second_dir_cam, Z → up.
    world_axes_cam = _axes_from(AXES[first], d1, second_axis_world, second_dir_cam, up)
    wx, wy, wz = world_axes_cam

    camera = Camera(
        width=width,
        height=height,
        focal_px=focal,
        principal=principal,
        world_x=wx,
        world_y=wy,
        world_z=wz,
        mode=mode,
        points=len(vanishing),
        lens_from_points=from_points,
        roll_deg=math.degrees(roll),
        notes=notes,
    )
    cam = shot.get("camera") or {}
    if cam.get("positionM"):
        camera.position = tuple(float(v) for v in cam["positionM"])
    else:
        camera.position = (0.0, 0.0, float(cam.get("heightM", DEFAULT_HEIGHT_M)))
    return camera


def _axes_from(first_world, first_cam, second_world, second_cam, up_cam):
    """world_x/y/z in camera coordinates, from where two level world axes and Z go."""
    out = []
    for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        # e = a·first + b·second + c·Z (first, second, Z orthonormal in the world)
        a, b, c = dot(e, first_world), dot(e, second_world), e[2]
        out.append(add(add(scale(first_cam, a), scale(second_cam, b)), scale(up_cam, c)))
    return tuple(tuple(v) for v in out)


# --- against the hint -------------------------------------------------------------------------


def hint_differences(camera: Camera, hint: dict | None) -> list[dict]:
    """Where name-studio's own camera (hint) differs from this one beyond rounding."""
    if not hint:
        return []
    sx, sy = camera.shift
    ours = {
        "mode": camera.mode,
        "points": camera.points,
        "lensMm": camera.lens_mm,
        "lensFromPoints": camera.lens_from_points,
        "shiftX": sx,
        "shiftY": sy,
        "tiltDeg": camera.tilt_deg,
        "rollDeg": camera.roll_deg,
    }
    tolerance = {"lensMm": 0.15, "shiftX": 0.002, "shiftY": 0.002, "tiltDeg": 0.15, "rollDeg": 0.15}
    out = []
    for key, value in ours.items():
        if key not in hint or hint[key] is None:
            continue
        theirs = hint[key]
        if isinstance(value, (bool, str, int)) and not isinstance(value, float) and key not in tolerance:
            if value != theirs:
                out.append({"field": key, "hint": theirs, "ours": value})
        elif abs(float(theirs) - float(value)) > tolerance[key]:
            out.append({"field": key, "hint": theirs, "ours": round(float(value), 4)})
    return out


def focal_from_lens(lens_mm: float, frame: Frame) -> float:
    return lens_mm * frame.longer / SENSOR_MM


def angle_between_lines(p, a, b) -> float:
    """At picture point p, the angle (degrees) between the lines p→a and p→b (directions, mod 180)."""
    da = math.atan2(a[1] - p[1], a[0] - p[0])
    db = math.atan2(b[1] - p[1], b[0] - p[0])
    d = abs(da - db) % math.pi
    return math.degrees(min(d, math.pi - d))
