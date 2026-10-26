"""The authority gate. Code decides who acts, never the model.

Reversible and confident → auto. Cannot be undone → ask_crew. Otherwise → escalate.
"""

from __future__ import annotations

from dataclasses import dataclass

from schema import SUBSYSTEMS, Alert, Authority, subsystem_for_channel

AUTO_CONFIDENCE = 0.85


@dataclass(frozen=True)
class Action:
    description: str
    reversible: bool
    # The crew procedure the console runs before the irreversible step. Only crew actions have one.
    procedure: str | None = None
    # What the fault does if the crew rejects the fix or runs out of time.
    if_not_done: str = "The fault stays in place."
    # Overrides the subsystem's Table 8 examples when one sensor has a more specific story.
    causes: str | None = None
    # The steps the crew works through, for the chat to walk them through it.
    checklist: tuple[str, ...] = ()


# The response SafeMode proposes for each Table 8 subsystem.
ACTIONS: dict[str, Action] = {
    "attitude_control": Action("Switch attitude control to the backup reaction wheel", True),
    "power_eps": Action("Shed non-critical loads and move to the redundant power bus", True),
    "thermal_control": Action("Switch to the redundant cooling loop", True),
    "communications": Action("Fail over to the backup transponder", True),
    "data_handling": Action("Reboot the flight computer onto the backup image", True),
    "propulsion": Action(
        "Fire the pyro valve to isolate the affected thruster branch", False, "thruster_isolation",
        "Branch B kept leaking propellant. Not enough left for Mars orbit insertion.",
        checklist=("Find the leaking feed branch", "Repressurize the healthy branch", "Re-point the engines", "Fire the pyro valve"),
    ),
    "mechanisms": Action(
        "Fire the pyro release to force the deployment", False, "antenna_deploy",
        "The boom never deployed. The ship lost its high-rate link to Earth.",
        checklist=("Warm the cold hinge", "Arm the pyro circuit", "Time the release with the ship's sway", "Fire the release"),
    ),
    "life_support": Action(
        "Seal the leaking module and vent it to vacuum", False, "cabin_leak",
        "The leak was never sealed. Cabin pressure fell below the safe limit.",
        checklist=("Find the module losing pressure", "Work out the time to the suit-up limit", "Close the hatches in order", "Vent the module"),
    ),
}

# Sensors with their own fault and fix. Anything not listed falls back to its subsystem's action.
CHANNEL_ACTIONS: dict[str, Action] = {
    "F-3": Action(
        "Jettison the saturated CO2 scrubber bed and bring the spare online", False, "co2_scrubber",
        "CO2 kept building. The crew hit the toxic limit before the cabin cleared.",
        "saturated scrubber bed, failed bed heater, blocked airflow",
        ("Find the saturated bed", "Reroute airflow around it", "Check the spare lasts to the next resupply", "Jettison the bed"),
    ),
    "P-3": Action(
        "Isolate battery 3 and jettison it before thermal runaway spreads", False, "battery_runaway",
        "Battery 3 went into thermal runaway and took the power bay with it.",
        "internal cell short, failed charge regulator, cell overcharge",
        ("Find the overheating cell", "Open the battery breakers in order", "Time the jettison", "Jettison battery 3"),
    ),
    "T-2": Action(
        "Cut power to the avionics bay and flood it with CO2 suppressant", False, "avionics_fire",
        "The avionics fire spread. The crew lost the primary flight computers.",
        "overheated power converter, chafed wiring, failed cooling fan",
        ("Find the rack that is smoking", "Make the bay safe: masks, fans, power, hatch", "Flood the bay to the suppression band", "Discharge the suppressant"),
    ),
    "G-2": Action(
        "Fire the RCS thrusters from the landing reserve to stop the tumble", False, "detumble",
        "The tumble got worse. The solar arrays lost the Sun and the batteries ran flat.",
        "stuck-open RCS thruster, reaction wheel saturation, gyro failure",
        ("Null the spin with RCS pulses", "Check the landing reserve after the burn", "Re-lock the star tracker", "Commit the burn"),
    ),
    "R-2": Action(
        "Send the crew to the storm shelter and wipe the corrupted memory bank", False, "solar_flare",
        "The crew took a radiation dose over the career limit.",
        "solar particle event, coronal mass ejection, single-event upsets",
        ("Read the dose forecast", "Call the crew into the shelter", "Find the corrupted memory bank", "Wipe the bank"),
    ),
}


def action_for(channel: str, subsystem: str | None = None) -> Action:
    return CHANNEL_ACTIONS.get(channel) or ACTIONS[subsystem or subsystem_for_channel(channel)]


@dataclass(frozen=True)
class Decision:
    authority: Authority
    action: Action
    reason: str


def decide(alert: Alert) -> Decision:
    action = action_for(alert.channel, alert.subsystem)
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
    return action_for(alert.channel, alert.subsystem).description


def subsystem_label(alert: Alert) -> str:
    return str(SUBSYSTEMS.get(alert.subsystem, {}).get("label", alert.subsystem))
