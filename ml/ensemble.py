"""Merge telemanom runs from several seeds into one result per channel.

Spans from every seed are merged where they overlap. A merged window's
confidence is the mean over seeds of 1 - exp(-score), with 0 for a seed that
did not flag it. One seed alone tops out at 1/n, so only windows most seeds
agree on can clear the gate's auto line.

Writes ml/results/<run_id>.csv in Detector's layout plus a `confidences`
column of [start, end, confidence], which safemode.detections prefers.

    python -m ml.ensemble --seeds 0 1 2
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime

from ml.data import anomaly_spans
from ml.telemanom import RESULTS, RUNS, evaluate_sequences, resolve_channels


def score_confidence(score: float) -> float:
    return 1.0 - math.exp(-max(score, 0.0))


def load_record(channel: str, seed: int) -> dict:
    return json.loads((RUNS / channel / f"seed{seed}_telemanom_telemanom.json").read_text())


def span_scores(record: dict) -> list[tuple[int, int, float]]:
    """Each flagged span with the highest anom_score that starts inside it."""
    out = []
    for start, end in record["spans"]:
        inside = [s["score"] for s in record["anom_scores"] if start <= s["start_idx"] <= end]
        out.append((start, end, max(inside) if inside else 0.0))
    return out


def merge_seeds(records: list[dict]) -> list[tuple[int, int, float]]:
    tagged = sorted((start, end, score, seed) for seed, r in enumerate(records) for start, end, score in span_scores(r))
    clusters: list[list[tuple[int, int, float, int]]] = []
    for item in tagged:
        if clusters and item[0] <= max(member[1] for member in clusters[-1]):
            clusters[-1].append(item)
        else:
            clusters.append([item])

    merged = []
    for members in clusters:
        best = [0.0] * len(records)
        for _, _, score, seed in members:
            best[seed] = max(best[seed], score_confidence(score))
        start = min(member[0] for member in members)
        end = max(member[1] for member in members)
        merged.append((start, end, round(sum(best) / len(records), 3)))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--channels", default="default")
    parser.add_argument("--min-confidence", type=float, default=0.0, help="drop merged windows below this")
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y-%m-%d_%H.%M.%S") + "_ensemble"
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{run_id}.csv"
    fields = ["run_id", "chan_id", "seeds", "true_positives", "false_positives", "false_negatives",
              "tp_sequences", "fp_sequences", "anom_scores", "confidences"]
    totals = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for channel in resolve_channels(args.channels):
            records = [load_record(channel, seed) for seed in args.seeds]
            smoothing = {r["config"]["smoothing_perc"] for r in records}
            if len(smoothing) > 1:
                raise SystemExit(f"{channel}: seeds were scored with different smoothing {sorted(smoothing)}")
            merged = [m for m in merge_seeds(records) if m[2] >= args.min_confidence]
            labels = anomaly_spans(channel)
            counts = evaluate_sequences([(s, e) for s, e, _ in merged], labels)
            for key in totals:
                totals[key] += counts[key]
            writer.writerow({
                "run_id": run_id,
                "chan_id": channel,
                "seeds": str(args.seeds),
                "true_positives": counts["true_positives"],
                "false_positives": counts["false_positives"],
                "false_negatives": counts["false_negatives"],
                "tp_sequences": str(counts["tp_sequences"]),
                "fp_sequences": str(counts["fp_sequences"]),
                "anom_scores": "[]",
                "confidences": str([[s, e, c] for s, e, c in merged]),
            })
            print(f"{channel:5s} TP {counts['true_positives']} FP {counts['false_positives']} "
                  f"FN {counts['false_negatives']}  windows {[(s, e, c) for s, e, c in merged]}")

    tp, fp, fn = totals["true_positives"], totals["false_positives"], totals["false_negatives"]
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    print(f"\nseeds {args.seeds}  min confidence {args.min_confidence}")
    print(f"TP {tp}  FP {fp}  FN {fn}  precision {precision:.2f}  recall {recall:.2f}")
    print(f"results {path}")


if __name__ == "__main__":
    main()
