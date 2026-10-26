"""The mission the crew is flying. Progress, consumables, and the light delay come from it.

The crew picks a mission in app.missions. That choice is the ship (origin, destination, crew,
dry mass, engines) and the path. Apollo is a transfer from a parking orbit to the Moon, drawn
with Earth at the center. Every other mission is a Hohmann on circular, coplanar orbits around
the Sun, same model as voyage/. The ship's place on the transfer and Earth's on its orbit give
the distance home, and so the light delay. Angles start where the ship left its departure orbit.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from app.missions import activate, catalog, current_mission
from schema import (
    FOOD_KG_PER_PERSON_DAY,
    OXYGEN_KG_PER_PERSON_DAY,
    WATER_KG_PER_PERSON_DAY,
    VoyageRequest,
)
from voyage import voyage_calculate
from voyage.calculator import AU_KM, EARTH_PARKING_KM, MOON_ORBIT_KM, PLANETS

# Consumables are loaded for the coast plus this reserve.
RESERVE_DAYS = 60

EARTH_YEAR_DAYS = 365.256
MOON_PERIOD_DAYS = 27.321661
LIGHT_KM_S = 299_792.458

RATES_KG_PER_PERSON_DAY = {
    "oxygen": OXYGEN_KG_PER_PERSON_DAY,
    "water": WATER_KG_PER_PERSON_DAY,
    "food": FOOD_KG_PER_PERSON_DAY,
}


def launch_utc() -> datetime:
    return current_mission().launch


def profile() -> VoyageRequest:
    spec = current_mission()
    return VoyageRequest(
        origin=spec.origin,
        destination=spec.destination,
        spacecraft_mass_kg=spec.spacecraft_mass_kg,
        isp_s=spec.isp_s,
        crew=spec.crew,
    )


@lru_cache(maxsize=16)
def _coast_for(destination: str) -> float:
    origin = "leo" if destination == "moon" else "earth"
    request = VoyageRequest(origin=origin, destination=destination, spacecraft_mass_kg=1_000, isp_s=300, crew=1)
    return voyage_calculate(request).travel_time_days


def _coast_days() -> float:
    return _coast_for(current_mission().destination)


def _elapsed_days(now: datetime | None) -> float:
    launch = launch_utc()
    if now is None:
        # Wall clock. A launch still ahead, or one that arrived years ago, waits at departure
        # until the crew flies it. A coast that is underway right now (Ares) stays live.
        elapsed = (datetime.now(timezone.utc) - launch).total_seconds() / 86_400
        if elapsed < 0 or elapsed > _coast_days():
            return 0.0
        return elapsed
    return max(0.0, (now - launch).total_seconds() / 86_400)


def _phase(now: datetime | None, elapsed: float, coast: float) -> str:
    if now is None:
        wall = (datetime.now(timezone.utc) - launch_utc()).total_seconds() / 86_400
        if wall < 0 or wall > coast:
            return "ready"
    if coast - elapsed > 1e-6:
        return "transit"
    return "arrived"


def _route() -> tuple[float, float, float, str]:
    """Departure radius (AU), arrival radius (AU), target period (days), and the map frame."""
    if current_mission().destination == "moon":
        return EARTH_PARKING_KM / AU_KM, MOON_ORBIT_KM / AU_KM, MOON_PERIOD_DAYS, "earth"
    body = PLANETS[current_mission().destination]
    return 1.0, body.orbit_au, body.period_days, "sun"


def _ship(elapsed: float, coast: float, r1: float, r2: float) -> tuple[float, float]:
    """Radius and polar angle on the transfer. Angle runs from 0 at departure to π at arrival.

    Outward legs leave from periapsis. Inward legs (Venus, Mercury) leave from apoapsis,
    so the same half-ellipse is walked the other way and still plotted from 0 to π.
    """
    a = (r1 + r2) / 2
    e = abs(r2 - r1) / (r1 + r2)
    frac = 0.0 if coast <= 0 else min(max(elapsed, 0.0), coast) / coast
    inward = r2 < r1
    mean = math.pi * (1 - frac) if inward else math.pi * frac
    ecc = mean
    for _ in range(30):
        denom = 1 - e * math.cos(ecc)
        ecc -= (ecc - e * math.sin(ecc) - mean) / denom
    theta = 2 * math.atan2(
        math.sqrt(1 + e) * math.sin(ecc / 2),
        math.sqrt(1 - e) * math.cos(ecc / 2),
    )
    angle = (math.pi - theta) if inward else theta
    return a * (1 - e * math.cos(ecc)), angle


def _layout(elapsed: float, coast: float) -> dict[str, Any]:
    r1, r2, period, frame = _route()
    ship_r, ship_angle = _ship(elapsed, coast, r1, r2)
    if frame == "earth":
        ex = ey = 0.0
    else:
        earth_angle = 2 * math.pi * elapsed / EARTH_YEAR_DAYS
        ex, ey = r1 * math.cos(earth_angle), r1 * math.sin(earth_angle)
    # The ship meets the destination on the far side of the central body at arrival.
    dest_angle = math.pi - 2 * math.pi * (coast - min(elapsed, coast)) / period
    dx, dy = r2 * math.cos(dest_angle), r2 * math.sin(dest_angle)
    sx, sy = ship_r * math.cos(ship_angle), ship_r * math.sin(ship_angle)

    def pt(x: float, y: float) -> list[float]:
        return [round(x, 6), round(y, 6)]

    return {
        "frame": frame,
        "r1": r1,
        "r2": r2,
        "distance_km": math.hypot(sx - ex, sy - ey) * AU_KM,
        "positions": {"earth": pt(ex, ey), "ship": pt(sx, sy), "destination": pt(dx, dy)},
    }


def light_delay_s(now: datetime | None = None) -> float:
    coast = _coast_days()
    return _layout(_elapsed_days(now), coast)["distance_km"] / LIGHT_KM_S


def trajectory(now: datetime | None = None) -> dict[str, Any]:
    spec = current_mission()
    coast, elapsed = _coast_days(), _elapsed_days(now)
    remaining = max(0.0, coast - elapsed)
    layout = _layout(elapsed, coast)
    delay_s = layout["distance_km"] / LIGHT_KM_S
    return {
        "id": spec.id,
        "mission": spec.name,
        "site": spec.site,
        "origin": spec.origin,
        "destination": spec.destination,
        "crew": spec.crew,
        "spacecraft_mass_kg": spec.spacecraft_mass_kg,
        "isp_s": spec.isp_s,
        "frame": layout["frame"],
        "phase": _phase(now, elapsed, coast),
        "launch_utc": spec.launch.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arrival_utc": (spec.launch + timedelta(days=coast)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mission_day": int(elapsed) + 1,
        "transit_days": round(coast),
        "days_to_arrival": round(remaining, 1),
        "progress": round(min(elapsed / coast, 1.0), 3) if coast else 1.0,
        "distance_to_earth_km": round(layout["distance_km"]),
        "one_way_light_delay_s": round(delay_s, 1),
        "one_way_light_delay_min": round(delay_s / 60, 1),
        "orbits_au": {"earth": layout["r1"], "destination": layout["r2"]},
        "positions_au": layout["positions"],
    }


def consumables(now: datetime | None = None) -> dict[str, Any]:
    coast, elapsed = _coast_days(), _elapsed_days(now)
    to_arrival = max(0.0, coast - elapsed)
    crew = current_mission().crew
    out: dict[str, Any] = {}
    for name, rate in RATES_KG_PER_PERSON_DAY.items():
        per_day = rate * crew
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


__all__ = ["activate", "catalog", "consumables", "current_mission", "launch_utc", "light_delay_s", "profile", "trajectory"]
