"""Hohmann transfer, rocket equation, and crew consumables."""

from __future__ import annotations

import math

from schema import (
    FOOD_KG_PER_PERSON_DAY,
    OXYGEN_KG_PER_PERSON_DAY,
    ROUTES,
    WATER_KG_PER_PERSON_DAY,
)

G0 = 9.80665
MU_SUN = 1.32712440018e20
MU_EARTH = 3.986004418e14
AU = 1.495978707e11
R_EARTH_M = 6_371_000.0
LEO_ALTITUDE_M = 400_000.0
MARS_AU = 1.523679
MOON_SMA_M = 384_400_000.0

# Circular coplanar radii for the two supported routes.
RADII_M: dict[tuple[str, str], tuple[float, float, float]] = {
    ("earth", "mars"): (1.0 * AU, MARS_AU * AU, MU_SUN),
    ("leo", "moon"): (R_EARTH_M + LEO_ALTITUDE_M, MOON_SMA_M, MU_EARTH),
}


def hohmann_delta_v_m_s(r1: float, r2: float, mu: float) -> float:
    a = 0.5 * (r1 + r2)
    v1 = math.sqrt(mu / r1)
    v2 = math.sqrt(mu / r2)
    vt1 = math.sqrt(mu * (2.0 / r1 - 1.0 / a))
    vt2 = math.sqrt(mu * (2.0 / r2 - 1.0 / a))
    return abs(vt1 - v1) + abs(v2 - vt2)


def hohmann_time_s(r1: float, r2: float, mu: float) -> float:
    a = 0.5 * (r1 + r2)
    return math.pi * math.sqrt(a**3 / mu)


def rocket_propellant_kg(dry_mass_kg: float, delta_v_m_s: float, isp_s: float) -> float:
    return dry_mass_kg * (math.exp(delta_v_m_s / (isp_s * G0)) - 1.0)


def consumables_kg(crew: int, travel_time_days: float) -> tuple[float, float, float]:
    days = crew * travel_time_days
    return (
        days * OXYGEN_KG_PER_PERSON_DAY,
        days * WATER_KG_PER_PERSON_DAY,
        days * FOOD_KG_PER_PERSON_DAY,
    )


def route_elements(origin: str, destination: str) -> tuple[float, float, float, float]:
    key = (origin, destination)
    if key not in RADII_M:
        allowed = ", ".join(f"{a} → {b}" for a, b in ROUTES)
        raise ValueError(f"No physics for {origin!r} → {destination!r}. Use {allowed}")
    r1, r2, mu = RADII_M[key]
    check_days = float(ROUTES[key])
    computed_days = hohmann_time_s(r1, r2, mu) / 86400.0
    if abs(computed_days - check_days) > 1.5:
        raise ValueError(
            f"{origin}→{destination} Hohmann is {computed_days:.2f} days, "
            f"schema.ROUTES expects about {check_days:.0f}"
        )
    return r1, r2, mu, check_days
