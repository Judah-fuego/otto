"""Chat/voice tools: voyage_calculate, safemode_status, diagnose."""

from __future__ import annotations

import json
from typing import Any

from schema import ROUTES

from app.alerts import alert_source, alerts_by_id
from app.gate import IRREVERSIBLE_SUBSYSTEMS, gate, recommended_action, subsystem_label
from voyage import voyage_calculate

DEFAULT_MASS_KG = 10000.0
DEFAULT_ISP_S = 300.0
DEFAULT_CREW = 4

VOICE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "voyage_calculate",
        "description": (
            "Hohmann voyage calculator. Call this whenever the crew wants to go to Mars or "
            "the Moon, or asks about travel time, propellant, delta-v, launch window, oxygen, "
            "water, or food. Supported routes: earth→mars (~259 days) and leo→moon (~5 days). "
            "If they omit numbers, use spacecraft_mass_kg=10000, isp_s=300, crew=4."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "enum": ["earth", "leo"],
                    "description": "earth for Mars, leo for the Moon",
                },
                "destination": {
                    "type": "string",
                    "enum": ["mars", "moon"],
                },
                "spacecraft_mass_kg": {
                    "type": "number",
                    "description": "Dry mass, no propellant. Default 10000.",
                },
                "isp_s": {
                    "type": "number",
                    "description": "Specific impulse in seconds. Default 300.",
                },
                "crew": {
                    "type": "integer",
                    "description": "Number of people. Default 4.",
                },
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "type": "function",
        "name": "safemode_status",
        "description": "Background LSTM monitor: live queue or mock alerts, and current alert ids.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "diagnose",
        "description": (
            "Look up a SafeMode alert by id, name the subsystem, and apply the authority gate "
            "(auto / ask_crew / escalate). Demo ids: rw-backup, cabin-leak."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "alert_id": {"type": "string", "description": "Alert id from SafeMode"},
            },
            "required": ["alert_id"],
        },
    },
]

CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": item["name"],
            "description": item["description"],
            "parameters": item["parameters"],
        },
    }
    for item in VOICE_TOOLS
]


def _infer_route(origin: str | None, destination: str | None) -> tuple[str, str]:
    dest = (destination or "mars").strip().lower()
    if dest in {"moon", "luna", "lunar"}:
        dest = "moon"
    elif dest in {"mars", "martian"}:
        dest = "mars"
    origin = (origin or ("leo" if dest == "moon" else "earth")).strip().lower()
    if origin in {"earth", "geo", "ground"}:
        origin = "earth" if dest == "mars" else origin
    if origin in {"leo", "orbit", "low earth orbit"}:
        origin = "leo"
    if (origin, dest) not in ROUTES:
        if dest == "mars":
            origin = "earth"
        elif dest == "moon":
            origin = "leo"
    return origin, dest


def tool_voyage_calculate(arguments: dict[str, Any]) -> dict[str, Any]:
    origin, destination = _infer_route(arguments.get("origin"), arguments.get("destination"))
    result = voyage_calculate(
        {
            "origin": origin,
            "destination": destination,
            "spacecraft_mass_kg": float(arguments.get("spacecraft_mass_kg") or DEFAULT_MASS_KG),
            "isp_s": float(arguments.get("isp_s") or DEFAULT_ISP_S),
            "crew": int(arguments.get("crew") or DEFAULT_CREW),
        }
    )
    payload = result.to_dict()
    payload["delta_v_km_s"] = result.delta_v_m_s / 1000.0
    return payload


def tool_safemode_status(_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    alerts, path, live = alert_source()
    return {
        "live": live,
        "source": path,
        "alert_count": len(alerts),
        "alert_ids": [alert.alert_id for alert in alerts],
        "note": "Live queue" if live else "Person A has not written queue/alerts.json yet. Using mock_alerts.json.",
    }


def tool_diagnose(arguments: dict[str, Any]) -> dict[str, Any]:
    alert_id = str(arguments["alert_id"])
    found = alerts_by_id()
    alert = found.get(alert_id)
    if alert is None:
        return {"error": f"No alert {alert_id!r}", "known": sorted(found)}
    authority = gate(alert)
    return {
        "alert_id": alert.alert_id,
        "time": alert.time,
        "channel": alert.channel,
        "subsystem": alert.subsystem,
        "subsystem_label": subsystem_label(alert),
        "confidence": alert.confidence,
        "latest_value": alert.values[-1],
        "authority": authority.value,
        "recommended_action": recommended_action(alert),
        "cannot_be_undone": alert.subsystem in IRREVERSIBLE_SUBSYSTEMS,
    }


HANDLERS = {
    "voyage_calculate": tool_voyage_calculate,
    "safemode_status": tool_safemode_status,
    "diagnose": tool_diagnose,
}


def dispatch_tool(name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments else {}
    arguments = arguments or {}
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool {name!r}"}
    try:
        return handler(arguments)
    except Exception as exc:  # noqa: BLE001 — return the error to Grok instead of dropping the call
        return {"error": str(exc)}
