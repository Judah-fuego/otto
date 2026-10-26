"""Scripted alerts for the demo. They go to queue/simulated.json and sit beside the real alerts.

The gate still decides who acts, so each scenario only picks a subsystem, a confidence, and how
the telemetry misbehaves before it trips.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from schema import ALERT_QUEUE, Alert, dump_alerts, load_alerts, subsystem_for_channel

SIMULATED = ALERT_QUEUE.parent / "simulated.json"

BASELINE_SAMPLES = 36
FAULT_SAMPLES = 12


@dataclass(frozen=True)
class Scenario:
    channel: str
    confidence: float
    # Signed size of the excursion, in the channel's (-1, 1) scale.
    step: float
    # drift: slow creep, step: sudden jump, oscillation: growing wobble.
    shape: str
    # What SafeMode reports while the reading is still inside limits.
    watch: str


# What a fault does if the crew runs out of time lives with its action in app/gate.py.
SCENARIOS: dict[str, Scenario] = {
    "reaction_wheel": Scenario("A-1", 0.94, 0.8, "oscillation", "Reaction wheel 2 vibration rising"),
    "power_bus": Scenario("P-1", 0.91, -0.6, "drift", "Main bus voltage sagging"),
    "cooling_loop": Scenario("T-1", 0.89, 0.7, "drift", "Coolant loop A temperature creeping up"),
    "transponder": Scenario("S-1", 0.62, -0.5, "step", "Downlink signal-to-noise dropping"),
    "flight_computer": Scenario("R-1", 0.9, 0.6, "step", "Memory scrub errors climbing on the primary computer"),
    "thruster_valve": Scenario("D-1", 0.83, 0.9, "drift", "Thruster branch B feed pressure off-nominal"),
    "cabin_leak": Scenario("F-2", 0.78, -0.7, "drift", "Cabin pressure trending down"),
    "antenna_deploy": Scenario("E-1", 0.81, -0.8, "step", "High-gain antenna boom motor stalling"),
    "co2_scrubber": Scenario("F-3", 0.88, 0.8, "drift", "Cabin CO2 climbing, scrubber bed C output rising"),
    "battery_runaway": Scenario("P-3", 0.92, 0.85, "drift", "Battery 3 cell temperature climbing"),
    "avionics_fire": Scenario("T-2", 0.87, 0.9, "step", "Smoke detector reading up in the avionics bay"),
    "tumble": Scenario("G-2", 0.93, 0.8, "oscillation", "Body rates rising, the ship is starting to tumble"),
    "solar_flare": Scenario("R-2", 0.9, 0.9, "step", "Proton flux rising, solar particle event inbound"),
}


def load() -> list[Alert]:
    return load_alerts(SIMULATED)


def _fault(shape: str, step: float, i: int, rng: random.Random) -> float:
    x = (i + 1) / FAULT_SAMPLES
    if shape == "step":
        level = step * (0.85 if i >= 2 else 0.3 * (i + 1))
    elif shape == "oscillation":
        level = step * x * math.sin(i * 1.7) + step * 0.5 * x
    else:
        level = step * x**1.6
    return round(level + rng.gauss(0.0, 0.03), 3)


def inject(scenario: str) -> Alert:
    s = SCENARIOS[scenario]
    now = datetime.now(timezone.utc)
    rng = random.Random()
    values = [round(rng.gauss(0.0, 0.04), 3) for _ in range(BASELINE_SAMPLES)]
    values += [_fault(s.shape, s.step, i, rng) for i in range(FAULT_SAMPLES)]
    alert = Alert(
        alert_id=f"sim-{s.channel}-{now.strftime('%H%M%S')}{rng.randint(0, 9)}",
        time=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        channel=s.channel,
        subsystem=subsystem_for_channel(s.channel),
        confidence=s.confidence,
        values=tuple(values),
    )
    dump_alerts([*load(), alert], SIMULATED)
    return alert


def clear() -> None:
    SIMULATED.unlink(missing_ok=True)
