"""SMAP channels and their NASA labels.

Each .npy row is 25 columns: column 0 is the telemetry value, and the rest are
command flags. NASA spans in labeled_anomalies.csv are inclusive.
"""

from __future__ import annotations

import ast
import csv
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "smap"
N_FEATURES = 25


def load_series(channel: str, split: str) -> np.ndarray:
    path = DATA / split / f"{channel}.npy"
    series = np.load(path)
    if series.ndim != 2 or series.shape[1] != N_FEATURES:
        raise ValueError(f"{path} has shape {series.shape}, expected (*, {N_FEATURES})")
    return np.ascontiguousarray(series, dtype=np.float32)


def anomaly_spans(channel: str, spacecraft: str = "SMAP") -> list[tuple[int, int]]:
    """Inclusive [start, end] index pairs for one channel."""
    spans: list[tuple[int, int]] = []
    with (DATA / "labeled_anomalies.csv").open() as handle:
        for row in csv.DictReader(handle):
            if row["chan_id"] != channel or row["spacecraft"] != spacecraft:
                continue
            for start, end in ast.literal_eval(row["anomaly_sequences"]):
                spans.append((int(start), int(end)))
    if not spans:
        raise ValueError(f"No {spacecraft} labels for channel {channel}")
    return spans
