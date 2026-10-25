"""NASA Telemanom (Hundman et al. 2018), ported from the Keras reference to PyTorch.

Model: two stacked LSTMs (80, 80) read `l_s` = 250 rows and predict the next
`n_predictions` = 10 telemetry values. The first prediction is the forecast.

Errors: |y_hat - y| smoothed with an EWM, then thresholded per window of
`window_size` batches of `batch_size` points. Each window picks the
mean + z * std line that best shrinks the error mean and spread, checks the
inverted errors too, and prunes sequences that barely clear the next highest
error. No labels are used. NASA spans only score the result.

    python -m ml.telemanom --channel F-1 --seed 0
    python -m ml.telemanom --channel F-1 --seed 0 --forecaster residual
    python -m ml.telemanom --channels all --seed 0 --reuse
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import nn

from ml.data import DATA, N_FEATURES, WINDOW, anomaly_spans, load_series, windows
from ml.threshold import overlapping, sequence_scores, smoothed_auprc
from ml.train import FIGURES, RUNS, device, load_forecaster, predict, set_seed


@dataclass(frozen=True)
class Config:
    """Defaults from telemanom's config.yaml."""

    l_s: int = 250
    n_predictions: int = 10
    layers: tuple[int, int] = (80, 80)
    dropout: float = 0.3
    lstm_batch_size: int = 64
    epochs: int = 35
    patience: int = 10
    min_delta: float = 0.0003
    validation_split: float = 0.2
    batch_size: int = 70
    window_size: int = 30
    smoothing_perc: float = 0.05
    error_buffer: int = 100
    p: float = 0.13


class TelemanomLSTM(nn.Module):
    def __init__(
        self,
        n_features: int = N_FEATURES,
        layers: tuple[int, int] = (80, 80),
        dropout: float = 0.3,
        n_predictions: int = 10,
    ):
        super().__init__()
        self.layers = tuple(layers)
        self.dropout_rate = dropout
        self.n_predictions = n_predictions
        self.lstm1 = nn.LSTM(n_features, layers[0], batch_first=True)
        self.lstm2 = nn.LSTM(layers[0], layers[1], batch_first=True)
        self.drop = nn.Dropout(dropout)
        self.head = nn.Linear(layers[1], n_predictions)
        for lstm in (self.lstm1, self.lstm2):
            for name, param in lstm.named_parameters():
                if "bias_ih" in name:
                    size = param.shape[0] // 4
                    param.data[size : 2 * size].fill_(1.0)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        sequence, _ = self.lstm1(inputs)
        sequence, _ = self.lstm2(self.drop(sequence))
        return self.head(self.drop(sequence[:, -1]))


def shape_data(series: np.ndarray, cfg: Config) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """X (N, l_s, 25) as a view, y (N, n_predictions), and the index of y[:, 0]."""
    span = cfg.l_s + cfg.n_predictions
    count = len(series) - span
    if count <= 0:
        raise ValueError(f"series length {len(series)} is shorter than l_s + n_predictions")
    view = np.lib.stride_tricks.sliding_window_view(series, span, axis=0)[:count]
    data = np.moveaxis(view, 2, 1)
    frames = data[:, : cfg.l_s, :]
    targets = np.ascontiguousarray(data[:, cfg.l_s :, 0])
    return frames, targets, np.arange(count) + cfg.l_s


def _loss(model: TelemanomLSTM, frames: np.ndarray, targets: np.ndarray, dev: torch.device) -> float:
    model.eval()
    total = 0.0
    with torch.no_grad():
        for start in range(0, len(frames), 256):
            batch_x = torch.from_numpy(np.ascontiguousarray(frames[start : start + 256])).to(dev)
            batch_y = torch.from_numpy(targets[start : start + 256]).to(dev)
            total += float((model(batch_x) - batch_y).pow(2).sum())
    return total / targets.size


def train_telemanom(channel: str, seed: int, cfg: Config) -> TelemanomLSTM:
    """Keras fit with validation_split: shuffle once, hold out the last fraction."""
    set_seed(seed)
    dev = device()
    frames, targets, _ = shape_data(load_series(channel, "train"), cfg)
    order = np.random.permutation(len(frames))
    frames = np.ascontiguousarray(frames[order])
    targets = targets[order]
    split = int(len(frames) * (1.0 - cfg.validation_split))
    train_x, train_y = frames[:split], targets[:split]
    val_x, val_y = frames[split:], targets[split:]

    model = TelemanomLSTM(layers=cfg.layers, dropout=cfg.dropout, n_predictions=cfg.n_predictions).to(dev)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    best_val = float("inf")
    stall = 0
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        total = 0.0
        for batch in np.array_split(np.random.permutation(split), max(1, split // cfg.lstm_batch_size)):
            batch_x = torch.from_numpy(train_x[batch]).to(dev)
            batch_y = torch.from_numpy(train_y[batch]).to(dev)
            optimizer.zero_grad()
            loss = (model(batch_x) - batch_y).pow(2).mean()
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * len(batch)
        val_loss = _loss(model, val_x, val_y, dev)
        marker = ""
        if val_loss < best_val - cfg.min_delta:
            best_val = val_loss
            stall = 0
            marker = "  best"
        else:
            stall += 1
        print(f"epoch {epoch:02d}  loss {total / split:.6f}  val_loss {val_loss:.6f}{marker}", flush=True)
        if stall >= cfg.patience:
            print(f"early stop at epoch {epoch}")
            break

    # Keras EarlyStopping keeps the last weights, not the best ones
    model.eval()
    return model


def predict_first(model: TelemanomLSTM, frames: np.ndarray, batch_size: int = 256) -> np.ndarray:
    """Telemanom's "first" aggregation: the 1-step-ahead value of each forecast."""
    dev = next(model.parameters()).device
    predicted = np.empty(len(frames), dtype=np.float32)
    model.eval()
    with torch.no_grad():
        for start in range(0, len(frames), batch_size):
            batch = torch.from_numpy(np.ascontiguousarray(frames[start : start + batch_size])).to(dev)
            predicted[start : start + len(batch)] = model(batch)[:, 0].cpu().numpy()
    return predicted


def checkpoint_path(channel: str, seed: int) -> Path:
    return RUNS / channel / f"telemanom_seed{seed}.pt"


def save_telemanom(model: TelemanomLSTM, channel: str, seed: int, cfg: Config) -> Path:
    path = checkpoint_path(channel, seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"channel": channel, "seed": seed, "config": cfg.__dict__, "state_dict": model.state_dict()}, path)
    return path


def load_telemanom(channel: str, seed: int) -> tuple[TelemanomLSTM, Config]:
    blob = torch.load(checkpoint_path(channel, seed), map_location="cpu", weights_only=False)
    saved = dict(blob["config"])
    saved["layers"] = tuple(saved["layers"])
    cfg = Config(**saved)
    model = TelemanomLSTM(layers=cfg.layers, dropout=cfg.dropout, n_predictions=cfg.n_predictions)
    model.load_state_dict(blob["state_dict"])
    model.to(device())
    model.eval()
    return model, cfg


def consecutive_groups(values: np.ndarray) -> list[list[int]]:
    """more_itertools.consecutive_groups for a sorted integer array."""
    if len(values) == 0:
        return []
    values = np.asarray(values, dtype=np.int64)
    breaks = np.flatnonzero(np.diff(values) != 1) + 1
    return [group.tolist() for group in np.split(values, breaks)]


def ewm_mean(values: np.ndarray, span: int) -> np.ndarray:
    """pandas `.ewm(span=span).mean()` with adjust=True."""
    decay = 1.0 - 2.0 / (span + 1.0)
    smoothed = np.empty(len(values), dtype=np.float64)
    numerator = 0.0
    denominator = 0.0
    for position, value in enumerate(values):
        numerator = float(value) + decay * numerator
        denominator = 1.0 + decay * denominator
        smoothed[position] = numerator / denominator
    return smoothed


def _buffered(i_anom: np.ndarray, buffer: np.ndarray, length: int) -> np.ndarray:
    grown = np.concatenate((i_anom, (i_anom[:, None] + buffer).ravel(), (i_anom[:, None] - buffer).ravel()))
    return np.sort(grown[(grown < length) & (grown >= 0)])


class ErrorWindow:
    def __init__(self, e_s: np.ndarray, y_test: np.ndarray, n_total: int, cfg: Config, window_num: int):
        self.cfg = cfg
        self.window_num = window_num
        self.i_anom = np.array([], dtype=np.int64)
        self.i_anom_inv = np.array([], dtype=np.int64)
        self.E_seq: list[tuple[int, int]] = []
        self.E_seq_inv: list[tuple[int, int]] = []
        self.non_anom_max = -1000000.0
        self.non_anom_max_inv = -1000000.0
        self.anom_scores: list[dict] = []

        self.sd_lim = 12.0
        self.e_s = e_s
        self.mean_e_s = float(np.mean(e_s))
        self.sd_e_s = float(np.std(e_s))
        self.e_s_inv = self.mean_e_s + (self.mean_e_s - e_s)
        self.epsilon = self.mean_e_s + self.sd_lim * self.sd_e_s
        self.epsilon_inv = self.epsilon

        self.sd_values = float(np.std(y_test))
        perc_high, perc_low = np.percentile(y_test, [95, 5])
        self.inter_range = float(perc_high - perc_low)

        self.num_to_ignore = cfg.l_s * 2
        if n_total < 2500:
            self.num_to_ignore = cfg.l_s
        if n_total < 1800:
            self.num_to_ignore = 0

    def find_epsilon(self, inverse: bool = False) -> None:
        e_s = self.e_s_inv if inverse else self.e_s
        max_score = -10000000.0
        buffer = np.arange(1, self.cfg.error_buffer)
        for z in np.arange(2.5, self.sd_lim, 0.5):
            epsilon = self.mean_e_s + self.sd_e_s * z
            pruned_e_s = e_s[e_s < epsilon]
            i_anom = np.argwhere(e_s >= epsilon).reshape(-1)
            i_anom = np.unique(_buffered(i_anom, buffer, len(e_s)))
            if len(i_anom) == 0 or len(pruned_e_s) == 0:
                continue
            E_seq = [(g[0], g[-1]) for g in consecutive_groups(i_anom) if g[0] != g[-1]]
            mean_perc_decrease = (self.mean_e_s - np.mean(pruned_e_s)) / self.mean_e_s
            sd_perc_decrease = (self.sd_e_s - np.std(pruned_e_s)) / self.sd_e_s
            score = (mean_perc_decrease + sd_perc_decrease) / (len(E_seq) ** 2 + len(i_anom))
            if score >= max_score and len(E_seq) <= 5 and len(i_anom) < len(e_s) * 0.5:
                max_score = score
                if inverse:
                    self.epsilon_inv = self.mean_e_s + z * self.sd_e_s
                else:
                    self.epsilon = self.mean_e_s + z * self.sd_e_s

    def compare_to_epsilon(self, all_i_anom: np.ndarray, inverse: bool = False) -> None:
        e_s = self.e_s_inv if inverse else self.e_s
        epsilon = self.epsilon_inv if inverse else self.epsilon

        # errors too small relative to the signal to mean anything
        if not (self.sd_e_s > 0.05 * self.sd_values or max(self.e_s) > 0.05 * self.inter_range) or not max(self.e_s) > 0.05:
            return

        i_anom = np.argwhere((e_s >= epsilon) & (e_s > 0.05 * self.inter_range)).reshape(-1)
        if len(i_anom) == 0:
            return
        i_anom = _buffered(i_anom, np.arange(1, self.cfg.error_buffer + 1), len(e_s))

        # only the newest batch of a later window is new; the first window needs history
        if self.window_num == 0:
            i_anom = i_anom[i_anom >= self.num_to_ignore]
        else:
            i_anom = i_anom[i_anom >= len(e_s) - self.cfg.batch_size]
        i_anom = np.unique(i_anom)

        batch_position = self.window_num * self.cfg.batch_size
        window_indices = np.arange(len(e_s)) + batch_position
        window_indices = np.setdiff1d(window_indices, np.append(all_i_anom, i_anom + batch_position))
        candidates = np.unique(window_indices - batch_position).astype(np.int64)
        non_anom_max = float(np.max(e_s[candidates])) if len(candidates) else 0.0

        E_seq = [(g[0], g[-1]) for g in consecutive_groups(i_anom) if g[0] != g[-1]]
        if inverse:
            self.i_anom_inv, self.E_seq_inv, self.non_anom_max_inv = i_anom, E_seq, non_anom_max
        else:
            self.i_anom, self.E_seq, self.non_anom_max = i_anom, E_seq, non_anom_max

    def prune_anoms(self, inverse: bool = False) -> None:
        """Drop sequences whose peak is within p of the next highest peak or error."""
        E_seq = self.E_seq_inv if inverse else self.E_seq
        e_s = self.e_s_inv if inverse else self.e_s
        non_anom_max = self.non_anom_max_inv if inverse else self.non_anom_max
        if len(E_seq) == 0:
            return

        E_seq_max = np.array([max(e_s[start : end + 1]) for start, end in E_seq])
        E_seq_max_sorted = np.append(np.sort(E_seq_max)[::-1], [non_anom_max])
        to_remove: set[int] = set()
        for i in range(len(E_seq_max_sorted) - 1):
            if (E_seq_max_sorted[i] - E_seq_max_sorted[i + 1]) / E_seq_max_sorted[i] < self.cfg.p:
                to_remove.update(np.flatnonzero(E_seq_max == E_seq_max_sorted[i]).tolist())
            else:
                to_remove = set()
        kept = [seq for i, seq in enumerate(E_seq) if i not in to_remove]

        if not kept:
            if inverse:
                self.i_anom_inv = np.array([], dtype=np.int64)
            else:
                self.i_anom = np.array([], dtype=np.int64)
            return

        indices_to_keep = np.concatenate([np.arange(start, end + 1) for start, end in kept])
        if inverse:
            self.i_anom_inv = self.i_anom_inv[np.isin(self.i_anom_inv, indices_to_keep)]
        else:
            self.i_anom = self.i_anom[np.isin(self.i_anom, indices_to_keep)]

    def score_anomalies(self, prior_idx: int) -> None:
        """Peak distance from epsilon, in units of mean + std of the window error."""
        scale = self.mean_e_s + self.sd_e_s
        for group in consecutive_groups(self.i_anom):
            span = slice(group[0], group[-1] + 1)
            score = float(np.max(np.abs(self.e_s[span] - self.epsilon)) / scale)
            inv_score = float(np.max(np.abs(self.e_s_inv[span] - self.epsilon_inv)) / scale)
            self.anom_scores.append(
                {"start_idx": group[0] + prior_idx, "end_idx": group[-1] + prior_idx, "score": max(score, inv_score)}
            )


def detect(actual: np.ndarray, predicted: np.ndarray, index: np.ndarray, cfg: Config) -> dict:
    """Telemanom's Errors.process_batches. Returned spans and scores are in series index."""
    actual = actual.astype(np.float64)
    predicted = predicted.astype(np.float64)
    if len(actual) != len(predicted):
        raise ValueError(f"len(y_hat) != len(y_test): {len(predicted)}, {len(actual)}")
    n_total = len(actual)

    raw_error = np.abs(predicted - actual)
    e_s = ewm_mean(raw_error, max(1, int(cfg.batch_size * cfg.window_size * cfg.smoothing_perc)))
    e_s[: cfg.l_s] = np.mean(e_s[: cfg.l_s * 2])

    window_size = cfg.window_size
    n_windows = int((n_total - cfg.batch_size * window_size) / cfg.batch_size)
    while n_windows < 0:
        window_size -= 1
        n_windows = int((n_total - cfg.batch_size * window_size) / cfg.batch_size)
        if window_size == 1 and n_windows < 0:
            raise ValueError(f"batch_size ({cfg.batch_size}) larger than y_test (len={n_total})")

    all_i_anom = np.array([], dtype=np.int64)
    anom_scores: list[dict] = []
    epsilon_line = np.full(n_total, np.nan)
    for i in range(n_windows + 1):
        prior_idx = i * cfg.batch_size
        idx = window_size * cfg.batch_size + i * cfg.batch_size
        if i == n_windows:
            idx = n_total

        window = ErrorWindow(e_s[prior_idx:idx], actual[prior_idx:idx], n_total, cfg, i)
        window.find_epsilon()
        window.find_epsilon(inverse=True)
        line_start = prior_idx if i == 0 else max(prior_idx, idx - cfg.batch_size)
        epsilon_line[line_start:idx] = window.epsilon

        window.compare_to_epsilon(all_i_anom)
        window.compare_to_epsilon(all_i_anom, inverse=True)
        if len(window.i_anom) == 0 and len(window.i_anom_inv) == 0:
            continue
        window.prune_anoms()
        window.prune_anoms(inverse=True)
        if len(window.i_anom) == 0 and len(window.i_anom_inv) == 0:
            continue

        window.i_anom = np.unique(np.append(window.i_anom, window.i_anom_inv)).astype(np.int64)
        window.score_anomalies(prior_idx)
        all_i_anom = np.append(all_i_anom, window.i_anom + prior_idx)
        anom_scores.extend(window.anom_scores)

    groups = consecutive_groups(np.unique(all_i_anom))
    spans = [(int(index[g[0]]), int(index[g[-1]])) for g in groups if g[0] != g[-1]]
    for score in anom_scores:
        score["start_idx"] = int(index[score["start_idx"]])
        score["end_idx"] = int(index[score["end_idx"]])
    return {
        "spans": spans,
        "anom_scores": anom_scores,
        "smoothed": e_s,
        "raw_error": raw_error,
        "epsilon": epsilon_line,
        "normalized_error": float(np.mean(raw_error / np.ptp(actual))) if np.ptp(actual) else float("nan"),
    }


def evaluate_sequences(spans: list[tuple[int, int]], labels: list[tuple[int, int]]) -> dict:
    """Detector.evaluate_sequences: each label counts once, each unmatched span is a FP.

    NASA scores each CSV row on its own, so P-2's two overlapping rows can both be hit.
    """
    matched: set[int] = set()
    tp_sequences, fp_sequences = [], []
    for start, end in spans:
        hit = [i for i, (a, b) in enumerate(labels) if start <= b and a <= end]
        if hit:
            tp_sequences.append([start, end])
            matched.update(hit)
        else:
            fp_sequences.append([start, end])
    return {
        "true_positives": len(matched),
        "false_positives": len(fp_sequences),
        "false_negatives": len(labels) - len(matched),
        "tp_sequences": tp_sequences,
        "fp_sequences": fp_sequences,
    }


def plot_detection(
    channel: str,
    seed: int,
    forecaster: str,
    index: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
    labels: list[tuple[int, int]],
    result: dict,
) -> Path:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{channel}_seed{seed}_telemanom_{forecaster}.png"
    figure, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, constrained_layout=True)
    for axis in axes:
        for start, end in labels:
            axis.axvspan(start, end, color="#f3c1b8", alpha=0.55, linewidth=0)
        for start, end in result["spans"]:
            axis.axvspan(start - 0.5, end + 0.5, color="#2f6fed", alpha=0.3, linewidth=0)

    axes[0].plot(index, actual, color="#1f2933", linewidth=0.7, label="actual")
    axes[0].plot(index, predicted, color="#2f6fed", linewidth=0.7, alpha=0.85, label="predicted")
    axes[0].set_title(f"{channel} seed {seed}, {forecaster} forecaster, telemanom threshold. Pink is NASA, blue is flagged.")
    axes[0].set_ylabel("value")
    axes[0].legend(loc="lower right")

    axes[1].plot(index, result["smoothed"], color="#b42318", linewidth=0.8, label="smoothed |error|")
    axes[1].plot(index, result["epsilon"], color="#0f6b4c", linestyle="--", linewidth=1.0, label="window epsilon")
    axes[1].set_ylabel("smoothed |error|")
    axes[1].set_xlabel("test index")
    axes[1].legend(loc="upper right")

    figure.savefig(path, dpi=140)
    plt.close(figure)
    return path


def smap_channels() -> list[str]:
    """Every SMAP channel in labeled_anomalies.csv, once each, in file order."""
    with (DATA / "labeled_anomalies.csv").open() as handle:
        rows = [row["chan_id"] for row in csv.DictReader(handle) if row["spacecraft"] == "SMAP"]
    return list(dict.fromkeys(rows))


def resolve_channels(spec: str) -> list[str]:
    if spec == "all":
        return smap_channels()
    if spec == "default":
        from schema import DEFAULT_CHANNELS

        return list(DEFAULT_CHANNELS)
    return [name.strip() for name in spec.split(",") if name.strip()]


def run_channel(channel: str, seed: int, forecaster: str, reuse: bool, cfg: Config) -> dict:
    test_series = load_series(channel, "test")
    if forecaster == "telemanom":
        if reuse and checkpoint_path(channel, seed).exists():
            model, saved = load_telemanom(channel, seed)
            cfg = replace(saved, smoothing_perc=cfg.smoothing_perc)
        else:
            model = train_telemanom(channel, seed, cfg)
            print(f"checkpoint {save_telemanom(model, channel, seed, cfg)}")
        frames, targets, index = shape_data(test_series, cfg)
        actual = targets[:, 0]
        predicted = predict_first(model, frames)
    else:
        cfg = replace(cfg, l_s=WINDOW)
        frames, actual, index = windows(test_series, WINDOW)
        predicted = predict(load_forecaster(channel, seed), frames)

    labels = anomaly_spans(channel)
    result = detect(actual, predicted, index, cfg)
    hits = overlapping(result["spans"], labels)
    scores = sequence_scores(result["spans"], labels)
    counts = evaluate_sequences(result["spans"], labels)
    auprc = smoothed_auprc(index, result["smoothed"], labels)

    record = {
        "channel": channel,
        "seed": seed,
        "forecaster": forecaster,
        "threshold_fit": "telemanom_test_windows",
        "config": cfg.__dict__,
        "normalized_error": result["normalized_error"],
        "precision": scores["precision"],
        "recall": scores["recall"],
        "f0.5": scores["f0.5"],
        "auprc": auprc,
        **counts,
        "spans": result["spans"],
        "anom_scores": result["anom_scores"],
        "label_hits": hits,
    }
    out = RUNS / channel / f"seed{seed}_telemanom_{forecaster}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n")
    figure = plot_detection(channel, seed, forecaster, index, actual, predicted, labels, result)

    print(f"smoothing span {int(cfg.batch_size * cfg.window_size * cfg.smoothing_perc)}")
    print(f"normalized prediction error {result['normalized_error']:.4f}")
    print(
        f"precision {scores['precision']:.4f}  recall {scores['recall']:.4f}  "
        f"f0.5 {scores['f0.5']:.4f}  auprc {auprc:.4f}"
    )
    print(
        f"TP {counts['true_positives']}  FP {counts['false_positives']}  FN {counts['false_negatives']}  "
        f"scores {[round(s['score'], 2) for s in result['anom_scores']]}"
    )
    print(f"labels {labels}  flagged {result['spans']}  hits {hits}")
    print(f"saved {out}")
    print(f"figure {figure}")
    return record


RESULTS = Path(__file__).resolve().parent / "results"


def write_results_csv(records: list[dict], run_id: str) -> Path:
    """ml/results/<run_id>.csv in Detector's layout, which safemode.detections reads.

    NASA's anom_scores index y_test, so they are shifted back by l_s.
    """
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{run_id}.csv"
    fields = ["run_id", "chan_id", "true_positives", "false_positives", "false_negatives",
              "tp_sequences", "fp_sequences", "anom_scores", "normalized_pred_error"]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for r in records:
            l_s = r["config"]["l_s"]
            scores = [
                {"start_idx": s["start_idx"] - l_s, "end_idx": s["end_idx"] - l_s, "score": s["score"]}
                for s in r["anom_scores"]
            ]
            writer.writerow({
                "run_id": run_id,
                "chan_id": r["channel"],
                "true_positives": r["true_positives"],
                "false_positives": r["false_positives"],
                "false_negatives": r["false_negatives"],
                "tp_sequences": str(r["tp_sequences"]),
                "fp_sequences": str(r["fp_sequences"]),
                "anom_scores": str(scores),
                "normalized_pred_error": r["normalized_error"],
            })
    return path


def summarize(records: list[dict], seed: int, forecaster: str, smoothing_perc: float, run_id: str) -> Path:
    """Detector.log_final_stats: sum TP, FP, FN over channels, then one precision and recall."""
    tp = sum(r["true_positives"] for r in records)
    fp = sum(r["false_positives"] for r in records)
    fn = sum(r["false_negatives"] for r in records)
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    summary = {
        "seed": seed,
        "forecaster": forecaster,
        "smoothing_perc": smoothing_perc,
        "channels": len(records),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "per_channel": {
            r["channel"]: {
                "tp": r["true_positives"],
                "fp": r["false_positives"],
                "fn": r["false_negatives"],
                "normalized_error": r["normalized_error"],
            }
            for r in records
        },
    }
    out = RUNS / f"telemanom_summary_seed{seed}_{forecaster}_smooth{smoothing_perc}.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")
    write_results_csv(records, run_id)
    print("\nFinal totals")
    print(f"channels {len(records)}  TP {tp}  FP {fp}  FN {fn}")
    print(f"precision {precision:.2f}  recall {recall:.2f}")
    print(f"summary {out}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="A-1")
    parser.add_argument(
        "--channels",
        help="run many and sum TP/FP/FN: 'all' (every SMAP channel), 'default' (schema.DEFAULT_CHANNELS), or a comma list",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--forecaster",
        choices=("telemanom", "residual"),
        default="telemanom",
        help="telemanom trains NASA's model; residual reuses ml.train's checkpoint",
    )
    parser.add_argument(
        "--reuse", action="store_true", help="load the saved telemanom checkpoint when one exists instead of training"
    )
    parser.add_argument("--epochs", type=int, default=Config.epochs)
    parser.add_argument(
        "--smoothing-perc",
        type=float,
        default=Config.smoothing_perc,
        help="EWM span as a fraction of batch_size * window_size; lower keeps one-sample spikes",
    )
    args = parser.parse_args()

    cfg = Config(epochs=args.epochs, smoothing_perc=args.smoothing_perc)
    if not args.channels:
        record = run_channel(args.channel, args.seed, args.forecaster, args.reuse, cfg)
        if not record["label_hits"]:
            raise SystemExit("Telemanom threshold does not overlap the NASA span.")
        return

    channels = resolve_channels(args.channels)
    run_id = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    records = []
    for position, channel in enumerate(channels, start=1):
        print(f"\n=== {position}/{len(channels)} {channel} ===", flush=True)
        records.append(run_channel(channel, args.seed, args.forecaster, args.reuse, cfg))
        summarize(records, args.seed, args.forecaster, cfg.smoothing_perc, run_id)
    print(f"results {RESULTS / (run_id + '.csv')}")


if __name__ == "__main__":
    main()
