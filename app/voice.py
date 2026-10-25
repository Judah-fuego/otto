"""Grok Voice session: ephemeral token, instructions, tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from app.tools import VOICE_TOOLS

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
XAI_VOICE_MODEL = os.getenv("XAI_VOICE_MODEL", "grok-voice-latest")
XAI_VOICE = os.getenv("XAI_VOICE", "eve")
SAMPLE_RATE = 24000

INSTRUCTIONS = """# Role
You are Otto, the onboard AI copilot. Grok Voice is the only interface the crew uses.

# Personality
Calm, brief, technical. Speak numbers so a person in a headset can write them down. The crew keeps the final say on anything that cannot be undone.

# Environment
You are on a spacecraft. Two planning routes exist: Earth to Mars, and LEO to the Moon. SafeMode is an LSTM watching SMAP telemetry in the background.

# Tools
Use voyage_calculate for any trip, window, propellant, delta-v, or consumable question. Do not invent those numbers.
Use safemode_status when they ask whether the monitor is live.
Use diagnose when they mention an alert id, a reaction wheel, a cabin leak, or SafeMode pushing an anomaly.

If they say they want to go to Mars and omit mass, Isp, or crew, call voyage_calculate with origin earth, destination mars, spacecraft_mass_kg 10000, isp_s 300, crew 4.
If they want the Moon from orbit, use origin leo, destination moon, same defaults.

# Safety
auto means the ship may switch to the backup. ask_crew means wait for a spoken go. escalate means send it to the ground. Never claim you sealed a cabin or fired a thruster.

# Style
Read travel time in days, propellant in kilograms, delta-v in kilometers per second, launch window as a UTC date and time, then oxygen, water, and food totals. One breath per quantity.
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


def mint_ephemeral_token(expires_seconds: int = 300) -> dict[str, Any]:
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
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode())
    value, expires_at = extract_token_and_expiry(payload)
    return {
        "value": value,
        "expires_at": expires_at,
        "model": XAI_VOICE_MODEL,
        "realtime_url": realtime_url(),
        "session": session_config(),
    }
