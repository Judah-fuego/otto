"""otto's chat. Run with `streamlit run app/ui.py`.

SafeMode alerts land in the chat as cards. The gate in app/gate.py decides who acts;
ask_crew cards wait for the crew's buttons.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from app import chat
from app.tools import alert_source, current_alerts, diagnose, safemode_status, score_figure

# Alerts already in the queue when the page opens. Only the newest few are pushed into the chat.
BACKLOG = 2
POLL_S = 2

AUTHORITY_LABEL = {
    "auto": ("Auto", "green", "SafeMode acted. The action is reversible."),
    "ask_crew": ("Crew decision", "orange", "This cannot be undone. The crew decides."),
    "escalate": ("Escalated", "blue", "Sent to ground control."),
}

st.set_page_config(page_title="otto", layout="wide")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def _init() -> None:
    if "messages" in st.session_state:
        return
    st.session_state.messages = []
    st.session_state.decisions = {}
    st.session_state.log = []
    alerts = current_alerts()
    st.session_state.seen = {a.alert_id for a in alerts[:-BACKLOG]}


def _log(text: str) -> None:
    st.session_state.log.append(f"{_now()}  {text}")


def _push_alert(alert) -> None:
    d = diagnose(alert.alert_id)
    try:
        narration = chat.narrate_alert(d)
    except Exception as exc:
        narration = f"{d['subsystem']} anomaly on {d['channel']}. {d['authority_reason']} (Grok unavailable: {exc})"
    st.session_state.messages.append(
        {"role": "assistant", "kind": "alert", "alert": alert, "diagnosis": d, "content": narration}
    )
    if d["authority"] == "auto":
        st.session_state.decisions[alert.alert_id] = "executed"
        _log(f"AUTO {alert.alert_id}: {d['proposed_action']}")
    elif d["authority"] == "escalate":
        st.session_state.decisions[alert.alert_id] = "escalated"
        _log(f"GROUND {alert.alert_id}: {d['proposed_action']}")


def _check_alerts() -> bool:
    new = [a for a in current_alerts() if a.alert_id not in st.session_state.seen]
    for alert in new:
        st.session_state.seen.add(alert.alert_id)
        _push_alert(alert)
    return bool(new)


def _decide(alert_id: str, action: str, approved: bool) -> None:
    st.session_state.decisions[alert_id] = "approved" if approved else "rejected"
    verb = "approved" if approved else "rejected"
    _log(f"CREW {verb} {alert_id}: {action}")
    st.session_state.messages.append(
        {"role": "assistant", "content": f"Crew {verb}: {action}." + ("" if approved else " No action taken.")}
    )


def _history() -> list[dict[str, str]]:
    """What Grok sees. Alert cards become one line each, with the gate and the crew's call."""
    out = []
    for m in st.session_state.messages:
        if m.get("kind") == "alert":
            d = m["diagnosis"]
            outcome = st.session_state.decisions.get(d["alert_id"], "awaiting crew")
            out.append(
                {
                    "role": "assistant",
                    "content": f"[SafeMode alert {d['alert_id']}: {d['subsystem']} on {d['channel']}, "
                    f"confidence {d['confidence']}, authority {d['authority']}, "
                    f"action '{d['proposed_action']}', status {outcome}]",
                }
            )
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def _render_alert(m: dict, index: int) -> None:
    d, alert = m["diagnosis"], m["alert"]
    label, color, blurb = AUTHORITY_LABEL[d["authority"]]
    with st.chat_message("assistant", avatar=":material/warning:"):
        st.markdown(f"**SafeMode alert: {d['subsystem']}, channel {d['channel']}**  \n`{d['alert_id']}` at {d['time']}")
        st.markdown(f":{color}-badge[{label}] {blurb}")
        left, right = st.columns([3, 2])
        with left:
            st.line_chart(list(alert.values), height=180)
        with right:
            st.metric("Confidence", f"{d['confidence']:.0%}")
            t = d["telemetry"]
            st.metric("Shift", t["direction"], f"{t['shift_in_sigma']:+.1f} σ", delta_color="off")
        st.write(m["content"])
        st.markdown(f"**Proposed action:** {d['proposed_action']}")

        status = st.session_state.decisions.get(d["alert_id"])
        if d["authority"] == "ask_crew" and status is None:
            a, b, _ = st.columns([1, 1, 4])
            a.button("Approve", key=f"ok-{index}", type="primary",
                     on_click=_decide, args=(d["alert_id"], d["proposed_action"], True))
            b.button("Reject", key=f"no-{index}", on_click=_decide, args=(d["alert_id"], d["proposed_action"], False))
        elif status:
            st.caption(f"Status: {status}")

        figure = score_figure(d["channel"])
        if figure:
            with st.expander("Anomaly score chart"):
                st.image(figure)


def _render_messages() -> None:
    for i, m in enumerate(st.session_state.messages):
        if m.get("kind") == "alert":
            _render_alert(m, i)
            continue
        with st.chat_message(m["role"]):
            st.write(m["content"])
            for call in m.get("calls", []):
                with st.expander(f"Tool: {call['name']}"):
                    st.json({"arguments": call["arguments"], "result": call["result"]})


@st.fragment(run_every=POLL_S)
def _status_panel() -> None:
    if _check_alerts():
        st.rerun()
    s = safemode_status()
    st.subheader("SafeMode")
    st.markdown(":green-badge[Running]" if s.get("running") else ":gray-badge[Idle]")
    if s.get("progress") is not None:
        st.progress(s["progress"], text=f"Replay {s['progress']:.0%}")
    st.caption(f"Alerts from {s['alert_source']}. {s.get('alerts_emitted', 0)} emitted. {s.get('note', '')}")
    st.subheader("Action log")
    for line in reversed(st.session_state.log[-10:]):
        st.caption(line)


_init()

with st.sidebar:
    _status_panel()

st.title("otto")
st.caption("Crew copilot. Ask about the voyage or the spacecraft. SafeMode reports anomalies here.")

_render_messages()

if prompt := st.chat_input("Ask otto"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Thinking"):
            try:
                text, calls = chat.reply(_history())
            except Exception as exc:
                text, calls = f"Grok call failed: {exc}", []
    st.session_state.messages.append({"role": "assistant", "content": text, "calls": calls})
    st.rerun()
