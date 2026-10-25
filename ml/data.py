"""Windowed SMAP channels for one-step forecasting.

Each .npy row is 25 columns: column 0 is the telemetry value, and the rest are
command flags. A sample at time t uses the previous `WINDOW` rows to predict
column 0 at t. NASA spans in labeled_anomalies.csv are inclusive.
"""

from __future__ import annotations

import ast
import csv
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "smap"
WINDOW = 50
N_FEATURES = 25


def load_series(channel: str, split: str) -> np.ndarray:
    path = DATA / split / f"{channel}.npy"
    series = np.load(path)
    if series.ndim != 2 or series.shape[1] != N_FEATURES:
        raise ValueError(f"{path} has shape {series.shape}, expected (*, {N_FEATURES})")
    return np.ascontiguousarray(series, dtype=np.float32)


def windows(series: np.ndarray, window: int = WINDOW) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return X (N, window, 25), y (N,), and the target index of each row."""
    if len(series) <= window:
        raise ValueError(f"series length {len(series)} is shorter than the window {window}")
    view = np.lib.stride_tricks.sliding_window_view(series, window, axis=0)
    frames = np.ascontiguousarray(np.moveaxis(view[:-1], 2, 1))
    targets = series[window:, 0].copy()
    indices = np.arange(window, len(series))
    return frames, targets, indices


def sequence_targets(series: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """Next telemetry value at every step of each window. Shape (N, window).

    Row i lines up with windows(series)[0][i]. Position t predicts series[i + t + 1, 0],
    and the last column is the one-step target windows() already returns.
    """
    values = np.ascontiguousarray(series[:, 0])
    view = np.lib.stride_tricks.sliding_window_view(values, window)
    return np.ascontiguousarray(view[1 : len(series) - window + 1])


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
