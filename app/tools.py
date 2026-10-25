"""The three chat tools: voyage_calculate, safemode_status, diagnose(alert_id)."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

import numpy as np

from app import mission, simulate
from app.gate import decide
from safemode.monitor import safemode_status as _monitor_status
from schema import (
    ALERT_QUEUE,
    DESTINATIONS,
    MOCK_ALERTS,
    ORIGINS,
    ROOT,
    SUBSYSTEMS,
    Alert,
    load_alerts,
    parse_voyage_request,
)
from voyage import voyage_calculate as _voyage_calculate

FIGURES = ROOT / "ml" / "figures"
DECISIONS = ALERT_QUEUE.parent / "decisions.json"
# What the server records the first time it sees an alert, before anyone acts.
FIRST_STATUS = {"auto": "executed", "ask_crew": "awaiting_crew", "escalate": "escalated"}


def alert_source() -> str:
    """`OTTO_ALERTS=mock` pins the scripted demo. Otherwise the live queue, once it has anything."""
    if os.getenv("OTTO_ALERTS", "").lower() == "mock":
        return "mock"
    return "queue" if load_alerts(ALERT_QUEUE) else "mock"


def current_alerts() -> list[Alert]:
    return load_alerts(ALERT_QUEUE if alert_source() == "queue" else MOCK_ALERTS) + simulate.load()


def find_alert(alert_id: str) -> Alert:
    for alert in current_alerts():
        if alert.alert_id == alert_id:
            return alert
    raise KeyError(f"No alert {alert_id!r}")


def score_figure(channel: str) -> str | None:
    for name in (f"{channel}_seed0_telemanom_telemanom.png", f"{channel}_seed0.png"):
        if (FIGURES / name).exists():
            return str(FIGURES / name)
    return None


def diagnose(alert_id: str) -> dict[str, Any]:
    alert = find_alert(alert_id)
    values = np.asarray(alert.values)
    split = max(1, int(len(values) * 0.75))
    baseline, recent = values[:split], values[split:]
    spread = float(baseline.std()) or 1e-6
    shift = float(recent.mean() - baseline.mean())
    decision = decide(alert)
    subsystem = SUBSYSTEMS[alert.subsystem]
    return {
        "alert_id": alert.alert_id,
        "time": alert.time,
        "channel": alert.channel,
        "subsystem": subsystem["label"],
        "likely_causes": subsystem["examples"],
        "confidence": alert.confidence,
        "telemetry": {
            "baseline_mean": round(float(baseline.mean()), 4),
            "recent_mean": round(float(recent.mean()), 4),
            "shift_in_sigma": round(shift / spread, 2),
            "direction": "rising" if shift > 0 else "falling",
            "last_value": round(float(values[-1]), 4),
            "samples": len(values),
        },
        "proposed_action": decision.action.description,
        "reversible": decision.action.reversible,
        "authority": decision.authority.value,
        "authority_reason": decision.reason,
    }


def safemode_status() -> dict[str, Any]:
    status = _monitor_status()
    alerts = current_alerts()
    status["alert_source"] = alert_source()
    status["recent_alerts"] = [
        {"alert_id": a.alert_id, "channel": a.channel, "subsystem": a.subsystem, "confidence": a.confidence}
        for a in alerts[-5:]
    ]
    return status


def alert_outcomes() -> dict[str, str]:
    """Crew and gate outcomes per alert, as app/server.py records them."""
    if not DECISIONS.exists():
        return {}
    return {k: v["status"] for k, v in json.loads(DECISIONS.read_text()).get("decisions", {}).items()}


def mission_status() -> dict[str, Any]:
    outcomes = alert_outcomes()
    systems = []
    for alert in current_alerts():
        decision = decide(alert)
        systems.append(
            {
                "subsystem": SUBSYSTEMS[alert.subsystem]["label"],
                "action": decision.action.description,
                "authority": decision.authority.value,
                "status": outcomes.get(alert.alert_id, FIRST_STATUS[decision.authority.value]),
            }
        )
    awaiting_crew = [s for s in systems if s["status"] == "awaiting_crew"]
    with_ground = [s for s in systems if s["status"] == "escalated"]
    # Rejecting the fix leaves the fault in place, so it stays open.
    crew_declined = [s for s in systems if s["status"] == "rejected"]
    supplies = mission.consumables()
    short = [name for name, c in supplies.items() if c["margin_days_after_arrival"] < 0]
    if awaiting_crew or short:
        overall = "action_needed"
    elif with_ground or crew_declined:
        overall = "watch"
    else:
        overall = "nominal"
    return {
        "overall": overall,
        "trajectory": mission.trajectory(),
        "consumables": supplies,
        "systems": {
            "awaiting_crew": awaiting_crew,
            "with_ground": with_ground,
            "crew_declined": crew_declined,
            "handled": [s for s in systems if s["status"] in ("executed", "approved")],
        },
        "safemode_running": bool(_monitor_status().get("running")),
    }


def voyage_calculate(**raw: Any) -> dict[str, Any]:
    return _voyage_calculate(parse_voyage_request(raw)).to_dict()


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "voyage_calculate": voyage_calculate,
    "safemode_status": safemode_status,
    "diagnose": diagnose,
    "mission_status": mission_status,
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "voyage_calculate",
            "description": "Plan a crewed trip. Hohmann delta-v, coast time, propellant from the rocket equation, "
            "the next launch window, and oxygen, water, and food for the crew. Leaves a 300 km Earth "
            "parking orbit for the Moon or any planet from Mercury to Pluto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "enum": list(ORIGINS)},
                    "destination": {"type": "string", "enum": list(DESTINATIONS)},
                    "spacecraft_mass_kg": {"type": "number", "description": "Dry mass, no propellant"},
                    "isp_s": {"type": "number", "description": "Engine specific impulse in seconds"},
                    "crew": {"type": "integer", "minimum": 1},
                },
                "required": ["origin", "destination", "spacecraft_mass_kg", "isp_s", "crew"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "safemode_status",
            "description": "Whether the SafeMode telemetry monitor is running, its progress, and the latest alerts.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diagnose",
            "description": "Diagnose one SafeMode alert: telemetry shift, likely causes, the proposed action, "
            "and who has authority to act (auto, ask_crew, escalate).",
            "parameters": {
                "type": "object",
                "properties": {"alert_id": {"type": "string"}},
                "required": ["alert_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mission_status",
            "description": "The crew's own mission right now: overall state, mission day and progress to arrival, "
            "distance and light delay to Earth, oxygen, water, and food left, and which SafeMode alerts are "
            "waiting on the crew, with ground, declined by the crew (fault still present), or handled.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def call_tool(name: str, arguments: str | dict[str, Any]) -> str:
    args = json.loads(arguments or "{}") if isinstance(arguments, str) else arguments
    try:
        return json.dumps(TOOLS[name](**args))
    except Exception as exc:  # the model should see the error and recover
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


# Grok Voice (app/voice.py, app/static/index.html) uses the flat realtime tool shape and dict results.
DEFAULT_MASS_KG = 10000.0
DEFAULT_ISP_S = 300.0
DEFAULT_CREW = 4

CHAT_TOOLS = TOOL_SPECS
VOICE_TOOLS: list[dict[str, Any]] = [{"type": "function", **spec["function"]} for spec in TOOL_SPECS]
for _spec in VOICE_TOOLS:
    if _spec["name"] == "voyage_calculate":
        _spec["parameters"] = {**_spec["parameters"], "required": ["destination"]}
        _spec["description"] += (
            f" If the crew omits numbers, use spacecraft_mass_kg={DEFAULT_MASS_KG:.0f}, "
            f"isp_s={DEFAULT_ISP_S:.0f}, crew={DEFAULT_CREW}."
        )


def tool_voyage_calculate(arguments: dict[str, Any]) -> dict[str, Any]:
    destination = str(arguments.get("destination") or "mars").strip().lower()
    origin = str(arguments.get("origin") or ("leo" if destination == "moon" else "earth")).strip().lower()
    payload = voyage_calculate(
        origin=origin,
        destination=destination,
        spacecraft_mass_kg=float(arguments.get("spacecraft_mass_kg") or DEFAULT_MASS_KG),
        isp_s=float(arguments.get("isp_s") or DEFAULT_ISP_S),
        crew=int(arguments.get("crew") or DEFAULT_CREW),
    )
    payload["delta_v_km_s"] = payload["delta_v_m_s"] / 1000.0
    return payload


def tool_safemode_status(_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    status = safemode_status()
    alerts = current_alerts()
    live = alert_source() == "queue"
    status.update(
        {
            "live": live,
            "source": str(ALERT_QUEUE if live else MOCK_ALERTS),
            "alert_count": len(alerts),
            "alert_ids": [a.alert_id for a in alerts],
        }
    )
    return status


def tool_diagnose(arguments: dict[str, Any]) -> dict[str, Any]:
    alert_id = str(arguments["alert_id"])
    try:
        result = diagnose(alert_id)
    except KeyError:
        return {"error": f"No alert {alert_id!r}", "known": sorted(a.alert_id for a in current_alerts())}
    result["cannot_be_undone"] = not result["reversible"]
    return result


HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "voyage_calculate": tool_voyage_calculate,
    "safemode_status": tool_safemode_status,
    "diagnose": tool_diagnose,
    "mission_status": lambda _arguments: mission_status(),
}


def dispatch_tool(name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments else {}
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool {name!r}"}
    try:
        return handler(arguments or {})
    except Exception as exc:  # the model should see the error and recover
        return {"error": f"{type(exc).__name__}: {exc}"}
