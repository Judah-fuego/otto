"""Hohmann transfers, the rocket equation, and crew consumables. No ML.

Every trip leaves a 300 km Earth parking orbit. The Moon is a transfer around Earth into a
100 km lunar orbit. Planets are a transfer around the Sun on circular, coplanar orbits.
Rocky worlds capture into a low circular orbit. Giants capture into a long ellipse, as
Juno and Cassini did, because a circular capture there costs more than the whole trip.
Propellant is sized for the dry mass plus the crew's consumables, since both ride the burn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from schema import (
    DESTINATIONS,
    EPHEMERIS,
    FOOD_KG_PER_PERSON_DAY,
    ORIGINS,
    OXYGEN_KG_PER_PERSON_DAY,
    ROUTES,
    WATER_KG_PER_PERSON_DAY,
    VoyageRequest,
    VoyageResult,
    parse_voyage_request,
)

G0 = 9.80665  # m/s^2
DAY_S = 86_400.0
AU_KM = 149_597_870.7

MU_SUN = 1.32712440018e11  # km^3/s^2
MU_EARTH = 398_600.4418
EARTH_PARKING_KM = 6_378.137 + 300.0
EARTH_ORBIT_AU = 1.0

MU_MOON = 4_902.800
MOON_CAPTURE_KM = 1_737.4 + 100.0
MOON_ORBIT_KM = 384_400.0

# How far off ROUTES the Hohmann time may land before something is wrong.
TRAVEL_TIME_TOLERANCE = 0.05


@dataclass(frozen=True)
class Body:
    orbit_au: float
    period_days: float
    mu: float  # km^3/s^2
    radius_km: float
    capture_altitude_km: float
    capture_eccentricity: float
    ephemeris_name: str


PLANETS: dict[str, Body] = {
    "mercury": Body(0.387098, 87.969, 22_031.8, 2_439.7, 200.0, 0.0, "mercury barycenter"),
    "venus": Body(0.723332, 224.701, 324_858.6, 6_051.8, 300.0, 0.0, "venus barycenter"),
    "mars": Body(1.523679, 686.98, 42_828.37, 3_389.5, 400.0, 0.0, "mars barycenter"),
    "jupiter": Body(5.2044, 4_332.59, 126_686_534.0, 69_911.0, 34_956.0, 0.9, "jupiter barycenter"),
    "saturn": Body(9.5826, 10_759.22, 37_931_187.0, 58_232.0, 29_116.0, 0.9, "saturn barycenter"),
    "uranus": Body(19.2184, 30_688.5, 5_793_939.0, 25_362.0, 12_681.0, 0.9, "uranus barycenter"),
    "neptune": Body(30.11, 60_182.0, 6_836_529.0, 24_622.0, 12_311.0, 0.9, "neptune barycenter"),
    "pluto": Body(39.482, 90_560.0, 869.6, 1_188.3, 100.0, 0.0, "pluto barycenter"),
}

if set(PLANETS) | {"moon"} != set(DESTINATIONS):
    raise RuntimeError("PLANETS and schema.DESTINATIONS disagree")


def _hohmann(mu: float, r1: float, r2: float) -> tuple[float, float, float]:
    """Burn at departure, burn at arrival (km/s, both positive), and coast time (s)."""
    a = (r1 + r2) / 2
    dv1 = abs(math.sqrt(mu / r1) * (math.sqrt(2 * r2 / (r1 + r2)) - 1))
    dv2 = abs(math.sqrt(mu / r2) * (1 - math.sqrt(2 * r1 / (r1 + r2))))
    return dv1, dv2, math.pi * math.sqrt(a**3 / mu)


def _escape_burn(mu: float, r: float, v_inf: float) -> float:
    """Burn from a circular orbit of radius r onto a hyperbola with excess speed v_inf."""
    return math.sqrt(v_inf**2 + 2 * mu / r) - math.sqrt(mu / r)


def _capture_burn(mu: float, periapsis: float, eccentricity: float, v_inf: float) -> float:
    """Burn at periapsis from a hyperbola into an orbit of the given eccentricity."""
    return math.sqrt(v_inf**2 + 2 * mu / periapsis) - math.sqrt(mu * (1 + eccentricity) / periapsis)


def _to_moon() -> tuple[float, float]:
    # At apogee the craft lags the Moon by exactly the circularization burn.
    tli, v_inf, t = _hohmann(MU_EARTH, EARTH_PARKING_KM, MOON_ORBIT_KM)
    return tli + _capture_burn(MU_MOON, MOON_CAPTURE_KM, 0.0, v_inf), t


def _to_planet(body: Body) -> tuple[float, float]:
    v_dep, v_arr, t = _hohmann(MU_SUN, EARTH_ORBIT_AU * AU_KM, body.orbit_au * AU_KM)
    periapsis = body.radius_km + body.capture_altitude_km
    dv = _escape_burn(MU_EARTH, EARTH_PARKING_KM, v_dep) + _capture_burn(
        body.mu, periapsis, body.capture_eccentricity, v_arr
    )
    return dv, t


def _launch_window(body: Body, after: datetime, coast_days: float) -> str | None:
    """Next date the target leads Earth by the Hohmann phase angle, from the DE421 ephemeris."""
    if not EPHEMERIS.exists():
        return None
    from skyfield.api import load

    eph = load(str(EPHEMERIS))
    ts = load.timescale()
    sun, earth, target = eph["sun"], eph["earth"], eph[body.ephemeris_name]
    days = np.arange(0, 2 * 780)  # two of the longest synodic periods (Mars)
    t = ts.utc(after.year, after.month, after.day + days)

    def longitude(b) -> np.ndarray:
        _, lon, _ = (b - sun).at(t).ecliptic_latlon()
        return lon.degrees

    lead = (180.0 - 360.0 * coast_days / body.period_days) % 360.0
    phase = (longitude(target) - longitude(earth)) % 360.0
    offset = (phase - lead + 180.0) % 360.0 - 180.0
    # A real crossing moves a few degrees a day. A jump near ±180 is the wrap, not a window.
    crossed = (np.sign(offset[:-1]) != np.sign(offset[1:])) & (np.abs(offset[1:] - offset[:-1]) < 90.0)
    hits = np.nonzero(crossed)[0]
    if not len(hits):
        return None
    return t[hits[0] + 1].utc_strftime("%Y-%m-%dT00:00:00Z")


def voyage_calculate(request: VoyageRequest | dict, now: datetime | None = None) -> VoyageResult:
    if isinstance(request, dict):
        request = parse_voyage_request(request)
    if request.origin not in ORIGINS or request.destination not in DESTINATIONS:
        raise ValueError(f"Route {request.origin} → {request.destination} is not supported")

    body = PLANETS.get(request.destination)
    dv_km_s, coast_s = _to_planet(body) if body else _to_moon()
    days = coast_s / DAY_S
    expected = ROUTES.get((request.origin, request.destination))
    if expected and abs(days - expected) > TRAVEL_TIME_TOLERANCE * expected:
        raise RuntimeError(f"{request.destination}: Hohmann time {days:.1f} d is far from the {expected} d check")

    person_days = request.crew * days
    oxygen = OXYGEN_KG_PER_PERSON_DAY * person_days
    water = WATER_KG_PER_PERSON_DAY * person_days
    food = FOOD_KG_PER_PERSON_DAY * person_days

    payload = request.spacecraft_mass_kg + oxygen + water + food
    dv_m_s = dv_km_s * 1000
    propellant = payload * (math.exp(dv_m_s / (request.isp_s * G0)) - 1)

    now = now or datetime.now(timezone.utc)
    # The Moon opens every day from a parking orbit, so only planets get a dated window.
    window = _launch_window(body, now, days) if body else None

    return VoyageResult(
        origin=request.origin,
        destination=request.destination,
        delta_v_m_s=round(dv_m_s, 1),
        travel_time_days=round(days, 1),
        propellant_kg=round(propellant, 1),
        launch_window_utc=window,
        crew=request.crew,
        oxygen_kg=round(oxygen, 1),
        water_kg=round(water, 1),
        food_kg=round(food, 1),
    )
