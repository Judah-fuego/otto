"""The mission the crew is flying. Progress, consumables, and the light delay come from the profile.

Same model as voyage/: a Hohmann transfer on circular, coplanar orbits. The ship's position on
the transfer ellipse and Earth's on its orbit give the distance home, and so the light delay.
Angles are heliocentric, measured from where the ship left Earth.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from schema import (
    FOOD_KG_PER_PERSON_DAY,
    OXYGEN_KG_PER_PERSON_DAY,
    WATER_KG_PER_PERSON_DAY,
    VoyageRequest,
)
from voyage import voyage_calculate
from voyage.calculator import AU_KM, PLANETS

MISSION_NAME = "Ares"
LAUNCH_UTC = datetime(2026, 6, 12, tzinfo=timezone.utc)
PROFILE = VoyageRequest(origin="earth", destination="mars", spacecraft_mass_kg=12_000, isp_s=450, crew=4)
# Consumables are loaded for the coast plus this reserve.
RESERVE_DAYS = 60

EARTH_YEAR_DAYS = 365.256
LIGHT_KM_S = 299_792.458

RATES_KG_PER_PERSON_DAY = {
    "oxygen": OXYGEN_KG_PER_PERSON_DAY,
    "water": WATER_KG_PER_PERSON_DAY,
    "food": FOOD_KG_PER_PERSON_DAY,
}


@lru_cache(maxsize=1)
def _coast_days() -> float:
    return voyage_calculate(PROFILE).travel_time_days


def _elapsed_days(now: datetime | None) -> float:
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - LAUNCH_UTC).total_seconds() / 86_400)


def _point(r: float, angle: float) -> list[float]:
    return [round(r * math.cos(angle), 4), round(r * math.sin(angle), 4)]


def _ship(elapsed: float, coast: float) -> tuple[float, float]:
    """Radius (AU) and angle on the transfer ellipse, from Kepler's equation."""
    r1, r2 = 1.0, PLANETS[PROFILE.destination].orbit_au
    a, e = (r1 + r2) / 2, (r2 - r1) / (r2 + r1)
    mean = math.pi * min(elapsed, coast) / coast
    ecc = mean
    for _ in range(20):
        ecc -= (ecc - e * math.sin(ecc) - mean) / (1 - e * math.cos(ecc))
    angle = 2 * math.atan2(math.sqrt(1 + e) * math.sin(ecc / 2), math.sqrt(1 - e) * math.cos(ecc / 2))
    return a * (1 - e * math.cos(ecc)), angle


def _positions(elapsed: float, coast: float) -> dict[str, list[float]]:
    body = PLANETS[PROFILE.destination]
    ship_r, ship_angle = _ship(elapsed, coast)
    earth_angle = 2 * math.pi * elapsed / EARTH_YEAR_DAYS
    # The ship meets the destination on the far side of the Sun at arrival.
    dest_angle = math.pi - 2 * math.pi * (coast - min(elapsed, coast)) / body.period_days
    return {
        "earth": _point(1.0, earth_angle),
        "ship": _point(ship_r, ship_angle),
        "destination": _point(body.orbit_au, dest_angle),
    }


def _distance_to_earth_km(elapsed: float, coast: float) -> float:
    p = _positions(elapsed, coast)
    (ex, ey), (sx, sy) = p["earth"], p["ship"]
    return math.hypot(sx - ex, sy - ey) * AU_KM


def light_delay_s(now: datetime | None = None) -> float:
    return _distance_to_earth_km(_elapsed_days(now), _coast_days()) / LIGHT_KM_S


def trajectory(now: datetime | None = None) -> dict[str, Any]:
    coast, elapsed = _coast_days(), _elapsed_days(now)
    remaining = max(0.0, coast - elapsed)
    distance = _distance_to_earth_km(elapsed, coast)
    return {
        "mission": MISSION_NAME,
        "origin": PROFILE.origin,
        "destination": PROFILE.destination,
        "crew": PROFILE.crew,
        "phase": "transit" if remaining > 0 else "arrived",
        "launch_utc": LAUNCH_UTC.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arrival_utc": (LAUNCH_UTC + timedelta(days=coast)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mission_day": int(elapsed) + 1,
        "transit_days": round(coast),
        "days_to_arrival": round(remaining, 1),
        "progress": round(min(elapsed / coast, 1.0), 3),
        "distance_to_earth_km": round(distance),
        "one_way_light_delay_min": round(distance / LIGHT_KM_S / 60, 1),
        "orbits_au": {"earth": 1.0, "destination": PLANETS[PROFILE.destination].orbit_au},
        "positions_au": _positions(elapsed, coast),
    }


def consumables(now: datetime | None = None) -> dict[str, Any]:
    coast, elapsed = _coast_days(), _elapsed_days(now)
    to_arrival = max(0.0, coast - elapsed)
    out: dict[str, Any] = {}
    for name, rate in RATES_KG_PER_PERSON_DAY.items():
        per_day = rate * PROFILE.crew
        loaded = per_day * (coast + RESERVE_DAYS)
        left = max(0.0, loaded - per_day * elapsed)
        lasts = left / per_day
        out[name] = {
            "remaining_kg": round(left),
            "remaining_fraction": round(left / loaded, 3),
            "days_left_at_current_use": round(lasts),
            "margin_days_after_arrival": round(lasts - to_arrival),
        }
    return out
