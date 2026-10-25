"""Run NASA Telemanom (vendored in ml/telemanom) on the SMAP/MSL data in data/smap.

Telemanom reads data/train, data/test, and config.yaml relative to the working
directory, so this runs from ml/ with data/train and data/test linked to
../data/smap. Models, y_hat, and smoothed errors land in ml/data/<run_id>/,
results in ml/results/<run_id>.csv, figures in ml/figures/<run_id>/.

    python ml/run.py --channels A-1 F-1
    python ml/run.py                      # every labeled channel, as in the paper
    python ml/run.py --no-labels --channels A-1
"""

import argparse
import os
import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
SMAP = ML.parent / "data" / "smap"
LABELS = SMAP / "labeled_anomalies.csv"


def link_data():
    data = ML / "data"
    data.mkdir(exist_ok=True)
    for split in ("train", "test"):
        link = data / split
        if not link.exists():
            link.symlink_to(SMAP / split, target_is_directory=True)
    (ML / "results").mkdir(exist_ok=True)


def plot(detector, out_dir):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    l_s = detector.config.l_s
    for row in detector.result_df.to_dict("records"):
        chan = row["chan_id"]
        y_hat = np.load(ML / "data" / detector.id / "y_hat" / f"{chan}.npy")
        e_s = np.load(ML / "data" / detector.id / "smoothed_errors" / f"{chan}.npy")
        actual = np.load(ML / "data" / "test" / f"{chan}.npy")[l_s:l_s + len(y_hat), 0]
        index = np.arange(len(y_hat)) + l_s

        if detector.labels_path:
            labels = eval(row["anomaly_sequences"]) if isinstance(row["anomaly_sequences"], str) else row["anomaly_sequences"]
            flagged = list(row["tp_sequences"]) + list(row["fp_sequences"])
        else:
            labels, flagged = [], list(row["anomaly_sequences"])

        fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, constrained_layout=True)
        for ax in axes:
            for start, end in labels:
                ax.axvspan(start, end, color="#f3c1b8", alpha=0.55, linewidth=0)
            for start, end in flagged:
                ax.axvspan(start, end, color="#2f6fed", alpha=0.3, linewidth=0)
        axes[0].plot(index, actual, color="#1f2933", linewidth=0.7, label="actual")
        axes[0].plot(index, y_hat, color="#2f6fed", linewidth=0.7, alpha=0.85, label="predicted")
        axes[0].set_title(f"{chan} telemanom. Pink is NASA label, blue is flagged.")
        axes[0].legend(loc="lower right")
        axes[1].plot(index, e_s, color="#b42318", linewidth=0.8, label="smoothed |error|")
        axes[1].set_xlabel("test index")
        axes[1].legend(loc="upper right")
        path = out_dir / f"{chan}.png"
        fig.savefig(path, dpi=140)
        plt.close(fig)
        print(f"figure {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", nargs="*", help="channel ids to run, default all")
    parser.add_argument("--no-labels", action="store_true", help="skip scoring against labeled_anomalies.csv")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    link_data()
    os.chdir(ML)
    sys.path.insert(0, str(ML))
    from telemanom.detector import Detector

    detector = Detector(labels_path=None if args.no_labels else str(LABELS))
    if args.channels:
        missing = set(args.channels) - set(detector.chan_df.chan_id)
        if missing:
            raise SystemExit(f"unknown channels: {sorted(missing)}")
        detector.chan_df = detector.chan_df[detector.chan_df.chan_id.isin(args.channels)].reset_index(drop=True)
    detector.run()
    print(f"results {ML / 'results' / (detector.id + '.csv')}")
    if not args.no_plot:
        plot(detector, ML / "figures" / detector.id)


if __name__ == "__main__":
    main()
