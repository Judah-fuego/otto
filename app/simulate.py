"""Scripted alerts for the demo. They go to queue/simulated.json and sit beside the real alerts.

The gate still decides who acts, so each scenario only picks a subsystem and a confidence.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from schema import ALERT_QUEUE, Alert, dump_alerts, load_alerts, subsystem_for_channel

SIMULATED = ALERT_QUEUE.parent / "simulated.json"

# scenario → (channel, confidence, signed size of the step in the last quarter)
SCENARIOS: dict[str, tuple[str, float, float]] = {
    "reaction_wheel": ("A-1", 0.94, 0.8),
    "power_bus": ("P-1", 0.91, -0.6),
    "cooling_loop": ("T-1", 0.89, 0.7),
    "transponder": ("S-1", 0.62, -0.5),
    "cabin_leak": ("F-2", 0.78, -0.7),
    "thruster_valve": ("D-1", 0.83, 0.9),
}


def load() -> list[Alert]:
    return load_alerts(SIMULATED)


def inject(scenario: str) -> Alert:
    channel, confidence, step = SCENARIOS[scenario]
    now = datetime.now(timezone.utc)
    rng = random.Random()
    values = [round(rng.gauss(0.0, 0.04), 3) for _ in range(18)]
    values += [round(step * (i + 1) / 6 + rng.gauss(0.0, 0.03), 3) for i in range(6)]
    alert = Alert(
        alert_id=f"sim-{channel}-{now.strftime('%H%M%S')}{rng.randint(0, 9)}",
        time=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        channel=channel,
        subsystem=subsystem_for_channel(channel),
        confidence=confidence,
        values=tuple(values),
    )
    dump_alerts([*load(), alert], SIMULATED)
    return alert


def clear() -> None:
    SIMULATED.unlink(missing_ok=True)
