"""HTTP API for the web UI. Run with `uvicorn app.server:app --port 8000`.

The browser polls GET /api/state. The gate in app/gate.py decides who acts; the only thing
the browser can do is answer an ask_crew alert, and the server checks that it is one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app import chat, flight, mission, simulate
from app.tools import DECISIONS, current_alerts, diagnose, dispatch_tool, safemode_status, score_figure
from app.voice import api_key, mint_ephemeral_token
from schema import ROOT, Alert

STATE_FILE = DECISIONS
API_HOST = "127.0.0.1"
API_PORT = 8000
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
    prior = decisions.get(alert.alert_id)
    # Reset marks the backlog "cleared" so it does not dump on the next poll. A later replay
    # writes the same id with a new timestamp; that is a new detection and has to warn again.
    if prior and prior.get("status") == "cleared" and alert.time > prior.get("time", ""):
        decisions.pop(alert.alert_id, None)
        _state["narrations"].pop(alert.alert_id, None)
        prior = None
    if prior is None:
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


MONITOR_PID = ROOT / "queue" / "monitor.pid"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _ensure_monitor() -> None:
    """Start the SafeMode replay if it is not already heartbeating.

    The console only warns about alerts this process writes. The last run had already
    finished, so nothing new was arriving. Replay from just before the first detection,
    fast enough that a warning lands every couple of seconds.
    """
    try:
        if MONITOR_PID.exists():
            try:
                if _pid_alive(int(MONITOR_PID.read_text().strip())):
                    print("SafeMode: monitor already running")
                    return
            except ValueError:
                pass
        if safemode_status().get("running"):
            print("SafeMode: monitor already running")
            return
        print("SafeMode: starting telemetry replay")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "safemode.monitor",
                "--fresh",
                "--speed",
                "35",
                "--tick",
                "0.4",
                "--start",
                "4400",
            ],
            cwd=str(ROOT),
            start_new_session=True,
        )
        MONITOR_PID.write_text(str(proc.pid))
    except Exception as exc:
        print(f"SafeMode: failed to start ({exc})")


threading.Thread(target=_ensure_monitor, daemon=True).start()


def _awaiting() -> set[str]:
    return {k for k, v in _state["decisions"].items() if v["status"] == "awaiting_crew"}


@app.get("/api/state")
def state() -> dict[str, Any]:
    with _lock:
        fired = flight.advance(_awaiting())
        if fired:
            _settle(fired)
        flight_view = flight.view(_awaiting())
        lost = (flight_view or {}).get("failed")
        if lost and _state["decisions"].get(lost["alert_id"], {}).get("status") == "awaiting_crew":
            _state["decisions"][lost["alert_id"]] = {"status": "timed_out", "time": _now()}
            _log("crew", lost["alert_id"], f"No crew decision in {flight.DECISION_LIMIT_S:.0f} s. {lost['text']}")
            _save(_state)
        alerts = [v for v in map(_view, current_alerts()) if v["decision"]["status"] != "cleared"]
        log = _state["log"][-300:]
    trajectory = mission.trajectory(flight.mission_now())
    return {
        "now": _now(),
        "safemode": safemode_status(),
        "alerts": alerts,
        "log": log,
        "mission": trajectory,
        "flight": flight_view,
        "missions": mission.catalog(),
        "ground_light_delay_s": round(trajectory["one_way_light_delay_s"]),
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


def _clean_ship() -> None:
    """Wipe decisions, the log, and simulated alerts. Alerts already in the queue are marked
    cleared rather than forgotten, or the next poll would settle them all over again."""
    simulate.clear()
    _state["decisions"] = {a.alert_id: {"status": "cleared", "time": _now()} for a in current_alerts()}
    _state["log"] = []
    _save(_state)


@app.post("/api/reset")
def reset() -> dict[str, str]:
    """Start the demo over from a quiet ship. Narrations are kept."""
    with _lock:
        flight.stop()
        _clean_ship()
    return {"status": "reset"}


class MissionSelect(BaseModel):
    id: str


@app.post("/api/mission")
def select_mission(body: MissionSelect) -> dict[str, Any]:
    """Point the map, the supplies, and the next launch at one catalog mission."""
    with _lock:
        if flight.active():
            raise HTTPException(409, "Abort the flight before changing missions")
        try:
            mission.activate(body.id.strip())
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return mission.trajectory(None)


class FlightStart(BaseModel):
    speed: float = 1.0


@app.post("/api/flight/start")
def flight_start(body: FlightStart) -> dict[str, Any] | None:
    """Fly the mission from launch. Starts from a clean ship: decisions, log, and simulated alerts go."""
    with _lock:
        flight.stop()
        _clean_ship()
        flight.start(body.speed)
        return flight.view(set())


class FlightControl(BaseModel):
    action: str
    speed: float | None = None


@app.post("/api/flight/control")
def flight_control(body: FlightControl) -> dict[str, Any] | None:
    with _lock:
        try:
            flight.control(body.action, body.speed)
        except LookupError as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return flight.view(_awaiting())


@app.post("/api/flight/stop")
def flight_stop() -> dict[str, str]:
    with _lock:
        flight.stop()
    return {"status": "stopped"}


@app.get("/api/simulate")
def scenarios() -> list[dict[str, Any]]:
    return [
        {"scenario": name, "channel": s.channel, "confidence": s.confidence}
        for name, s in simulate.SCENARIOS.items()
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
        if status == "cleared":
            continue
        line = (
            f"- {a.alert_id}: {d['subsystem']} on {a.channel}, confidence {a.confidence}, "
            f"authority {d['authority']}, action '{d['proposed_action']}', status {status}"
        )
        if status in ("awaiting_crew", "rejected", "timed_out"):
            line += f". If not done: {d['if_not_done']}"
        lines.append(line)
    context = "Current SafeMode alerts, oldest first:\n" + ("\n".join(lines) or "none")
    t = mission.trajectory(flight.mission_now())
    origin = "low Earth orbit" if t["origin"] == "leo" else t["origin"]
    context += (
        f"\n\nSelected mission: {t['mission']}, {origin} to {t['destination']}, "
        f"landing site {t['site']}, {t['crew']} crew, dry mass {t['spacecraft_mass_kg']:.0f} kilograms, "
        f"specific impulse {t['isp_s']:.0f} seconds, phase {t['phase']}."
    )
    f = flight.view(_awaiting())
    if f:
        context += (
            f"\n\nThe crew is flying the mission: day {f['elapsed_days']:.0f} of {f['transit_days']:.0f}, "
            f"{f['remaining_events']} more faults expected before arrival."
        )
        if f["decision_left_s"] is not None:
            context += f" The ship is holding for a crew decision with {f['decision_left_s']:.0f} s left before it is lost."
        if f["failed"]:
            context += f" The mission was lost: {f['failed']['text']}"
    return context


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


@app.post("/api/stt")
async def stt(request: Request) -> dict[str, str]:
    """Push-to-talk: the browser posts its recording as the raw body, Grok writes it down."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "No audio in the request body")
    try:
        text = await run_in_threadpool(chat.transcribe, audio, request.headers.get("content-type", "audio/webm"))
    except Exception as exc:
        raise HTTPException(502, f"Speech to text failed: {exc}")
    return {"text": text}


@app.get("/api/figures/{channel}")
def figure(channel: str) -> FileResponse:
    path = score_figure(channel)
    if not path:
        raise HTTPException(404, f"No score chart for {channel}")
    return FileResponse(Path(path))


class ToolCall(BaseModel):
    name: str = ""
    arguments: dict[str, Any] | str | None = None


@app.post("/api/voice/session")
def voice_session() -> dict[str, Any]:
    """Ephemeral token for a live Grok Voice call. The browser talks to xAI directly; the key stays here."""
    with _lock:
        context = _alert_context()
    try:
        return mint_ephemeral_token(context=context)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/voice/tool")
def voice_tool(body: ToolCall) -> dict[str, Any]:
    return dispatch_tool(body.name, body.arguments)


def serve(host: str = API_HOST, port: int = API_PORT) -> None:
    import uvicorn

    try:
        api_key()
    except RuntimeError as exc:
        print(f"Warning: {exc}")
    print(f"Otto API: http://{host}:{port}")
    print("Crew console: bash dev.sh, then http://127.0.0.1:3000")
    uvicorn.run(app, host=host, port=port)
