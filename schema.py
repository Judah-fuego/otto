"""Shared contracts. Change this file only when both people agree.

1. Alert — SafeMode writes these. The chat reads them.
2. Voyage — inputs and outputs of voyage_calculate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# Live queue written by safemode/. Gitignored. mock_alerts.json stands in until it exists.
ALERT_QUEUE = ROOT / "queue" / "alerts.json"
MOCK_ALERTS = ROOT / "mock_alerts.json"
EPHEMERIS = ROOT / "data" / "ephemeris" / "de421.bsp"

# Table 8 in the Space AI survey.
SUBSYSTEMS: dict[str, dict[str, str]] = {
    "attitude_control": {
        "label": "Attitude Control",
        "examples": "gyro degradation, star-tracker drift, reaction-wheel degradation",
    },
    "power_eps": {
        "label": "Power (EPS)",
        "examples": "solar-array degradation, battery fade, bus voltage anomalies",
    },
    "thermal_control": {
        "label": "Thermal Control",
        "examples": "cooling-loop leak, thermal-sensor drift, overheating",
    },
    "communications": {
        "label": "Communications",
        "examples": "antenna pointing loss, transponder dropouts",
    },
    "data_handling": {
        "label": "Data Handling",
        "examples": "CPU reset, memory upsets (SEUs), software faults",
    },
    "propulsion": {
        "label": "Propulsion",
        "examples": "thruster stuck, valve leak, propellant anomalies",
    },
    "mechanisms": {
        "label": "Mechanisms",
        "examples": "solar-array deployment, antenna deployment",
    },
    "life_support": {
        "label": "Life Support",
        "examples": "cabin leak, CO2 scrubbing, O2 generation",
    },
}

# SMAP ids are anonymized. Telemanom documents P = power and R = radiation.
# Every other letter is this repo's map onto Table 8. One map only.
CHANNEL_PREFIX_TO_SUBSYSTEM: dict[str, str] = {
    "A": "attitude_control",
    "G": "attitude_control",
    "P": "power_eps",
    "B": "power_eps",
    "T": "thermal_control",
    "S": "communications",
    "R": "data_handling",
    "D": "propulsion",
    "E": "mechanisms",
    "F": "life_support",
}

DEFAULT_CHANNELS: tuple[str, ...] = (
    "P-1",
    "A-1",
    "T-1",
    "S-1",
    "F-2",
    "E-1",
    "G-1",
    "R-1",
    "D-1",
    "B-1",
)
FALLBACK_CHANNELS: tuple[str, ...] = DEFAULT_CHANNELS[:5]

# voyage_calculate leaves a 300 km Earth parking orbit, so both origins depart from the same place.
ORIGINS: tuple[str, ...] = ("leo", "earth")
DESTINATIONS: tuple[str, ...] = (
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
)

# Travel-time checks for voyage_calculate, in days. Check values, not a formula.
ROUTES: dict[tuple[str, str], int] = {
    ("leo", "moon"): 5,
    ("earth", "mars"): 259,
}

# Crew consumption the calculator and the chat both use, kilograms per person per day.
OXYGEN_KG_PER_PERSON_DAY = 0.84
WATER_KG_PER_PERSON_DAY = 2.50
FOOD_KG_PER_PERSON_DAY = 1.80


class Authority(str, Enum):
    """Gate result. The rule lives in app/: reversible and confident → auto,
    cannot be undone → ask_crew, otherwise escalate."""

    AUTO = "auto"
    ASK_CREW = "ask_crew"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Alert:
    """One SafeMode anomaly. `values` is the recent telemetry, oldest first, last point is the alert."""

    alert_id: str
    time: str
    channel: str
    subsystem: str
    confidence: float
    values: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["values"] = list(self.values)
        return raw


@dataclass(frozen=True)
class VoyageRequest:
    origin: str
    destination: str
    spacecraft_mass_kg: float
    isp_s: float
    crew: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VoyageResult:
    origin: str
    destination: str
    delta_v_m_s: float
    travel_time_days: float
    propellant_kg: float
    launch_window_utc: str | None
    crew: int
    oxygen_kg: float
    water_kg: float
    food_kg: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def subsystem_for_channel(channel: str) -> str:
    prefix = channel.split("-", 1)[0].upper()
    try:
        return CHANNEL_PREFIX_TO_SUBSYSTEM[prefix]
    except KeyError as exc:
        known = ", ".join(sorted(CHANNEL_PREFIX_TO_SUBSYSTEM))
        raise ValueError(f"No Table 8 subsystem for channel {channel!r}. Known prefixes: {known}") from exc


def _parse_time(value: str, label: str) -> str:
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def parse_alert(raw: dict[str, Any]) -> Alert:
    missing = [key for key in ("alert_id", "time", "channel", "subsystem", "confidence", "values") if key not in raw]
    if missing:
        raise ValueError(f"Alert {raw.get('alert_id', raw)!r} is missing {missing}")

    channel = str(raw["channel"])
    subsystem = str(raw["subsystem"])
    if subsystem not in SUBSYSTEMS:
        raise ValueError(f"Unknown subsystem {subsystem!r}")
    expected = subsystem_for_channel(channel)
    if subsystem != expected:
        raise ValueError(f"{raw['alert_id']!r}: channel {channel} belongs to {expected}, not {subsystem}")

    confidence = float(raw["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"{raw['alert_id']!r}: confidence {confidence} is outside [0, 1]")

    values = tuple(float(item) for item in raw["values"])
    if len(values) < 2:
        raise ValueError(f"{raw['alert_id']!r}: values needs at least two points")

    return Alert(
        alert_id=str(raw["alert_id"]),
        time=_parse_time(str(raw["time"]), str(raw["alert_id"])),
        channel=channel,
        subsystem=subsystem,
        confidence=confidence,
        values=values,
    )


def load_alerts(path: Path | str = ALERT_QUEUE) -> list[Alert]:
    path = Path(path)
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"{path} must be a JSON list of alerts")
    alerts = [parse_alert(item) for item in payload]
    ids = [alert.alert_id for alert in alerts]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate alert_id in {path}")
    return alerts


def dump_alerts(alerts: list[Alert], path: Path | str = ALERT_QUEUE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([alert.to_dict() for alert in alerts], indent=2) + "\n")


def parse_voyage_request(raw: dict[str, Any]) -> VoyageRequest:
    origin = str(raw["origin"])
    destination = str(raw["destination"])
    if origin not in ORIGINS:
        raise ValueError(f"Origin {origin!r} is not supported. Use {', '.join(ORIGINS)}")
    if destination not in DESTINATIONS:
        raise ValueError(f"Destination {destination!r} is not supported. Use {', '.join(DESTINATIONS)}")
    mass = float(raw["spacecraft_mass_kg"])
    isp = float(raw["isp_s"])
    crew = int(raw["crew"])
    if mass <= 0 or isp <= 0 or crew < 1:
        raise ValueError("spacecraft_mass_kg, isp_s, and crew must be positive")
    return VoyageRequest(origin, destination, mass, isp, crew)


def parse_voyage_result(raw: dict[str, Any]) -> VoyageResult:
    request = parse_voyage_request(raw)
    window = raw.get("launch_window_utc")
    if window is not None:
        window = _parse_time(str(window), "launch_window_utc")
    result = VoyageResult(
        origin=request.origin,
        destination=request.destination,
        delta_v_m_s=float(raw["delta_v_m_s"]),
        travel_time_days=float(raw["travel_time_days"]),
        propellant_kg=float(raw["propellant_kg"]),
        launch_window_utc=window,
        crew=request.crew,
        oxygen_kg=float(raw["oxygen_kg"]),
        water_kg=float(raw["water_kg"]),
        food_kg=float(raw["food_kg"]),
    )
    if result.delta_v_m_s <= 0 or result.travel_time_days <= 0 or result.propellant_kg <= 0:
        raise ValueError("delta_v_m_s, travel_time_days, and propellant_kg must be positive")
    return result


if __name__ == "__main__":
    alerts = load_alerts(MOCK_ALERTS)
    ids = {alert.alert_id for alert in alerts}
    if ids != {"rw-backup", "cabin-leak"}:
        raise SystemExit(f"mock_alerts.json ids are {sorted(ids)}")
    parse_voyage_request(
        {
            "origin": "earth",
            "destination": "mars",
            "spacecraft_mass_kg": 10000,
            "isp_s": 300,
            "crew": 4,
        }
    )
    print(f"{len(alerts)} mock alerts ok; voyage request ok")
