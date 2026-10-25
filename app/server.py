"""HTTP API for the web UI. Run with `uvicorn app.server:app --port 8000`.

The browser polls GET /api/state. The gate in app/gate.py decides who acts; the only thing
the browser can do is answer an ask_crew alert, and the server checks that it is one.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app import chat, mission, simulate
from app.alerts import alert_source
from app.tools import DECISIONS, current_alerts, diagnose, dispatch_tool, safemode_status, score_figure
from app.voice import api_key, mint_ephemeral_token
from schema import Alert

STATE_FILE = DECISIONS
STATIC = Path(__file__).resolve().parent / "static"
VOICE_HOST = "127.0.0.1"
VOICE_PORT = 8765
NARRATE_LATEST = 6

app = FastAPI(title="otto")
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"decisions": {}, "narrations": {}, "log": []}


def _save(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, STATE_FILE)


_state = _load()


def _log(kind: str, alert_id: str, text: str) -> None:
    _state["log"].append({"time": _now(), "kind": kind, "alert_id": alert_id, "text": text})


def _settle(alert: Alert) -> dict[str, Any]:
    """Diagnose an alert and, the first time it is seen, carry out what the gate allows."""
    d = diagnose(alert.alert_id)
    decisions = _state["decisions"]
    if alert.alert_id not in decisions:
        if d["authority"] == "auto":
            decisions[alert.alert_id] = {"status": "executed", "time": _now()}
            _log("auto", alert.alert_id, d["proposed_action"])
        elif d["authority"] == "escalate":
            decisions[alert.alert_id] = {"status": "escalated", "time": _now()}
            _log("ground", alert.alert_id, d["proposed_action"])
        else:
            decisions[alert.alert_id] = {"status": "awaiting_crew", "time": _now()}
            _log("crew", alert.alert_id, f"Awaiting crew: {d['proposed_action']}")
        _save(_state)
    return d


def _view(alert: Alert) -> dict[str, Any]:
    d = _settle(alert)
    return {
        **d,
        "values": list(alert.values),
        "decision": _state["decisions"][alert.alert_id],
        "narration": _state["narrations"].get(alert.alert_id),
        "has_figure": score_figure(alert.channel) is not None,
    }


def _narrator() -> None:
    """Grok explains the newest alerts in the background so the page never waits on it."""
    while True:
        try:
            for alert in reversed(current_alerts()[-NARRATE_LATEST:]):
                if alert.alert_id in _state["narrations"]:
                    continue
                with _lock:
                    d = _settle(alert)
                text = chat.narrate_alert(d)
                with _lock:
                    _state["narrations"][alert.alert_id] = text
                    _save(_state)
        except Exception as exc:
            print(f"narrator: {exc}")
        time.sleep(1.0)


threading.Thread(target=_narrator, daemon=True).start()


@app.get("/api/state")
def state() -> dict[str, Any]:
    with _lock:
        alerts = [_view(a) for a in current_alerts()]
        log = _state["log"][-300:]
    trajectory = mission.trajectory()
    return {
        "now": _now(),
        "safemode": safemode_status(),
        "alerts": alerts,
        "log": log,
        "mission": trajectory,
        "ground_light_delay_s": round(trajectory["one_way_light_delay_min"] * 60),
    }


class Decision(BaseModel):
    approved: bool


@app.post("/api/alerts/{alert_id}/decision")
def decide(alert_id: str, body: Decision) -> dict[str, Any]:
    with _lock:
        try:
            alert = next(a for a in current_alerts() if a.alert_id == alert_id)
        except StopIteration:
            raise HTTPException(404, f"No alert {alert_id}")
        d = _settle(alert)
        current = _state["decisions"][alert_id]
        if d["authority"] != "ask_crew":
            raise HTTPException(409, f"{alert_id} is {d['authority']}, not a crew decision")
        if current["status"] != "awaiting_crew":
            raise HTTPException(409, f"{alert_id} was already {current['status']}")
        status = "approved" if body.approved else "rejected"
        _state["decisions"][alert_id] = {"status": status, "time": _now()}
        _log("crew", alert_id, f"Crew {status}: {d['proposed_action']}")
        _save(_state)
        return _view(alert)


@app.post("/api/alerts/{alert_id}/reopen")
def reopen(alert_id: str) -> dict[str, Any]:
    """Put a rejected alert back in front of the crew. Approvals stay final: the action ran."""
    with _lock:
        try:
            alert = next(a for a in current_alerts() if a.alert_id == alert_id)
        except StopIteration:
            raise HTTPException(404, f"No alert {alert_id}")
        d = _settle(alert)
        current = _state["decisions"][alert_id]
        if current["status"] != "rejected":
            raise HTTPException(409, f"{alert_id} is {current['status']}, only rejected alerts can be reopened")
        _state["decisions"][alert_id] = {"status": "awaiting_crew", "time": _now()}
        _log("crew", alert_id, f"Crew reopened: {d['proposed_action']}")
        _save(_state)
        return _view(alert)


@app.post("/api/reset")
def reset() -> dict[str, str]:
    """Forget decisions, the log, and simulated alerts so the demo can run again. Narrations are kept."""
    with _lock:
        _state["decisions"] = {}
        _state["log"] = []
        _save(_state)
        simulate.clear()
    return {"status": "reset"}


@app.get("/api/simulate")
def scenarios() -> list[dict[str, Any]]:
    return [
        {"scenario": name, "channel": channel, "confidence": confidence}
        for name, (channel, confidence, _) in simulate.SCENARIOS.items()
    ]


@app.post("/api/simulate/{scenario}")
def simulate_alert(scenario: str) -> dict[str, Any]:
    if scenario not in simulate.SCENARIOS:
        raise HTTPException(404, f"No scenario {scenario}. Use {', '.join(simulate.SCENARIOS)}")
    with _lock:
        return _view(simulate.inject(scenario))


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatTurn]


def _alert_context() -> str:
    lines = []
    for a in current_alerts()[-8:]:
        d = _settle(a)
        status = _state["decisions"][a.alert_id]["status"]
        lines.append(
            f"- {a.alert_id}: {d['subsystem']} on {a.channel}, confidence {a.confidence}, "
            f"authority {d['authority']}, action '{d['proposed_action']}', status {status}"
        )
    return "Current SafeMode alerts, oldest first:\n" + ("\n".join(lines) or "none")


@app.post("/api/chat")
def chat_reply(body: ChatRequest) -> dict[str, Any]:
    with _lock:
        context = _alert_context()
    history = [{"role": "system", "content": context}, *(m.model_dump() for m in body.messages)]
    try:
        text, spoken, calls = chat.reply_with_speech(history)
    except Exception as exc:
        raise HTTPException(502, f"Grok call failed: {exc}")
    return {"text": text, "spoken": spoken, "calls": calls}


class SpeechRequest(BaseModel):
    text: str
    speed: float = 1.0


@app.post("/api/tts")
def tts(body: SpeechRequest) -> Response:
    try:
        audio = chat.speech(body.text, min(max(body.speed, 0.7), 1.5))
    except Exception as exc:
        raise HTTPException(502, f"TTS call failed: {exc}")
    return Response(audio, media_type="audio/mpeg")


@app.get("/api/figures/{channel}")
def figure(channel: str) -> FileResponse:
    path = score_figure(channel)
    if not path:
        raise HTTPException(404, f"No score chart for {channel}")
    return FileResponse(Path(path))


# Grok Voice headset page (app/static/index.html) and the routes it calls.
@app.get("/", response_class=FileResponse)
def voice_page() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/alerts")
def voice_alerts() -> dict[str, Any]:
    alerts, source, live = alert_source()
    return {"live": live, "source": source, "alerts": [a.to_dict() for a in alerts]}


@app.post("/session")
def voice_session() -> dict[str, Any]:
    try:
        return mint_ephemeral_token()
    except Exception as exc:
        raise HTTPException(500, str(exc))


class ToolCall(BaseModel):
    name: str = ""
    arguments: dict[str, Any] | str | None = None


@app.post("/tool")
def voice_tool(body: ToolCall) -> dict[str, Any]:
    return dispatch_tool(body.name, body.arguments)


def serve(host: str = VOICE_HOST, port: int = VOICE_PORT) -> None:
    import uvicorn

    try:
        api_key()
    except RuntimeError as exc:
        print(f"Warning: {exc}")
    print(f"Otto voice copilot: http://{host}:{port}")
    print("Say: I want to go to Mars.")
    uvicorn.run(app, host=host, port=port)
