# SPDX-License-Identifier: GPL-3.0-or-later
"""The look of a shot in numbers, from its words: where the sun is (date, time
of day, latitude and longitude, which way north is) and what the weather does
to it. A fixed calculation (no AI): the same words give the same light.

The sun: declination from the day of the year, the hour angle in local solar
time, then elevation and azimuth (degrees from north, clockwise). Times of day
are hours of solar time, set from that day's sunrise and sunset:

  dawn      sunrise − 15 min (the sun just under the horizon: sky light only)
  morning   sunrise + 2 h
  noon      12:00 (solar noon)
  afternoon 15:00 (an hour and a half before sunset at the latest)
  evening   sunset − 1 h (low sun, long shadows)
  dusk      sunset + 20 min (sky light only)
  night     no sun

Without a date the spring equinox (03-21) stands, without a place Tokyo, and
without north +Y; each is noted as an assumption.
"""

from __future__ import annotations

import datetime as dt
import math

from .camera import AXES

DEFAULT_DATE = "03-21"
DEFAULT_LOCATION = {"latDeg": 35.68, "lonDeg": 139.77, "name": "東京"}
PLACES = {"東京": (35.68, 139.77), "大阪": (34.69, 135.50), "札幌": (43.06, 141.35), "那覇": (26.21, 127.68)}
DEFAULT_NORTH = "+Y"

#: Weather: the sun's strength (W/m², Blender's sun), how wide it looks (soft shadows), the sky's strength, direct sun at all.
WEATHER = {
    "clear": {"sun": 4.0, "angleDeg": 0.6, "sky": 0.6, "direct": True},
    "cloudy": {"sun": 2.5, "angleDeg": 4.0, "sky": 0.9, "direct": True},
    "haze": {"sun": 2.0, "angleDeg": 8.0, "sky": 0.9, "direct": True},
    "overcast": {"sun": 0.0, "angleDeg": 0.0, "sky": 1.2, "direct": False},
    "rain": {"sun": 0.0, "angleDeg": 0.0, "sky": 0.8, "direct": False},
    "snow": {"sun": 0.0, "angleDeg": 0.0, "sky": 1.3, "direct": False},
    "fog": {"sun": 0.0, "angleDeg": 0.0, "sky": 1.0, "direct": False},
}
DEFAULT_WEATHER = "clear"

#: A light the author names relative to the camera (look.light.key): its azimuth from the camera's heading, its elevation.
KEY_DIRECTIONS = {
    "front": (180.0, 35.0),  # from behind the camera onto what it sees
    "back": (0.0, 25.0),  # from behind what it sees (backlight)
    "side-left": (90.0, 30.0),
    "side-right": (-90.0, 30.0),
    "top": (0.0, 80.0),
}
KEY_LABELS = {"front": "順光（カメラ側から）", "back": "逆光", "side-left": "左から", "side-right": "右から", "top": "真上から"}


def day_of_year(date: str | None) -> int:
    """The day of the year of "YYYY-MM-DD" or "MM-DD" (an ordinary year)."""
    text = (date or DEFAULT_DATE).strip()
    parts = text.split("-")
    month, day = (int(parts[-2]), int(parts[-1])) if len(parts) >= 2 else (3, 21)
    return dt.date(2025, month, day).timetuple().tm_yday


def declination_deg(day: int) -> float:
    return 23.44 * math.sin(math.radians(360.0 / 365.0 * (284 + day)))


def sun_at(lat_deg: float, day: int, solar_hour: float) -> tuple[float, float]:
    """(azimuth from north clockwise, elevation), degrees, at that solar time."""
    phi, delta = math.radians(lat_deg), math.radians(declination_deg(day))
    hour_angle = math.radians(15.0 * (solar_hour - 12.0))
    sin_el = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(hour_angle)
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))
    a = math.atan2(math.sin(hour_angle), math.cos(hour_angle) * math.sin(phi) - math.tan(delta) * math.cos(phi))
    azimuth = (math.degrees(a) + 180.0) % 360.0
    return azimuth, elevation


def sunrise_sunset(lat_deg: float, day: int) -> tuple[float, float] | None:
    """Sunrise and sunset in solar hours (None: the sun stays up or down all day)."""
    phi, delta = math.radians(lat_deg), math.radians(declination_deg(day))
    c = (math.sin(math.radians(-0.833)) - math.sin(phi) * math.sin(delta)) / (math.cos(phi) * math.cos(delta))
    if abs(c) > 1:
        return None
    h = math.degrees(math.acos(c)) / 15.0
    return 12.0 - h, 12.0 + h


def solar_hour(word: str, lat_deg: float, day: int) -> float | None:
    """The solar hour a time-of-day word stands for (None: night)."""
    times = sunrise_sunset(lat_deg, day) or (6.0, 18.0)
    rise, set_ = times
    return {
        "dawn": rise - 0.25,
        "morning": rise + 2.0,
        "noon": 12.0,
        "afternoon": min(15.0, set_ - 1.5),
        "evening": set_ - 1.0,
        "dusk": set_ + 1.0 / 3.0,
        "night": None,
    }.get(word, 12.0)


def world_direction(azimuth_deg: float, elevation_deg: float, north: str = DEFAULT_NORTH) -> tuple[float, float, float]:
    """The direction toward the sun in the place's coordinates (Z up; north as said, east 90° clockwise from it)."""
    n = AXES[north]
    east = (n[1], -n[0], 0.0)  # north × Z
    a, e = math.radians(azimuth_deg), math.radians(elevation_deg)
    h = math.cos(e)
    return (
        h * (math.cos(a) * n[0] + math.sin(a) * east[0]),
        h * (math.cos(a) * n[1] + math.sin(a) * east[1]),
        math.sin(e),
    )


def heading_azimuth(heading_deg: float, north: str = DEFAULT_NORTH) -> float:
    """A heading in the place (degrees from +X, counter-clockwise) as an azimuth (from north, clockwise)."""
    n = AXES[north]
    north_heading = math.degrees(math.atan2(n[1], n[0]))
    return (north_heading - heading_deg) % 360.0


def key_of(sun_azimuth: float, camera_heading: float, north: str) -> str:
    """Which way the sun lights what the camera sees: front (順光), back (逆光), side-left, side-right."""
    view = heading_azimuth(camera_heading, north)
    d = (sun_azimuth - view + 540.0) % 360.0 - 180.0  # the sun's azimuth seen from the view, -180..180 (+ = to the right)
    if abs(d) <= 45:
        return "back"
    if abs(d) >= 135:
        return "front"
    return "side-right" if d > 0 else "side-left"


def norths_for_key(key: str, camera_heading: float, sun_azimuth: float) -> list[str]:
    """The north axes (of the four level ones) that put the sun on the side `key` says, best first."""
    out = []
    for north in ("+Y", "+X", "-Y", "-X"):
        view = heading_azimuth(camera_heading, north)
        d = (sun_azimuth - view + 540.0) % 360.0 - 180.0
        want = {"back": 0.0, "front": 180.0, "side-right": 90.0, "side-left": -90.0}.get(key)
        if want is None:
            continue
        miss = abs((d - want + 540.0) % 360.0 - 180.0)
        out.append((miss, north))
    return [north for miss, north in sorted(out) if miss < 70]


def lighting(look: dict | None, camera_heading: float) -> tuple[dict, list[dict]]:
    """The light of a shot in numbers, and the assumptions made for what the words leave open."""
    look = look or {}
    assumed: list[dict] = []
    weather = look.get("weather") or DEFAULT_WEATHER
    if not look.get("weather"):
        assumed.append({"path": "look.weather", "value": DEFAULT_WEATHER, "by": "tool", "note": "天気が決まっていないので晴れ"})
    w = WEATHER[weather]
    north = look.get("north") or DEFAULT_NORTH
    word = look.get("timeOfDay")
    key = (look.get("light") or {}).get("key")
    out = {"weather": weather, "north": north, "timeOfDay": word, "sky": {"strength": w["sky"]}, "sun": None, "key": key}
    if word:
        loc = look.get("location")
        if not loc:
            loc = DEFAULT_LOCATION
            assumed.append(
                {
                    "path": "look.location",
                    "value": [loc["latDeg"], loc["lonDeg"]],
                    "by": "tool",
                    "note": "場所が決まっていないので東京の緯度",
                }
            )
        if not look.get("date"):
            assumed.append({"path": "look.date", "value": DEFAULT_DATE, "by": "tool", "note": "日付が決まっていないので春分"})
        if not look.get("north"):
            assumed.append({"path": "look.north", "value": DEFAULT_NORTH, "by": "tool", "note": "北の向きが決まっていないので +Y"})
        day = day_of_year(look.get("date"))
        hour = solar_hour(word, loc["latDeg"], day)
        sky_scale = {"dawn": 0.35, "dusk": 0.3, "night": 0.06, "evening": 0.8}.get(word, 1.0)
        out["sky"]["strength"] = round(w["sky"] * sky_scale, 3)
        if hour is not None:
            azimuth, elevation = sun_at(loc["latDeg"], day, hour)
            out["solarHour"] = round(hour, 3)
            out["sun"] = {
                "azimuthDeg": round(azimuth, 3),
                "elevationDeg": round(elevation, 3),
                "direction": [round(v, 6) for v in world_direction(azimuth, elevation, north)],
                "strength": w["sun"] if (w["direct"] and elevation > 0.5) else 0.0,
                "angleDeg": w["angleDeg"],
                "side": key_of(azimuth, camera_heading, north),
            }
    elif key in KEY_DIRECTIONS:
        # No time: the light comes from where the author says, relative to the camera.
        rel, elevation = KEY_DIRECTIONS[key]
        azimuth = (heading_azimuth(camera_heading, north) - rel) % 360.0 if key != "top" else 0.0
        out["sun"] = {
            "azimuthDeg": round(azimuth, 3),
            "elevationDeg": elevation,
            "direction": [round(v, 6) for v in world_direction(azimuth, elevation, north)],
            "strength": w["sun"] if w["direct"] else 0.0,
            "angleDeg": w["angleDeg"],
            "side": key,
        }
    return out, assumed
