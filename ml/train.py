"""Train one LSTM forecaster and plot its test-stream forecast.

The network predicts a low, middle, and high next value at every step. Normal
spikes live inside that band. The alarm score is how far a point falls outside
it, so a drop through the floor stands out from spikes the channel always has.
A-1 is the shape check:

    python -m ml.train --channel A-1 --seed 0
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from ml.data import WINDOW, anomaly_spans, load_series, sequence_targets, windows
from ml.model import LSTMForecaster

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "ml" / "runs"
FIGURES = ROOT / "ml" / "figures"
HIDDEN = 80
LAYERS = 2
DROPOUT = 0.1
PATIENCE = 10
QUANTILES = (0.01, 0.5, 0.99)


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def pinball_loss(predicted: torch.Tensor, target: torch.Tensor, levels: torch.Tensor) -> torch.Tensor:
    """Mean pinball loss. `predicted` is (..., Q) and `target` is (...)."""
    error = target.unsqueeze(-1) - predicted
    quantiles = levels.view(*([1] * (predicted.ndim - 1)), -1)
    return torch.maximum(quantiles * error, (quantiles - 1) * error).mean()


def _last_step_pinball(model: LSTMForecaster, frames: torch.Tensor, targets: torch.Tensor, dev: torch.device) -> float:
    model.eval()
    levels = torch.tensor(model.quantiles, dtype=torch.float32, device=dev)
    total = 0.0
    count = 0
    with torch.no_grad():
        for start in range(0, len(frames), 256):
            batch_x = frames[start : start + 256].to(dev)
            batch_y = targets[start : start + 256, -1].to(dev)
            loss = pinball_loss(model(batch_x)[:, -1, :], batch_y, levels)
            total += float(loss) * len(batch_y)
            count += len(batch_y)
    return total / count


def train_forecaster(
    channel: str,
    seed: int,
    epochs: int = 50,
    batch_size: int = 64,
    lr: float = 1e-3,
    patience: int = PATIENCE,
) -> tuple[LSTMForecaster, np.ndarray, np.ndarray, np.ndarray]:
    """Fit on the train split. Return the model and test index, actual, predicted."""
    set_seed(seed)
    dev = device()
    series = load_series(channel, "train")
    frames, _, _ = windows(series, WINDOW)
    targets = sequence_targets(series, WINDOW)
    if targets.shape != (len(frames), WINDOW) or not np.allclose(targets[:, -1], series[WINDOW:, 0]):
        raise ValueError("Sequence targets are misaligned with the windows.")

    split = int(len(frames) * 0.85)
    train_x, train_y = frames[:split], targets[:split]
    val_x = torch.from_numpy(frames[split + WINDOW :])
    val_y = torch.from_numpy(targets[split + WINDOW :])
    if len(val_x) < 10:
        raise ValueError(f"{channel} train series is too short for a validation holdout")

    model = LSTMForecaster(
        hidden=HIDDEN, layers=LAYERS, dropout=DROPOUT, residual=True, quantiles=QUANTILES
    ).to(dev)
    levels = torch.tensor(model.quantiles, dtype=torch.float32, device=dev)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, factor=0.5, patience=4)
    loader = DataLoader(
        TensorDataset(torch.from_numpy(train_x), torch.from_numpy(train_y)),
        batch_size=batch_size,
        shuffle=True,
    )

    best_state: dict[str, torch.Tensor] | None = None
    best_val = float("inf")
    stall = 0
    for epoch in range(1, epochs + 1):
        model.train()
        total = 0.0
        count = 0
        for batch_x, batch_y in loader:
            batch_x = batch_x.to(dev)
            batch_y = batch_y.to(dev)
            optimizer.zero_grad()
            predicted = model(batch_x)
            loss = pinball_loss(predicted, batch_y, levels) + pinball_loss(predicted[:, -1, :], batch_y[:, -1], levels)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total += float(loss.detach()) * len(batch_y)
            count += len(batch_y)
        val_loss = _last_step_pinball(model, val_x, val_y, dev)
        scheduler.step(val_loss)
        marker = ""
        if val_loss < best_val - 1e-6:
            best_val = val_loss
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stall = 0
            marker = "  best"
        else:
            stall += 1
        print(f"epoch {epoch:02d}  train_loss {total / count:.6f}  val_pinball {val_loss:.6f}{marker}")
        if stall >= patience:
            print(f"early stop at epoch {epoch}")
            break

    if best_state is None:
        raise RuntimeError("Training produced no checkpoint.")
    model.load_state_dict(best_state)
    model.to(dev)

    test_x, test_y, test_index = windows(load_series(channel, "test"), WINDOW)
    return model, test_index, test_y, predict(model, test_x, batch_size)


def architecture(blob: dict) -> dict:
    """Rebuild the module a checkpoint was trained with. Older files are absolute forecasters."""
    state = blob["state_dict"]
    layers = sum(1 for key in state if key.startswith("lstm.weight_ih_l"))
    hidden = state["lstm.weight_ih_l0"].shape[0] // 4
    return {
        "hidden": int(blob.get("hidden", hidden)),
        "layers": int(blob.get("layers", layers)),
        "dropout": float(blob.get("dropout", 0.2)),
        "residual": bool(blob.get("residual", False)),
        "quantiles": _quantiles(blob),
    }


def _quantiles(blob: dict) -> tuple[float, ...]:
    saved = blob.get("quantiles")
    if saved:
        return tuple(float(level) for level in saved)
    outputs = blob["state_dict"]["head.weight"].shape[0]
    if outputs == 1:
        return ()
    if outputs == 3:
        return QUANTILES
    raise ValueError(f"Checkpoint head has {outputs} outputs and no quantile levels.")


def load_forecaster(channel: str, seed: int) -> LSTMForecaster:
    path = RUNS / channel / f"seed{seed}.pt"
    blob = torch.load(path, map_location="cpu", weights_only=False)
    model = LSTMForecaster(**architecture(blob))
    model.load_state_dict(blob["state_dict"])
    model.to(device())
    model.eval()
    return model


def predict(model: LSTMForecaster, frames: np.ndarray, batch_size: int = 256) -> np.ndarray:
    dev = next(model.parameters()).device
    predicted = np.empty(len(frames), dtype=np.float32)
    model.eval()
    with torch.no_grad():
        for start in range(0, len(frames), batch_size):
            batch = torch.from_numpy(frames[start : start + batch_size]).to(dev)
            out = model(batch)
            if out.ndim == 3:
                out = out[:, -1, out.shape[-1] // 2]
            elif out.ndim == 2:
                out = out[:, -1]
            predicted[start : start + len(batch)] = out.detach().cpu().numpy()
    return predicted


def score_errors(model: LSTMForecaster, frames: np.ndarray, actual: np.ndarray, batch_size: int = 256) -> np.ndarray:
    """How far each point sits outside the forecast band. Absolute error for older models."""
    dev = next(model.parameters()).device
    scores = np.empty(len(frames), dtype=np.float64)
    model.eval()
    with torch.no_grad():
        for start in range(0, len(frames), batch_size):
            batch = torch.from_numpy(frames[start : start + batch_size]).to(dev)
            out = model(batch)
            observed = actual[start : start + len(batch)]
            if out.ndim == 3:
                low = out[:, -1, 0].detach().cpu().numpy()
                high = out[:, -1, -1].detach().cpu().numpy()
                scores[start : start + len(batch)] = np.maximum(low - observed, 0.0) + np.maximum(observed - high, 0.0)
            else:
                point = out[:, -1].detach().cpu().numpy() if out.ndim == 2 else out.detach().cpu().numpy()
                scores[start : start + len(batch)] = np.abs(observed - point)
    return scores


def save_checkpoint(model: LSTMForecaster, channel: str, seed: int) -> Path:
    path = RUNS / channel / f"seed{seed}.pt"
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "channel": channel,
            "seed": seed,
            "window": WINDOW,
            "hidden": model.hidden,
            "layers": model.layers,
            "dropout": model.dropout,
            "residual": model.residual,
            "quantiles": model.quantiles,
            "state_dict": model.state_dict(),
        },
        path,
    )
    return path


def plot_forecast(
    channel: str,
    seed: int,
    index: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
    spans: list[tuple[int, int]],
) -> Path:
    error = np.abs(actual - predicted)
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{channel}_seed{seed}.png"

    figure, axes = plt.subplots(3, 1, figsize=(11, 8), constrained_layout=True)
    _shade(axes, spans)

    axes[0].plot(index, actual, color="#1f2933", linewidth=0.8, label="actual")
    axes[0].plot(index, predicted, color="#2f6fed", linewidth=0.8, alpha=0.9, label="predicted")
    axes[0].set_title(f"{channel} seed {seed}: one-step forecast on the test stream")
    axes[0].set_ylabel("value")
    axes[0].legend(loc="lower right")

    axes[1].plot(index, error, color="#b42318", linewidth=0.8)
    axes[1].set_ylabel("|error|")
    axes[1].set_title("Absolute error. The forecast misses the labeled span where this rises.")

    start, end = spans[0]
    pad = 40
    zoom = (index >= start - pad) & (index <= end + pad)
    axes[2].plot(index[zoom], actual[zoom], color="#1f2933", linewidth=1.2, label="actual")
    axes[2].plot(index[zoom], predicted[zoom], color="#2f6fed", linewidth=1.2, label="predicted")
    axes[2].set_title(f"Zoom on NASA span [{start}, {end}]")
    axes[2].set_xlabel("test index")
    axes[2].set_ylabel("value")
    axes[2].legend(loc="lower right")

    figure.savefig(path, dpi=140)
    plt.close(figure)
    return path


def _shade(axes, spans: list[tuple[int, int]]) -> None:
    for axis in axes:
        for start, end in spans:
            axis.axvspan(start, end, color="#f3c1b8", alpha=0.45, linewidth=0)


def _inside_mask(index: np.ndarray, spans: list[tuple[int, int]]) -> np.ndarray:
    inside = np.zeros(len(index), dtype=bool)
    for start, end in spans:
        inside |= (index >= start) & (index <= end)
    return inside


def persistence_predict(series: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Column 0 at t-1. The forecast for time t is the previous telemetry value."""
    return series[index - 1, 0]


def print_forecast_score(
    name: str,
    index: np.ndarray,
    actual: np.ndarray,
    predicted: np.ndarray,
    spans: list[tuple[int, int]],
) -> float:
    """Test MSE, plus MAE inside and outside the labeled spans."""
    error = np.abs(actual.astype(np.float64) - predicted.astype(np.float64))
    inside = _inside_mask(index, spans)
    outside = ~inside
    if not inside.any():
        raise SystemExit("Labeled span is outside the forecast index.")
    mse = float(np.mean(np.square(error)))
    peak_at = int(index[inside][int(np.argmax(error[inside]))])
    print(
        f"{name} test_mse {mse:.6f}  "
        f"mae outside {error[outside].mean():.4f}  mae inside {error[inside].mean():.4f}  "
        f"peak inside {error[inside].max():.4f} at {peak_at}  "
        f"peak outside {error[outside].max():.4f}"
    )
    return mse


def miss_report(index: np.ndarray, actual: np.ndarray, predicted: np.ndarray, spans: list[tuple[int, int]]) -> None:
    error = np.abs(actual.astype(np.float64) - predicted.astype(np.float64))
    inside = _inside_mask(index, spans)
    outside = ~inside
    if error[inside].max() < 0.5 or float(np.median(error[outside])) > 0.1:
        raise SystemExit("Forecast does not miss the labeled span.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="A-1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--patience", type=int, default=PATIENCE)
    args = parser.parse_args()

    series = load_series(args.channel, "train")
    frames, targets, indices = windows(series)
    if not np.array_equal(frames[0], series[:WINDOW]) or targets[0] != series[WINDOW, 0]:
        raise SystemExit("Window loader is misaligned.")
    if indices[0] != WINDOW:
        raise SystemExit("Window target index is misaligned.")

    model, index, actual, predicted = train_forecaster(
        args.channel, args.seed, epochs=args.epochs, patience=args.patience
    )
    spans = anomaly_spans(args.channel)
    test_series = load_series(args.channel, "test")
    persistence = persistence_predict(test_series, index)
    lstm_mse = print_forecast_score("lstm", index, actual, predicted, spans)
    persist_mse = print_forecast_score("persistence", index, actual, persistence, spans)
    print(f"test_mse gap (persistence - lstm) {persist_mse - lstm_mse:.6f}")
    if model.quantiles:
        score = score_errors(model, windows(test_series, WINDOW)[0], actual)
        inside = _inside_mask(index, spans)
        outside = ~inside
        print(
            f"exceedance mean outside {score[outside].mean():.4f}  mean inside {score[inside].mean():.4f}  "
            f"peak inside {score[inside].max():.4f}  peak outside {score[outside].max():.4f}"
        )
    checkpoint = save_checkpoint(model, args.channel, args.seed)
    figure = plot_forecast(args.channel, args.seed, index, actual, predicted, spans)
    print(f"checkpoint {checkpoint}")
    print(f"figure {figure}")
    miss_report(index, actual, predicted, spans)


if __name__ == "__main__":
    main()
