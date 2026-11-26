# SPDX-License-Identifier: GPL-3.0-or-later
"""The light from words: the sun where it is at that time and place, the weather, and the side it lights."""

import math

import pytest

from name_blockout.look import (
    day_of_year,
    heading_azimuth,
    key_of,
    lighting,
    norths_for_key,
    solar_hour,
    sun_at,
    sunrise_sunset,
    world_direction,
)
from name_blockout.materials import LIBRARY, assign, guess
from name_blockout.requirement import effective, get_path, set_path

TOKYO = 35.68


def test_sun_at_the_equinox():
    day = day_of_year("03-21")
    az, el = sun_at(TOKYO, day, 12.0)
    assert az == pytest.approx(180.0, abs=0.5) and el == pytest.approx(90 - TOKYO, abs=1.0)
    rise, set_ = sunrise_sunset(TOKYO, day)
    assert rise == pytest.approx(6.0, abs=0.1) and set_ == pytest.approx(18.0, abs=0.1)
    az, el = sun_at(TOKYO, day, rise + 2)
    assert 90 < az < 130 and 15 < el < 30  # east-south-east, low


def test_seasons_and_words():
    summer, winter = day_of_year("2026-06-21"), day_of_year("12-22")
    assert sun_at(TOKYO, summer, 12)[1] > 75 and sun_at(TOKYO, winter, 12)[1] < 32
    assert solar_hour("noon", TOKYO, summer) == 12.0
    assert solar_hour("night", TOKYO, summer) is None
    evening = solar_hour("evening", TOKYO, winter)
    assert 0 < sun_at(TOKYO, winter, evening)[1] < 12
    assert sun_at(TOKYO, winter, solar_hour("dusk", TOKYO, winter))[1] < 0


def test_world_direction_and_sides():
    # North +Y: the sun at azimuth 90 (east) is +X.
    assert world_direction(90, 0, "+Y") == pytest.approx((1, 0, 0), abs=1e-9)
    assert world_direction(180, 0, "+X") == pytest.approx((-1, 0, 0), abs=1e-9)
    assert world_direction(0, 90, "+Y")[2] == pytest.approx(1.0)
    # A camera looking north (heading 90 = +Y): the sun in the south lights what it sees from the front.
    assert heading_azimuth(90.0, "+Y") == pytest.approx(0.0)
    assert key_of(180.0, 90.0, "+Y") == "front"
    assert key_of(0.0, 90.0, "+Y") == "back"
    assert key_of(90.0, 90.0, "+Y") == "side-right"
    assert key_of(270.0, 90.0, "+Y") == "side-left"
    # The north that puts the sun (south) behind the subject.
    for north in norths_for_key("back", 90.0, 180.0)[:1]:
        assert key_of(180.0, 90.0, north) == "back"


def test_lighting_words_and_assumptions():
    light, assumed = lighting({"timeOfDay": "evening", "weather": "cloudy"}, 0.0)
    assert light["sun"]["strength"] > 0 and light["sun"]["angleDeg"] > 1
    assert {a["path"] for a in assumed} == {"look.location", "look.date", "look.north"}
    d = light["sun"]["direction"]
    assert math.hypot(*d) == pytest.approx(1.0, abs=1e-5)
    light, _ = lighting({"timeOfDay": "noon", "weather": "overcast"}, 0.0)
    assert light["sun"]["strength"] == 0.0
    light, _ = lighting({"timeOfDay": "night"}, 0.0)
    assert light["sun"] is None and light["sky"]["strength"] < 0.1
    # No time: the light where the author says, relative to the camera.
    light, _ = lighting({"light": {"key": "back"}}, 30.0)
    assert light["sun"]["side"] == "back" and key_of(light["sun"]["azimuthDeg"], 30.0, "+Y") == "back"


def test_materials_assigned_and_guessed():
    shot = {
        "objects": [{"id": "a", "label": "倉庫"}, {"id": "b", "label": "黒いバン"}, {"id": "c", "label": "なにか"}],
        "look": {"materials": [{"target": "a", "material": "コンクリート"}]},
    }
    mats, assumed = assign(shot)
    assert mats["a"]["name"] == "コンクリート" and mats["b"]["beta"] and mats["c"]["name"] == "白壁"
    assert mats["ground"]["name"] == "白地"
    assert {a["path"] for a in assumed} == {"look.materials/b", "look.materials/c", "look.materials/ground"}
    assert guess("給水塔の上") == "コンクリート" and guess("???") is None
    assert all(0 <= m.tone <= m.shadowTone <= 1 for m in LIBRARY.values())


def test_answers_reach_lists():
    shot = {"objects": [{"id": "a", "label": "倉庫"}], "far": [{"kind": "panorama"}], "look": {}}
    assert set_path(shot, "look.materials/a", "木") and shot["look"]["materials"] == [{"target": "a", "material": "木"}]
    assert get_path(shot, "look.materials/a") == "木"
    assert set_path(shot, "look.materials/a", "金属") and shot["look"]["materials"] == [{"target": "a", "material": "金属"}]
    assert set_path(shot, "far/0/asset", "曇り空") and shot["far"][0]["asset"] == "曇り空"
    out, replaced = effective({"objects": shot["objects"]}, {"look.materials/a": "木", "look.north": "+X"})
    assert out["look"] == {"materials": [{"target": "a", "material": "木"}], "north": "+X"} and replaced == []


def test_indoors_the_light_is_the_room_s():
    from name_blockout.look import setting_of

    shot = {"objects": [{"id": "o1", "label": "ソファ"}], "look": {"timeOfDay": "evening"}}
    setting, assumed = setting_of(shot)
    assert setting == "indoor" and assumed["path"] == "look.setting" and "ソファ" in assumed["note"]
    light, notes = lighting(shot["look"], 90.0, setting)
    assert light["setting"] == "indoor" and light["sun"]["side"] == "interior" and light["sun"]["strength"] > 0
    assert light["sun"]["elevationDeg"] == 80.0 and light["sun"]["angleDeg"] >= 20
    assert [n["path"] for n in notes] == ["look.weather", "look.light.key"]
    # Through a window: low, from the left of the view; none at night.
    window, _ = lighting({"timeOfDay": "noon", "light": {"key": "window"}}, 90.0, "indoor")
    assert window["sun"]["elevationDeg"] == 20.0 and window["sun"]["side"] == "window"
    assert window["sun"]["direction"][0] < -0.9  # looking along +Y, the light comes from the left (−X)
    night, _ = lighting({"timeOfDay": "night", "light": {"key": "window"}}, 90.0, "indoor")
    assert night["sun"]["strength"] == 0.0 and night["sky"]["strength"] == 0.0
    # Said outdoors, it stays outdoors.
    assert setting_of({"objects": [{"id": "o1", "label": "ソファ"}], "look": {"setting": "outdoor"}}) == ("outdoor", None)
    floor, _ = assign(shot, "indoor")
    assert floor["ground"]["name"] == "白地" and floor["o1"]["name"] == "布"
