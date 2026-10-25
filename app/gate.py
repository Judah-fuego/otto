"""The authority gate. Code decides who acts, never the model.

Reversible and confident → auto. Cannot be undone → ask_crew. Otherwise → escalate.
"""

from __future__ import annotations

from dataclasses import dataclass

from schema import SUBSYSTEMS, Alert, Authority

AUTO_CONFIDENCE = 0.85


@dataclass(frozen=True)
class Action:
    description: str
    reversible: bool


# The response SafeMode proposes for each Table 8 subsystem.
ACTIONS: dict[str, Action] = {
    "attitude_control": Action("Switch attitude control to the backup reaction wheel", True),
    "power_eps": Action("Shed non-critical loads and move to the redundant power bus", True),
    "thermal_control": Action("Switch to the redundant cooling loop", True),
    "communications": Action("Fail over to the backup transponder", True),
    "data_handling": Action("Reboot the flight computer onto the backup image", True),
    "propulsion": Action("Fire the pyro valve to isolate the affected thruster branch", False),
    "mechanisms": Action("Fire the pyro release to force the deployment", False),
    "life_support": Action("Seal the leaking module and vent it to vacuum", False),
}


@dataclass(frozen=True)
class Decision:
    authority: Authority
    action: Action
    reason: str


def decide(alert: Alert) -> Decision:
    action = ACTIONS[alert.subsystem]
    if not action.reversible:
        return Decision(Authority.ASK_CREW, action, "The action cannot be undone, so the crew has the final say.")
    if alert.confidence >= AUTO_CONFIDENCE:
        return Decision(
            Authority.AUTO,
            action,
            f"The action is reversible and confidence {alert.confidence:.2f} clears {AUTO_CONFIDENCE:.2f}.",
        )
    return Decision(
        Authority.ESCALATE,
        action,
        f"The action is reversible but confidence {alert.confidence:.2f} is below {AUTO_CONFIDENCE:.2f}, so ground decides.",
    )


# The names app/voice.py, app/__main__.py, and tests/test_person_b.py use. Same policy as decide().
REVERSIBLE_SUBSYSTEMS = frozenset(name for name, action in ACTIONS.items() if action.reversible)
IRREVERSIBLE_SUBSYSTEMS = frozenset(name for name, action in ACTIONS.items() if not action.reversible)


def gate(alert: Alert) -> Authority:
    return decide(alert).authority


def recommended_action(alert: Alert) -> str:
    return ACTIONS[alert.subsystem].description


def subsystem_label(alert: Alert) -> str:
    return str(SUBSYSTEMS.get(alert.subsystem, {}).get("label", alert.subsystem))
