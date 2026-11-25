# SPDX-License-Identifier: GPL-3.0-or-later
"""The camera from a ruler: drawn from a known camera, the ruler gives that camera back."""

import math
import random

import pytest
from conftest import shot_from_camera, true_camera

from name_blockout.camera import CameraError, fit_camera, hint_differences
from name_blockout.instruction import frame_of

BOX = (10.0, 20.0, 210.0, 120.0)
DPI = 100.0


def size():
    f = frame_of({"boxMm": list(BOX), "dpi": DPI})
    return f.width, f.height


def same_projection(a, b, tol=0.05):
    """Both cameras draw every direction (and points about the scene) at the same place."""
    for d in ((1, 0, 0), (0, 1, 0), (0, -1, 0), (-1, 0, 0), (1, 1, 0.3), (0.3, -1, -0.5), (2, -1, 0.1), (0, 0, 1), (0, 0, -1)):
        pa, pb = a.project(d, direction=True), b.project(d, direction=True)
        assert (pa is None) == (pb is None), d
        if pa is None:
            continue
        # Points far outside are judged by direction from the picture's middle.
        if max(abs(pa[0]), abs(pa[1])) > 1e5:
            continue
        assert math.dist(pa, pb) < tol * max(1.0, math.dist(pa, (a.width / 2, a.height / 2)) / 1000), (d, pa, pb)


def level_principal(w, h, roll_deg, th):
    """A level camera's principal point: on the horizon, under the picture's middle."""
    r = math.radians(roll_deg)
    return (w / 2 - th * math.sin(r), h / 2 + th * math.cos(r))


@pytest.mark.parametrize("heading", [20.0, 45.0, 63.0])
@pytest.mark.parametrize("roll", [0.0, 4.0, -7.5])
@pytest.mark.parametrize("th", [0.0, 80.0, -150.0])
def test_two_point_level(heading, roll, th):
    w, h = size()
    truth = true_camera(w, h, 700.0, heading, 0.0, roll, level_principal(w, h, roll, th))
    shot = shot_from_camera(truth, 2, BOX, DPI)
    cam = fit_camera(shot)
    assert cam.mode == "level" and cam.lens_from_points
    assert cam.focal_px == pytest.approx(700.0, rel=1e-6)
    assert cam.principal == pytest.approx(truth.principal, abs=1e-6)
    assert cam.roll_deg == pytest.approx(roll, abs=1e-9)
    same_projection(truth, cam)


@pytest.mark.parametrize("heading,tilt,roll", [(30.0, 25.0, 0.0), (50.0, -30.0, 0.0), (35.0, 40.0, 6.0), (60.0, -20.0, -5.0)])
def test_three_point(heading, tilt, roll):
    w, h = size()
    truth = true_camera(w, h, 650.0, heading, tilt, roll, (w / 2 + 37.0, h / 2 - 21.0))
    shot = shot_from_camera(truth, 3, BOX, DPI)
    cam = fit_camera(shot)
    assert cam.mode == "tilt"
    assert cam.focal_px == pytest.approx(650.0, rel=1e-6)
    assert cam.principal == pytest.approx(truth.principal, abs=1e-6)
    assert cam.tilt_deg == pytest.approx(tilt, abs=1e-6)
    same_projection(truth, cam)


@pytest.mark.parametrize("roll", [0.0, 3.0])
def test_one_point_looks_at_the_point(roll):
    w, h = size()
    lens = 28.0
    focal = lens * max(w, h) / 36.0
    truth = true_camera(w, h, focal, 0.0, 0.0, roll, level_principal(w, h, roll, 60.0))
    shot = shot_from_camera(truth, 1, BOX, DPI)
    shot["camera"]["lensMm"] = lens
    cam = fit_camera(shot)
    assert cam.principal == pytest.approx(truth.principal, abs=1e-6)
    assert cam.lens_mm == pytest.approx(lens)
    assert cam.heading_deg == pytest.approx(0.0, abs=1e-6)
    same_projection(truth, cam)


def test_random_cameras():
    rng = random.Random(7)
    w, h = size()
    for _ in range(60):
        heading = rng.uniform(10, 80)
        roll = rng.uniform(-10, 10)
        focal = rng.uniform(300, 1500)
        if rng.random() < 0.5:
            tilt = rng.choice([-1, 1]) * rng.uniform(12, 45)
            truth = true_camera(w, h, focal, heading, tilt, roll, (w / 2 + rng.uniform(-80, 80), h / 2 + rng.uniform(-80, 80)))
            points = 3
        else:
            truth = true_camera(w, h, focal, heading, 0.0, roll, level_principal(w, h, roll, rng.uniform(-200, 200)))
            points = 2
        try:
            cam = fit_camera(shot_from_camera(truth, points, BOX, DPI))
        except CameraError:
            continue
        assert cam.focal_px == pytest.approx(focal, rel=1e-5)
        same_projection(truth, cam)


def test_place_axes_turn_the_world():
    w, h = size()
    truth = true_camera(w, h, 700.0, 30.0, 0.0, 0.0, level_principal(w, h, 0.0, 50.0))
    shot = shot_from_camera(truth, 2, BOX, DPI)
    shot["place"] = {"axes": ["+Y", "+X"]}
    cam = fit_camera(shot)
    vp1 = cam.project((0, 1, 0), direction=True)
    target = frame_of(shot["frame"]).px(shot["ruler"]["vanishingMm"][0])
    assert vp1 == pytest.approx(target, abs=1e-6)


def test_obtuse_three_points_are_refused():
    shot = {
        "id": "s",
        "frame": {"boxMm": list(BOX), "dpi": DPI},
        "ruler": {"points": 3, "horizonMm": [[10, 60], [210, 60]], "vanishingMm": [[100, 60], [120, 60], [400, 200]]},
    }
    with pytest.raises(CameraError):
        fit_camera(shot)


def test_hint_differences():
    w, h = size()
    truth = true_camera(w, h, 700.0, 40.0, 0.0, 0.0, level_principal(w, h, 0.0, 30.0))
    cam = fit_camera(shot_from_camera(truth, 2, BOX, DPI))
    sx, sy = cam.shift
    good = {
        "mode": "level",
        "points": 2,
        "lensMm": round(cam.lens_mm, 1),
        "shiftX": round(sx, 3),
        "shiftY": round(sy, 3),
        "tiltDeg": 0,
        "rollDeg": 0,
    }
    assert hint_differences(cam, good) == []
    bad = {**good, "shiftY": sy + 0.05}
    assert [d["field"] for d in hint_differences(cam, bad)] == ["shiftY"]
