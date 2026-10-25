"""Authority gate. Reversible and confident → auto, cannot be undone → ask_crew, else escalate."""

from __future__ import annotations

from schema import SUBSYSTEMS, Alert, Authority

# Switching to a backup wheel (or similar) can be undone.
REVERSIBLE_SUBSYSTEMS = frozenset({"attitude_control", "communications", "data_handling"})
# Isolating a cabin, firing a valve, dumping coolant cannot be undone from the chair.
IRREVERSIBLE_SUBSYSTEMS = frozenset({"life_support", "propulsion", "thermal_control"})
AUTO_CONFIDENCE = 0.90

RECOMMENDED_ACTION = {
    "attitude_control": "Switch to the backup reaction wheel.",
    "power_eps": "Shed non-critical loads and stay on the healthy bus.",
    "thermal_control": "Do not vent or isolate loops without a crew go.",
    "communications": "Repoint the backup antenna.",
    "data_handling": "Warm-reset the affected processor.",
    "propulsion": "Leave valves as they are until the ground concurs.",
    "mechanisms": "Hold deployment. Recycle only if the crew confirms.",
    "life_support": "Do not seal or vent. Confirm cabin leak with the crew first.",
}


def cannot_be_undone(alert: Alert) -> bool:
    return alert.subsystem in IRREVERSIBLE_SUBSYSTEMS


def is_reversible(alert: Alert) -> bool:
    return alert.subsystem in REVERSIBLE_SUBSYSTEMS


def gate(alert: Alert) -> Authority:
    if cannot_be_undone(alert):
        return Authority.ASK_CREW
    if is_reversible(alert) and alert.confidence >= AUTO_CONFIDENCE:
        return Authority.AUTO
    return Authority.ESCALATE


def recommended_action(alert: Alert) -> str:
    return RECOMMENDED_ACTION.get(alert.subsystem, "Hold. Report to the ground.")


def subsystem_label(alert: Alert) -> str:
    info = SUBSYSTEMS.get(alert.subsystem, {})
    return str(info.get("label", alert.subsystem))
