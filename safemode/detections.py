"""Where SafeMode learns which telemetry windows are anomalous.

`telemanom` reads ml/results/<run_id>.csv from `python -m ml.ensemble` (or `python -m ml.telemanom --channels ...`).
`labels` reads NASA's labeled_anomalies.csv. Use it only to exercise the
pipeline before a Telemanom run finishes, since it is the answer key.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from schema import ROOT

ML = ROOT / "ml"
RESULTS = ML / "results"
LABELS = ROOT / "data" / "smap" / "labeled_anomalies.csv"

# Telemanom's anom_scores index y_test, which starts l_s samples into the channel. Matches ml.telemanom.Config.l_s.
L_S = 250

LABEL_CONFIDENCE = 0.9


@dataclass(frozen=True)
class Detection:
    channel: str
    start: int
    end: int
    confidence: float


def score_to_confidence(score: float) -> float:
    """Telemanom scores are distance past the threshold in units of mean+std, unbounded above."""
    return round(1.0 - math.exp(-max(score, 0.0)), 3)


def _literal(cell):
    if not isinstance(cell, str):
        return cell
    return ast.literal_eval(re.sub(r"np\.\w+\(([^()]*)\)", r"\1", cell))


def latest_run_id() -> str | None:
    runs = sorted(RESULTS.glob("*.csv"))
    return runs[-1].stem if runs else None


def from_telemanom(run_id: str | None = None) -> tuple[str, list[Detection]]:
    run_id = run_id or latest_run_id()
    if run_id is None:
        raise FileNotFoundError(f"No Telemanom results in {RESULTS}. Run `python -m ml.telemanom --channels default` first")
    df = pd.read_csv(RESULTS / f"{run_id}.csv")

    detections = []
    for row in df.to_dict("records"):
        # ml.ensemble writes seed-agreement confidence per window directly.
        if isinstance(row.get("confidences"), str):
            for start, end, confidence in _literal(row["confidences"]):
                detections.append(Detection(row["chan_id"], int(start), int(end), float(confidence)))
            continue
        # With labels, anomaly_sequences holds NASA's labels and the predictions are split into tp/fp.
        if "tp_sequences" in row:
            sequences = list(_literal(row["tp_sequences"])) + list(_literal(row["fp_sequences"]))
        else:
            sequences = list(_literal(row["anomaly_sequences"]))
        scores = _literal(row.get("anom_scores", "[]")) or []

        for start, end in sorted((int(s), int(e)) for s, e in sequences):
            inside = [s["score"] for s in scores if start <= s["start_idx"] + L_S <= end]
            confidence = score_to_confidence(max(inside)) if inside else 0.5
            detections.append(Detection(row["chan_id"], start, end, confidence))
    return run_id, detections


def from_labels(channels: list[str]) -> tuple[str, list[Detection]]:
    df = pd.read_csv(LABELS)
    df = df[df.chan_id.isin(channels)]
    detections = [
        Detection(row["chan_id"], int(start), int(end), LABEL_CONFIDENCE)
        for row in df.to_dict("records")
        for start, end in _literal(row["anomaly_sequences"])
    ]
    return "nasa-labels", detections
