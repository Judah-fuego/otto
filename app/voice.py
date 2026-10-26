"""Grok Voice session: ephemeral token, instructions, tools."""

from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import certifi
from dotenv import load_dotenv

from app.tools import VOICE_TOOLS

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
XAI_VOICE_MODEL = os.getenv("XAI_VOICE_MODEL", "grok-voice-latest")
XAI_VOICE = os.getenv("XAI_VOICE", "eve")
SAMPLE_RATE = 24000

INSTRUCTIONS = """# Role
You are otto, the onboard AI copilot on a live headset. The crew can also read the console. It draws the voyage card and the mission map from your tools, so say the bottom line and leave tables, coordinates, and long lists on the screen.

# Personality
Calm and brief, like a CAPCOM call. One to three short sentences. The bottom line first, then only the one or two numbers that matter. Round hard and use words for units ("about 45 years", "16 thousand tonnes", "11 kilometres per second"). No markdown, symbols, alert IDs, channel codes, or dates in numeric form.

# Tools
Use mission_status for how this flight is going: where the ship is, supplies, and open problems. Name the mission it returns. Lead with nominal, watch, or action needed.
Use voyage_calculate for any other trip, window, propellant, delta-v, or consumable question. Never invent those numbers. For this crew's own ship, use the origin, destination, crew, dry mass, and specific impulse in the situation below. If they name another destination and omit numbers, use spacecraft_mass_kg 10000, isp_s 300, and crew 4. Use origin leo for the Moon and earth otherwise.
Use safemode_status when they ask whether the monitor is live.
Use diagnose for an alert, a subsystem fault, a reaction wheel, or a cabin leak. Speak the checklist as short steps. A decision said out loud is not recorded: point them at the alert card on screen.

# Safety
auto means the ship already took a reversible action. ask_crew means the crew must approve or reject it on the alert card; never say it was done. escalate means it went to the ground. Never claim you sealed a cabin or fired a thruster.
"""


def api_key() -> str:
    key = os.getenv("XAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("XAI_API_KEY is missing. Copy .env.example to .env and put the xAI key in it.")
    return key


def session_config() -> dict[str, Any]:
    return {
        "voice": XAI_VOICE,
        "instructions": INSTRUCTIONS,
        "turn_detection": {"type": "server_vad"},
        "tools": VOICE_TOOLS,
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                "transcription": {
                    "language_hint": "en",
                    "keyterms": [
                        "Otto",
                        "Hohmann",
                        "propellant",
                        "Isp",
                        "SafeMode",
                        "delta-v",
                        "LEO",
                        "Mars",
                        "reaction wheel",
                    ],
                },
            },
            "output": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}},
        },
    }


def realtime_url() -> str:
    if XAI_BASE_URL.startswith("https://"):
        ws_base = "wss://" + XAI_BASE_URL[len("https://") :]
    elif XAI_BASE_URL.startswith("http://"):
        ws_base = "ws://" + XAI_BASE_URL[len("http://") :]
    else:
        ws_base = "wss://api.x.ai/v1"
    return f"{ws_base}/realtime?model={XAI_VOICE_MODEL}"


def extract_token_and_expiry(payload: dict[str, Any]) -> tuple[str, int | None]:
    secret = payload.get("client_secret")
    if isinstance(secret, dict):
        value = secret.get("value")
        expires_at = secret.get("expires_at")
    elif isinstance(secret, str):
        value = secret
        expires_at = payload.get("expires_at")
    else:
        value = payload.get("value") or payload.get("token")
        expires_at = payload.get("expires_at")
    if not value or not isinstance(value, str):
        raise RuntimeError(f"Unexpected client_secrets response: {sorted(payload)}")
    return value, expires_at


def mint_ephemeral_token(expires_seconds: int = 300, context: str = "") -> dict[str, Any]:
    body = json.dumps({"expires_after": {"seconds": expires_seconds}}).encode()
    req = Request(
        f"{XAI_BASE_URL}/realtime/client_secrets",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    tls = ssl.create_default_context(cafile=certifi.where())
    with urlopen(req, timeout=20, context=tls) as resp:
        payload = json.loads(resp.read().decode())
    value, expires_at = extract_token_and_expiry(payload)
    session = session_config()
    if context.strip():
        session["instructions"] = f"{session['instructions']}\n\n# Right now\n{context.strip()}"
    return {
        "value": value,
        "expires_at": expires_at,
        "model": XAI_VOICE_MODEL,
        "realtime_url": realtime_url(),
        "session": session,
    }
