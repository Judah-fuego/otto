"""Automatic alarm line for one forecaster.

Smooth the absolute forecast error. Fit the threshold on the last 20% of the
train errors, in time order, then freeze that line and apply it to test.
NASA spans are drawn on the chart and used only to score the frozen line.

A flagged run counts as a hit when it overlaps a label. Precision, recall,
and F0.5 are sequence scores: no point-adjust. AUPRC uses the smoothed error
at each test point, so it does not depend on the chosen z.

A-1's labeled event is a single sample, so runs of length 1 are kept.

    python -m ml.threshold --channel A-1 --seed 0
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import average_precision_score

from ml.data import WINDOW, anomaly_spans, load_series, windows
from ml.train import FIGURES, RUNS, load_forecaster, predict, score_errors

ALPHA = 0.4
VAL_FRACTION = 0.2


def ewma(values: np.ndarray, alpha: float = ALPHA) -> np.ndarray:
    """Exponential moving average. Higher alpha keeps a one-step spike visible."""
    smoothed = np.empty(len(values), dtype=np.float64)
    smoothed[0] = float(values[0])
    remain = 1.0 - alpha
    for index in range(1, len(values)):
        smoothed[index] = alpha * float(values[index]) + remain * smoothed[index - 1]
    return smoothed


def group_runs(index: np.ndarray, flagged: np.ndarray, min_length: int = 1) -> list[tuple[int, int]]:
    """Inclusive [start, end] index pairs for consecutive flagged samples."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for position, is_flagged in enumerate(flagged):
        if is_flagged and start is None:
            start = position
        elif not is_flagged and start is not None:
            if position - start >= min_length:
                spans.append((int(index[start]), int(index[position - 1])))
            start = None
    if start is not None and len(flagged) - start >= min_length:
        spans.append((int(index[start]), int(index[-1])))
    return spans


def find_threshold(errors: np.ndarray, z_min: float = 2.5, z_max: float = 12.0, z_step: float = 0.5) -> tuple[float, float]:
    """Return (threshold, z) for errors already smoothed.

    Candidate lines are mean + z * std. The winner is the line where removing
    the points above it shrinks the mean and spread the most, per flagged point.
    """
    mean = float(np.mean(errors))
    std = float(np.std(errors))
    if std == 0.0 or mean <= 0.0:
        return mean, 0.0

    best_score = -np.inf
    best_threshold = mean + z_min * std
    best_z = z_min
    for z in np.arange(z_min, z_max + 1e-9, z_step):
        threshold = mean + float(z) * std
        below = errors[errors < threshold]
        above_count = int(np.sum(errors >= threshold))
        if above_count == 0 or len(below) < 2:
            continue
        sequences = group_runs(np.arange(len(errors)), errors >= threshold)
        drop_mean = (mean - float(np.mean(below))) / mean
        drop_std = (std - float(np.std(below))) / std
        score = (drop_mean + drop_std) / (above_count + len(sequences) ** 2)
        if score > best_score:
            best_score = score
            best_threshold = float(threshold)
            best_z = float(z)
    return best_threshold, best_z


def overlaps(start: int, end: int, other_start: int, other_end: int) -> bool:
    return start <= other_end and other_start <= end


def overlapping(found: list[tuple[int, int]], labels: list[tuple[int, int]]) -> list[tuple[int, int]]:
    hits = []
    for start, end in found:
        if any(overlaps(start, end, label_start, label_end) for label_start, label_end in labels):
            hits.append((start, end))
    return hits


def sequence_scores(found: list[tuple[int, int]], labels: list[tuple[int, int]]) -> dict[str, float]:
    """Telemanom sequence precision, recall, and F0.5.

    A flagged run is a true positive when it overlaps a label, and a false
    positive otherwise. A label is a false negative when no flagged run
    overlaps it. Point scores are left alone.
    """
    if found:
        hit_runs = sum(1 for start, end in found if any(overlaps(start, end, a, b) for a, b in labels))
        precision = hit_runs / len(found)
    else:
        precision = 0.0
    if labels:
        hit_labels = sum(1 for a, b in labels if any(overlaps(start, end, a, b) for start, end in found))
        recall = hit_labels / len(labels)
    else:
        recall = 0.0
    beta2 = 0.25
    denom = beta2 * precision + recall
    f05 = (1.0 + beta2) * precision * recall / denom if denom else 0.0
    return {"precision": precision, "recall": recall, "f0.5": f05}


def smoothed_auprc(index: np.ndarray, smoothed: np.ndarray, labels: list[tuple[int, int]]) -> float:
    """Average precision of the smoothed error against point membership in a span."""
    truth = np.zeros(len(index), dtype=np.int8)
    for start, end in labels:
        truth[(index >= start) & (index <= end)] = 1
    if int(truth.sum()) == 0 or int(truth.sum()) == len(truth):
        return float("nan")
    return float(average_precision_score(truth, smoothed))


def fit_on_train_tail(channel: str, seed: int, fraction: float = VAL_FRACTION) -> tuple[float, float, int]:
    """Freeze mean + z * std from the chronological tail of the smoothed train error."""
    frames, actual, _ = windows(load_series(channel, "train"), WINDOW)
    smoothed = ewma(score_errors(load_forecaster(channel, seed), frames, actual))
    n_tail = max(1, int(len(smoothed) * fraction))
    threshold, z_value = find_threshold(smoothed[-n_tail:])
    return threshold, z_value, n_tail


def detect(
    index: np.ndarray,
    raw_error: np.ndarray,
    threshold: float,
    z_value: float,
    alpha: float = ALPHA,
) -> dict:
    raw_error = np.asarray(raw_error, dtype=np.float64)
    smoothed = ewma(raw_error, alpha)
    flagged = smoothed >= threshold
    spans = group_runs(index, flagged, min_length=1)
    return {
        "alpha": alpha,
        "threshold": threshold,
        "z": z_value,
        "spans": spans,
        "smoothed": smoothed,
        "raw_error": raw_error,
    }


def plot_threshold(
    channel: str,
    seed: int,
    index: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
    labels: list[tuple[int, int]],
    result: dict,
) -> Path:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{channel}_seed{seed}_threshold.png"
    smoothed = result["smoothed"]
    threshold = result["threshold"]
    found = result["spans"]

    start, end = labels[0]
    pad = 40
    label_zoom = (index >= start - pad) & (index <= end + pad)
    missed = found and not overlapping(found, labels)
    rows = 3 if missed else 2
    figure, axes = plt.subplots(rows, 1, figsize=(11, 3.2 * rows), constrained_layout=True, squeeze=False)
    axes = axes.ravel()

    def shade(axis) -> None:
        for label_start, label_end in labels:
            axis.axvspan(label_start, label_end, color="#f3c1b8", alpha=0.45, linewidth=0)
        for alarm_start, alarm_end in found:
            axis.axvspan(alarm_start - 0.5, alarm_end + 0.5, color="#2f6fed", alpha=0.35, linewidth=0)

    shade(axes[0])
    axes[0].plot(index[label_zoom], actual[label_zoom], color="#1f2933", linewidth=1.2, label="actual")
    axes[0].plot(index[label_zoom], predicted[label_zoom], color="#2f6fed", linewidth=1.2, label="predicted")
    axes[0].set_xlim(int(index[label_zoom][0]), int(index[label_zoom][-1]))
    axes[0].set_title(f"{channel} seed {seed}: forecast inside NASA span [{start}, {end}]")
    axes[0].set_ylabel("value")
    axes[0].legend(loc="lower right")

    shade(axes[1])
    axes[1].plot(index[label_zoom], smoothed[label_zoom], color="#b42318", linewidth=1.2, label="smoothed score")
    axes[1].axhline(threshold, color="#0f6b4c", linestyle="--", linewidth=1.2, label=f"threshold {threshold:.3f}")
    axes[1].set_xlim(int(index[label_zoom][0]), int(index[label_zoom][-1]))
    axes[1].set_ylabel("smoothed score")
    axes[1].set_title("Pink is NASA's label. The green line was frozen on the train tail.")
    axes[1].legend(loc="upper right")

    if missed:
        alarm_start, alarm_end = found[0]
        alarm_zoom = (index >= alarm_start - pad) & (index <= alarm_end + pad)
        shade(axes[2])
        axes[2].plot(index[alarm_zoom], smoothed[alarm_zoom], color="#b42318", linewidth=1.2, label="smoothed score")
        axes[2].axhline(threshold, color="#0f6b4c", linestyle="--", linewidth=1.2, label=f"threshold {threshold:.3f}")
        axes[2].set_xlim(int(index[alarm_zoom][0]), int(index[alarm_zoom][-1]))
        axes[2].set_title(f"Where the alarm actually rang: [{alarm_start}, {alarm_end}]")
        axes[2].set_ylabel("smoothed score")
        axes[2].legend(loc="upper right")
    axes[-1].set_xlabel("test index")

    figure.savefig(path, dpi=140)
    plt.close(figure)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="A-1")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    threshold, z_value, n_tail = fit_on_train_tail(args.channel, args.seed)
    frames, actual, index = windows(load_series(args.channel, "test"), WINDOW)
    model = load_forecaster(args.channel, args.seed)
    predicted = predict(model, frames)
    labels = anomaly_spans(args.channel)
    result = detect(index, score_errors(model, frames, actual), threshold, z_value)
    hits = overlapping(result["spans"], labels)
    scores = sequence_scores(result["spans"], labels)
    auprc = smoothed_auprc(index, result["smoothed"], labels)

    record = {
        "channel": args.channel,
        "seed": args.seed,
        "alpha": result["alpha"],
        "threshold": result["threshold"],
        "z": result["z"],
        "threshold_fit": "train_validation_tail",
        "val_fraction": VAL_FRACTION,
        "val_points": n_tail,
        "precision": scores["precision"],
        "recall": scores["recall"],
        "f0.5": scores["f0.5"],
        "auprc": auprc,
        "spans": result["spans"],
        "label_hits": hits,
    }
    out = RUNS / args.channel / f"seed{args.seed}_threshold.json"
    out.write_text(json.dumps(record, indent=2) + "\n")
    figure = plot_threshold(args.channel, args.seed, index, actual, predicted, labels, result)

    print(
        f"threshold {result['threshold']:.4f}  z {result['z']:.1f}  "
        f"fit train tail n={n_tail}"
    )
    print(
        f"precision {scores['precision']:.4f}  recall {scores['recall']:.4f}  "
        f"f0.5 {scores['f0.5']:.4f}  auprc {auprc:.4f}"
    )
    print(f"flagged {result['spans']}  hits {hits}")
    print(f"saved {out}")
    print(f"figure {figure}")
    if not hits:
        raise SystemExit("Alarm line does not overlap the NASA span.")


if __name__ == "__main__":
    main()
