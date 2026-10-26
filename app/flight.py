"""A sped-up flight along the mission profile, with faults spread along the route.

The whole coast takes FLIGHT_S real seconds at 1×, whichever mission is selected. Each fault shows as a caution
a few mission days before it trips, then fires one alert through app/simulate.py. The ship holds
position while a crew decision is open, so faults arrive one at a time instead of all at once.
State lives in queue/flight.json so a server reload picks the flight back up.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timedelta
from typing import Any

from app import mission, simulate
from app.gate import action_for
from schema import ALERT_QUEUE, Alert

FLIGHT = ALERT_QUEUE.parent / "flight.json"
FLIGHT_S = 300
SPEEDS = (0.5, 1.0, 2.0, 4.0)
# A caution shows this share of the transit before its fault trips.
CAUTION_LEAD = 0.03
# A long poll gap (server reload, laptop asleep) must not teleport the ship past several faults.
MAX_STEP_S = 3.0
# Real seconds the crew has to answer a decision before the mission is lost. Pausing does not stop it.
DECISION_LIMIT_S = 60.0

# (share of the transit, scenario). Each run jitters the shares so the demo never plays the same twice.
# Shares sit at least 2 × JITTER apart so the faults always fire in this order.
ROUTE: tuple[tuple[float, str], ...] = (
    (0.05, "power_bus"),
    (0.11, "co2_scrubber"),
    (0.18, "reaction_wheel"),
    (0.25, "thruster_valve"),
    (0.32, "solar_flare"),
    (0.39, "transponder"),
    (0.46, "battery_runaway"),
    (0.53, "cooling_loop"),
    (0.60, "cabin_leak"),
    (0.67, "avionics_fire"),
    (0.74, "flight_computer"),
    (0.81, "tumble"),
    (0.89, "antenna_deploy"),
)
JITTER = 0.025


def _coast() -> float:
    return mission._coast_days()


def _load() -> dict[str, Any] | None:
    if not FLIGHT.exists():
        return None
    return json.loads(FLIGHT.read_text())


def _save(f: dict[str, Any]) -> None:
    FLIGHT.parent.mkdir(parents=True, exist_ok=True)
    tmp = FLIGHT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(f, indent=2) + "\n")
    os.replace(tmp, FLIGHT)


def active() -> bool:
    f = _load()
    return bool(f and f["active"])


def start(speed: float = 1.0) -> dict[str, Any]:
    rng = random.Random()
    coast = _coast()
    events = [
        {"day": round(min(0.95, max(0.03, share + rng.uniform(-JITTER, JITTER))) * coast, 2), "scenario": name, "alert_id": None}
        for share, name in ROUTE
    ]
    f = {
        "active": True,
        "paused": False,
        "finished": False,
        "speed": speed if speed in SPEEDS else 1.0,
        "elapsed_days": 0.0,
        "updated": time.time(),
        "events": events,
    }
    _save(f)
    return f


def stop() -> None:
    FLIGHT.unlink(missing_ok=True)


def control(action: str, speed: float | None = None) -> dict[str, Any]:
    f = _load()
    if not f:
        raise LookupError("No flight running")
    if action == "pause":
        f["paused"] = True
    elif action == "resume":
        f["paused"] = False
    elif action == "speed" and speed in SPEEDS:
        f["speed"] = speed
    else:
        raise ValueError(f"Unknown flight control {action!r}")
    f["updated"] = time.time()
    _save(f)
    return f


def _hold(f: dict[str, Any], awaiting: set[str]) -> str | None:
    return next((e["alert_id"] for e in f["events"] if e["alert_id"] in awaiting), None)


def advance(awaiting: set[str]) -> Alert | None:
    """Move the ship on by the wall time since the last call. Returns the alert that fired, if any."""
    f = _load()
    if not f or not f["active"]:
        return None
    t = time.time()
    dt = min(MAX_STEP_S, max(0.0, t - f["updated"]))
    f["updated"] = t
    hold = None if f["finished"] else _hold(f, awaiting)
    prev = f.get("hold_id")
    if hold != prev:
        # Unfired events also have alert_id None, so a missing hold is not an answer.
        started = f.get("hold_since")
        if prev is not None and started is not None:
            answered = next((e for e in f["events"] if e["alert_id"] == prev), None)
            if answered:
                answered["response_s"] = round(t - started, 1)
        f["hold_id"] = hold
        f["hold_since"] = t
    elif hold is not None and f.get("hold_since") is None:
        f["hold_since"] = t
    started = f.get("hold_since")
    if hold and started is not None and t - started > DECISION_LIMIT_S:
        scenario = next(e["scenario"] for e in f["events"] if e["alert_id"] == hold)
        f["finished"] = True
        f["failed"] = {"alert_id": hold, "text": action_for(simulate.SCENARIOS[scenario].channel).if_not_done}
        f["hold_id"] = None
    if f["paused"] or f["finished"] or hold:
        _save(f)
        return None

    coast = _coast()
    elapsed = f["elapsed_days"] + dt * f["speed"] * coast / FLIGHT_S
    fired = None
    upcoming = next((e for e in f["events"] if e["alert_id"] is None), None)
    if upcoming and elapsed >= upcoming["day"]:
        # Stop the ship on the fault so the marker and the alert line up.
        elapsed = upcoming["day"]
        fired = simulate.inject(upcoming["scenario"])
        upcoming["alert_id"] = fired.alert_id
    f["elapsed_days"] = round(min(elapsed, coast), 3)
    if f["elapsed_days"] >= coast:
        f["finished"] = True
    _save(f)
    return fired


def mission_now() -> datetime | None:
    """The mission clock the trajectory should use while a flight runs, otherwise None (wall clock)."""
    f = _load()
    if not f or not f["active"]:
        return None
    return mission.launch_utc() + timedelta(days=f["elapsed_days"])


def view(awaiting: set[str]) -> dict[str, Any] | None:
    f = _load()
    if not f or not f["active"]:
        return None
    coast = _coast()
    elapsed = f["elapsed_days"]
    hold = None if f["finished"] else _hold(f, awaiting)
    deadline = None
    started = f.get("hold_since")
    if hold and f.get("hold_id") == hold and started is not None:
        deadline = round(max(0.0, DECISION_LIMIT_S - (time.time() - started)), 1)
    caution = None
    upcoming = next((e for e in f["events"] if e["alert_id"] is None), None)
    if upcoming and not f["finished"] and upcoming["day"] - elapsed <= CAUTION_LEAD * coast:
        s = simulate.SCENARIOS[upcoming["scenario"]]
        caution = {"channel": s.channel, "text": s.watch, "in_days": round(upcoming["day"] - elapsed, 1)}
    return {
        "paused": f["paused"],
        "finished": f["finished"],
        "speed": f["speed"],
        "speeds": list(SPEEDS),
        "elapsed_days": elapsed,
        "transit_days": round(coast, 1),
        "progress": round(min(elapsed / coast, 1.0), 4),
        "days_per_s": 0 if (f["paused"] or f["finished"] or hold) else round(f["speed"] * coast / FLIGHT_S, 3),
        "hold_alert_id": hold,
        "decision_limit_s": DECISION_LIMIT_S,
        "decision_left_s": deadline,
        "failed": f.get("failed"),
        "caution": caution,
        "events": [
            {"day": e["day"], "progress": round(e["day"] / coast, 4), "alert_id": e["alert_id"], "response_s": e.get("response_s")}
            for e in f["events"]
            if e["alert_id"]
        ],
        "remaining_events": sum(1 for e in f["events"] if e["alert_id"] is None),
        "total_events": len(f["events"]),
    }
