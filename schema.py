"""Shared contract for anomaly events. Change this file only when both people agree.

The detector (ml/) and the voyage simulator (sim/) emit these events.
The authority gate (agent/) and the Guide (app/) consume them.
mock_events.json is the same shape, so the Grok side can run before the model exists.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# Table 8 in the Space AI survey: fault detection and autonomous recovery.
# Keys are the ids used in events. Labels are for the Guide.
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

# SMAP channel ids are anonymized. Telemanom documents P = power and R = radiation.
# Every other letter is this repo's assignment onto Table 8, so both sides name
# subsystems the same way. Do not invent a second map.
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

# Ten SMAP channels for training. The five-channel fallback is the first five
# of the demo story: power, attitude, thermal, comms, life support.
DEFAULT_CHANNELS: tuple[str, ...] = (
    "P-1",
    "A-1",
    "T-1",
    "S-1",
    "F-1",
    "E-1",
    "G-1",
    "R-1",
    "D-1",
    "B-1",
)
FALLBACK_CHANNELS: tuple[str, ...] = DEFAULT_CHANNELS[:5]

# Mission clock origin for the demo scenario. Event `time` is this clock, not a
# SMAP sample index. Sample index → mission time is the simulator's job.
DEMO_T0 = "2026-10-25T18:00:00Z"


class Authority(str, Enum):
    """What the gate may return. The rule itself lives in agent/."""

    AUTO = "auto"
    ASK_CREW = "ask_crew"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class AnomalyEvent:
    """One detected anomaly.

    time: mission clock, UTC, `YYYY-MM-DDTHH:MM:SSZ`.
    channel: SMAP channel id, such as `A-1`.
    subsystem: a key of SUBSYSTEMS.
    confidence: ensemble score in [0, 1].
    ground_contact: true when a ground station can see the spacecraft.
    event_id: stable id shared with the scenario file and the audit log.
    """

    time: str
    channel: str
    subsystem: str
    confidence: float
    ground_contact: bool
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def mission_time(t_min: float, t0: str = DEMO_T0) -> str:
    """Minutes after the demo epoch, as a UTC timestamp."""
    start = datetime.fromisoformat(t0.replace("Z", "+00:00")).astimezone(timezone.utc)
    stamp = start + timedelta(minutes=float(t_min))
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def subsystem_for_channel(channel: str) -> str:
    prefix = channel.split("-", 1)[0].upper()
    try:
        return CHANNEL_PREFIX_TO_SUBSYSTEM[prefix]
    except KeyError as exc:
        known = ", ".join(sorted(CHANNEL_PREFIX_TO_SUBSYSTEM))
        raise ValueError(f"No Table 8 subsystem for channel {channel!r}. Known prefixes: {known}") from exc


def parse_event(raw: dict[str, Any]) -> AnomalyEvent:
    missing = [key for key in ("time", "channel", "subsystem", "confidence", "ground_contact", "event_id") if key not in raw]
    if missing:
        raise ValueError(f"Event {raw.get('event_id', raw)!r} is missing {missing}")

    channel = str(raw["channel"])
    subsystem = str(raw["subsystem"])
    if subsystem not in SUBSYSTEMS:
        raise ValueError(f"Unknown subsystem {subsystem!r} on {raw['event_id']!r}")
    expected = subsystem_for_channel(channel)
    if subsystem != expected:
        raise ValueError(
            f"{raw['event_id']!r}: channel {channel} belongs to {expected}, not {subsystem}"
        )

    confidence = float(raw["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"{raw['event_id']!r}: confidence {confidence} is outside [0, 1]")

    ground_contact = raw["ground_contact"]
    if not isinstance(ground_contact, bool):
        raise ValueError(f"{raw['event_id']!r}: ground_contact must be true or false, not {ground_contact!r}")

    time = str(raw["time"])
    datetime.fromisoformat(time.replace("Z", "+00:00"))

    return AnomalyEvent(
        time=time,
        channel=channel,
        subsystem=subsystem,
        confidence=confidence,
        ground_contact=ground_contact,
        event_id=str(raw["event_id"]),
    )


def load_events(path: Path | str) -> list[AnomalyEvent]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, list):
        raise ValueError(f"{path} must be a JSON list of events")
    events = [parse_event(item) for item in payload]
    ids = [event.event_id for event in events]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate event_id in {path}")
    return events


def dump_events(events: list[AnomalyEvent], path: Path | str) -> None:
    Path(path).write_text(json.dumps([event.to_dict() for event in events], indent=2) + "\n")


def _check_demo_alignment(root: Path) -> None:
    events = {event.event_id: event for event in load_events(root / "mock_events.json")}
    scenario = json.loads((root / "sim" / "scenarios" / "demo.json").read_text())
    faults = {fault["event_id"]: fault for fault in scenario["faults"]}
    if set(events) != set(faults):
        raise SystemExit(f"event ids differ: mock={sorted(events)} scenario={sorted(faults)}")
    for event_id, fault in faults.items():
        event = events[event_id]
        expected_time = mission_time(fault["t_min"], scenario.get("t0", DEMO_T0))
        if event.time != expected_time or event.channel != fault["channel"]:
            raise SystemExit(f"{event_id} does not match sim/scenarios/demo.json")
        if event.ground_contact:
            raise SystemExit(f"{event_id} is a blackout fault and ground_contact must be false")


if __name__ == "__main__":
    _check_demo_alignment(Path(__file__).resolve().parent)
    print("mock_events.json matches sim/scenarios/demo.json")
