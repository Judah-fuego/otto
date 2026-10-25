"""Next launch window from DE421 via Skyfield. Returns None if the kernel is missing."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from schema import EPHEMERIS, ROUTES

from voyage.physics import MARS_AU, MU_SUN, AU


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_eph():
    if not EPHEMERIS.exists():
        return None, None
    from skyfield.api import load, load_file

    return load.timescale(), load_file(str(EPHEMERIS))


def _angle_error(actual: float, required: float) -> float:
    return abs((actual - required + math.pi) % (2.0 * math.pi) - math.pi)


def next_earth_mars_window(now: datetime | None = None) -> str | None:
    """First Hohmann phase-angle match, searching up to one synodic period."""
    ts, eph = _load_eph()
    if ts is None:
        return None
    sun, earth, mars = eph["sun"], eph["earth"], eph["mars"]
    t_tof_s = ROUTES[("earth", "mars")] * 86400.0
    n_mars = math.sqrt(MU_SUN / (MARS_AU * AU) ** 3)
    required_lead = math.pi - n_mars * t_tof_s

    t0 = ts.from_datetime((now or datetime.now(timezone.utc)).astimezone(timezone.utc))
    best_i, best_err = 0, 1e9
    # Daily scan. A window is the first day the error bottoms out under 4°.
    prev_err = None
    for i in range(0, 800):
        t = ts.tt_jd(t0.tt + i)
        earth_helio = (earth - sun).at(t)
        mars_helio = (mars - sun).at(t)
        _, lon_e, _ = earth_helio.ecliptic_latlon()
        _, lon_m, _ = mars_helio.ecliptic_latlon()
        lead = (lon_m.radians - lon_e.radians) % (2.0 * math.pi)
        err = _angle_error(lead, required_lead)
        if err < best_err:
            best_err, best_i = err, i
        if prev_err is not None and err > prev_err and prev_err < math.radians(4.0) and i > 2:
            t_win = ts.tt_jd(t0.tt + (i - 1))
            return _fmt(t_win.utc_datetime())
        prev_err = err
    t_win = ts.tt_jd(t0.tt + best_i)
    return _fmt(t_win.utc_datetime())


def next_leo_moon_window(now: datetime | None = None) -> str | None:
    """Next lunar nodal crossing: a low-inclination TLI prefers |β| ≈ 0."""
    ts, eph = _load_eph()
    if ts is None:
        return None
    earth, moon = eph["earth"], eph["moon"]
    t0 = ts.from_datetime((now or datetime.now(timezone.utc)).astimezone(timezone.utc))
    best_i, best_lat = 0, 1e9
    prev = None
    for i in range(0, 28 * 24):
        t = ts.tt_jd(t0.tt + i / 24.0)
        apparent = earth.at(t).observe(moon)
        lat, _, _ = apparent.ecliptic_latlon()
        mag = abs(lat.radians)
        if mag < best_lat:
            best_lat, best_i = mag, i
        if prev is not None and mag > prev and prev < math.radians(1.0) and i > 2:
            t_win = ts.tt_jd(t0.tt + (i - 1) / 24.0)
            return _fmt(t_win.utc_datetime())
        prev = mag
    t_win = ts.tt_jd(t0.tt + best_i / 24.0)
    return _fmt(t_win.utc_datetime())


def launch_window_utc(origin: str, destination: str, now: datetime | None = None) -> str | None:
    if (origin, destination) == ("earth", "mars"):
        return next_earth_mars_window(now)
    if (origin, destination) == ("leo", "moon"):
        return next_leo_moon_window(now)
    return None
