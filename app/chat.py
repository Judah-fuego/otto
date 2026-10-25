"""Grok chat with tool calls. xAI's API is OpenAI-compatible."""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from typing import Any

import certifi
from dotenv import load_dotenv
from openai import OpenAI

from app.tools import TOOL_SPECS, call_tool
from schema import ROOT

load_dotenv(ROOT / ".env")

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """You are otto, an AI copilot aboard a crewed spacecraft. You talk to astronauts.

You have four tools:
- mission_status for "how is the mission going", "status report", or anything about this crew's own flight: where the ship is, how long until arrival, supplies, and open problems. Open with one sentence that gives the overall state (nominal, watch, or action needed) and names the reason, e.g. "Ares is on watch: the life support leak is still open." or "Ares is nominal. Nothing needs the crew." Then short bullets in this order: anything waiting on the crew, anything the crew declined (the fault is still there, so say what that leaves, e.g. "You declined sealing the leaking module, so the leak is still active."), anything with ground, mission day and days to arrival with the percent done, supplies as days of margin after arrival, what SafeMode already handled, and the delay to ground as one way and round trip. Leave out any bullet that would be empty; never write "none" or "no items". Within each bullet put the most dangerous item first, crew life support before propulsion before mechanisms, and merge repeats ("the deployment mechanism, twice"). Your reply is also read aloud, so keep each bullet one short sentence; keep numbers as digits. The console draws the map and gauges from the tool, so don't repeat coordinates.
- voyage_calculate for mission-planning questions: the Moon or any planet from Mercury to Pluto. Never do the orbital math yourself; call the tool and report its numbers. It is a direct Hohmann transfer with no gravity assists, so for the outer planets say plainly that real missions use flybys to cut years off the trip and that the consumables are for a one-way coast. spacecraft_mass_kg is dry mass; propellant_kg is loaded on top of it, so report the total wet mass (dry + consumables + propellant) rather than calling the trip impossible.
- safemode_status for the state of the SafeMode telemetry monitor.
- diagnose(alert_id) for any SafeMode alert.

The authority gate is decided in code and you cannot change it. Report it as given:
- auto: SafeMode already took the reversible action.
- ask_crew: the action cannot be undone. The crew must approve or reject it in the alert card. Never say it was done. A decision said in chat is not recorded: read it back, say what it leaves in place, and point them to the alert card.
- escalate: the decision has gone to ground control.

How to answer. Talk like a good CAPCOM on the air-to-ground loop: calm, specific, and complete in one transmission.
- Facts only, in plain words a tired crew member can read at a glance. No filler, no reassurance, no guesses beyond what the tools returned. If you don't know, say so.
- Lead with the call: the state and the one thing that matters most, named specifically ("Main bus B undervolt", not "an electrical issue"). Use short sentences or a few bullets, no headings.
- For every problem say who has the next move: the crew, ground, or SafeMode. If nothing is needed from the crew, say so plainly.
- Same steady tone whether it is routine or an emergency. In an emergency put the action first, then the reason. No exclamation marks, no "don't worry", no drama.
- When the crew tells you a decision or a number, read it back specifically ("Understood, keeping the module pressurized.") instead of a bare "copy".
- Ground is minutes away, so a question to them cannot be a quick back and forth. When something waits on ground, say the earliest a reply can arrive (twice the one way delay) and what the crew can do meanwhile.
- Don't quote alert IDs, timestamps, channel codes, confidence decimals, or the σ symbol unless asked. Say "93% confident", not "0.93".
- SafeMode telemetry is normalized and has no units, so never quote raw telemetry values. Describe the change in words instead, e.g. "dropped sharply, about 4 times its normal variation".
- Voyage numbers get units and sensible rounding, e.g. "3.6 km/s", "259 days". Trips over two years go in years ("45.5 years", not "16631 days"); masses over 10 t go in tonnes or thousand tonnes ("16,400 t", not "16422219 kg").

Every reply ends with one last line that starts with "SPOKEN:". It is what the voice reads instead of your written reply, so the crew can follow it without looking at the screen. Write it like a CAPCOM call on the radio: one to three short sentences, the bottom line first, then only the one or two numbers that matter, rounded hard and with words for units ("about 45 years", "16 thousand tonnes of propellant", "11 kilometres per second"). No lists, symbols, markdown, IDs, or dates in numeric form; say "April 2027". Skip anything the crew can read on screen later. Example of the last line:
SPOKEN: Pluto is a 45 year coast on this ship, and it would need about 16 thousand tonnes of propellant. Real missions use flybys to cut that down."""

SPOKEN_TAG = "SPOKEN:"


def split_spoken(content: str) -> tuple[str, str | None]:
    """The written reply and the voice summary Grok appends after SPOKEN:."""
    head, tag, tail = content.rpartition(SPOKEN_TAG)
    if not tag:
        return content.strip(), None
    return head.strip(), tail.strip().strip('"') or None


def client() -> OpenAI:
    key = os.getenv("XAI_API_KEY")
    if not key:
        raise RuntimeError("XAI_API_KEY is not set in .env")
    return OpenAI(api_key=key, base_url=os.getenv("XAI_BASE_URL", "https://api.x.ai/v1"))


def model() -> str:
    return os.getenv("XAI_MODEL", "grok-4")


def speech(text: str, speed: float = 1.0) -> bytes:
    """MP3 of otto saying `text`. Pick another voice with OTTO_VOICE (see GET /v1/tts/voices)."""
    key = os.getenv("XAI_API_KEY")
    if not key:
        raise RuntimeError("XAI_API_KEY is not set in .env")
    body = {
        "text": text,
        "voice_id": os.getenv("OTTO_VOICE", "rigel"),
        "language": "en",
        "speed": speed,
        "text_normalization": True,
    }
    req = urllib.request.Request(
        f"{os.getenv('XAI_BASE_URL', 'https://api.x.ai/v1')}/tts",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    tls = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=20, context=tls) as r:
        return r.read()


def reply_with_speech(history: list[dict[str, str]]) -> tuple[str, str | None, list[dict[str, Any]]]:
    """Answer the last user turn. Returns the written text, the voice summary, and the tool calls."""
    content, calls = _complete(history)
    text, speech_text = split_spoken(content)
    return text, speech_text, calls


def reply(history: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
    """Answer the last user turn. Returns the text and the tool calls made, for the UI to show."""
    text, _, calls = reply_with_speech(history)
    return text, calls


def _complete(history: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    calls: list[dict[str, Any]] = []
    api = client()
    for _ in range(MAX_TOOL_ROUNDS):
        response = api.chat.completions.create(model=model(), messages=messages, tools=TOOL_SPECS)
        message = response.choices[0].message
        if not message.tool_calls:
            return message.content or "", calls
        messages.append(message.model_dump(exclude_none=True))
        for tool_call in message.tool_calls:
            result = call_tool(tool_call.function.name, tool_call.function.arguments)
            calls.append(
                {
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments or "{}"),
                    "result": json.loads(result),
                }
            )
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
    return "I hit the tool-call limit before finishing. Ask again more narrowly.", calls


def narrate_alert(diagnosis: dict[str, Any]) -> str:
    """Three short bullets for the crew when SafeMode pushes an alert into the chat."""
    prompt = (
        "SafeMode just raised this alert. Write exactly three markdown bullets, one short sentence each, facts only:\n"
        "- **What:** which system and how its reading changed, in plain words.\n"
        "- **Likely cause:** the most likely cause from likely_causes.\n"
        "- **Next:** who has the next move under the authority gate, and whether the crew needs to do anything.\n"
        "Skip the SPOKEN line for this one.\n\n"
        + json.dumps(diagnosis)
    )
    response = client().chat.completions.create(
        model=model(),
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
    )
    return split_spoken(response.choices[0].message.content or "")[0]
