"""Replay SMAP test telemetry as if it were live and push anomalies into the alert queue.

    python -m safemode.monitor                      # latest ml/results run
    python -m safemode.monitor --run 2026-10-25_15.27.33
    python -m safemode.monitor --source labels      # NASA labels, until a Telemanom run exists
    python -m safemode.monitor --fresh --speed 100 --start 2000

Every tick the replay cursor moves `speed` samples. When it crosses the end of a
detected window, an Alert lands in schema.ALERT_QUEUE. queue/status.json backs safemode_status.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from safemode import detections as det
from schema import (
    ALERT_QUEUE,
    DEFAULT_CHANNELS,
    ROOT,
    Alert,
    load_alerts,
    subsystem_for_channel,
)

TEST = ROOT / "data" / "smap" / "test"
STATUS = ALERT_QUEUE.parent / "status.json"

# Minimum lead-in samples sent with each alert, oldest first. The last one is the end of the window.
ALERT_WINDOW = 60


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload) -> None:
    """Write then rename, so the chat never reads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, path)


def load_telemetry(channels: list[str]) -> dict[str, np.ndarray]:
    return {ch: np.load(TEST / f"{ch}.npy")[:, 0] for ch in channels}


def make_alert(d: det.Detection, series: np.ndarray, cursor: int) -> Alert:
    """History before the window, then the window. diagnose() reads the first 75% as baseline,
    so the lead-in is three times the window, and at least ALERT_WINDOW samples."""
    last = min(cursor, d.end, len(series) - 1)
    lead = max(ALERT_WINDOW, 3 * (last - d.start + 1))
    values = series[max(0, d.start - lead) : last + 1]
    return Alert(
        alert_id=f"{d.channel}-{d.start}",
        time=_now(),
        channel=d.channel,
        subsystem=subsystem_for_channel(d.channel),
        confidence=d.confidence,
        values=tuple(round(float(v), 4) for v in values),
    )


def run(source: str, run_id: str | None, channels: list[str], speed: int, tick: float, start: int, fresh: bool) -> None:
    if source == "labels":
        run_id, found = det.from_labels(channels)
    else:
        run_id, found = det.from_telemanom(run_id)
    found = [d for d in found if d.channel in channels]

    telemetry = load_telemetry(channels)
    length = max(len(s) for s in telemetry.values())
    # Telemanom pads each window by error_buffer on both sides, so its start comes before the
    # anomaly. Fire at the end, once the detector has seen it, so `values` holds the excursion.
    pending = sorted((d for d in found if d.end >= start), key=lambda d: d.end)

    queue = [] if fresh else load_alerts(ALERT_QUEUE)
    seen = {a.alert_id for a in queue}
    _write_json(ALERT_QUEUE, [a.to_dict() for a in queue])

    print(f"SafeMode: {source} {run_id}, {len(channels)} channels, {len(pending)} detections ahead, {speed} samples/tick")

    def status(running: bool, cursor: int, note: str = "") -> None:
        _write_json(
            STATUS,
            {
                "running": running,
                "updated": _now(),
                "tick_s": tick,
                "source": source,
                "run_id": run_id,
                "channels": channels,
                "cursor": cursor,
                "length": length,
                "alerts_emitted": len(queue),
                "last_alert_id": queue[-1].alert_id if queue else None,
                "next_detection": asdict(pending[0]) if pending else None,
                "note": note,
            },
        )

    cursor = start
    try:
        while cursor < length:
            cursor = min(cursor + speed, length)
            while pending and pending[0].end <= cursor:
                d = pending.pop(0)
                alert = make_alert(d, telemetry[d.channel], cursor)
                if alert.alert_id in seen:
                    continue
                seen.add(alert.alert_id)
                queue.append(alert)
                _write_json(ALERT_QUEUE, [a.to_dict() for a in queue])
                print(f"[{alert.time}] ALERT {alert.alert_id} {alert.subsystem} confidence {alert.confidence}")
            status(True, cursor)
            time.sleep(tick)
        status(False, cursor, "replay finished")
        print("SafeMode: replay finished")
    except KeyboardInterrupt:
        status(False, cursor, "stopped by operator")
        print("\nSafeMode: stopped")


def safemode_status() -> dict:
    """What the chat's safemode_status tool returns."""
    if not STATUS.exists():
        return {"running": False, "note": "SafeMode has not been started"}
    status = json.loads(STATUS.read_text())
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(status["updated"].replace("Z", "+00:00"))).total_seconds()
    if status["running"] and age > 5 * status["tick_s"] + 2:
        status["running"] = False
        status["note"] = f"no heartbeat for {age:.0f}s, monitor likely crashed"
    status["progress"] = round(status["cursor"] / status["length"], 3) if status.get("length") else None
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("telemanom", "labels"), default="telemanom")
    parser.add_argument("--run", help="ml/results run id, default latest")
    parser.add_argument("--channels", nargs="*", default=list(DEFAULT_CHANNELS))
    parser.add_argument("--speed", type=int, default=50, help="samples per tick")
    parser.add_argument("--tick", type=float, default=1.0, help="seconds per tick")
    parser.add_argument("--start", type=int, default=0, help="sample index to start the replay at")
    parser.add_argument("--fresh", action="store_true", help="clear queue/alerts.json first")
    args = parser.parse_args()
    for ch in args.channels:
        subsystem_for_channel(ch)
    run(args.source, args.run, args.channels, args.speed, args.tick, args.start, args.fresh)


if __name__ == "__main__":
    main()
