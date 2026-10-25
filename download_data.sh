#!/usr/bin/env bash
# SMAP telemetry plus the DE421 planetary kernel. Safe to re-run.
# Uses curl. The python.org macOS install often fails HTTPS inside urllib.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA="$ROOT/data"
SMAP="$DATA/smap"
EPHEM="$DATA/ephemeris"
mkdir -p "$SMAP" "$EPHEM"

UA="otto-hackathon/1.0 (educational)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [[ ! -f "$SMAP/labeled_anomalies.csv" ]]; then
  echo "Fetching anomaly labels..."
  curl -fsSL -A "$UA" -o "$SMAP/labeled_anomalies.csv" \
    "https://raw.githubusercontent.com/khundman/telemanom/master/labeled_anomalies.csv"
fi

train_n="$(find "$SMAP/train" -name '*.npy' 2>/dev/null | wc -l | tr -d '[:space:]')"
test_n="$(find "$SMAP/test" -name '*.npy' 2>/dev/null | wc -l | tr -d '[:space:]')"
if [[ "${train_n:-0}" -lt 1 || "${test_n:-0}" -lt 1 ]]; then
  echo "Fetching SMAP/MSL channel files..."
  : > "$tmp/needed.tsv"
  for split in train test; do
    mkdir -p "$SMAP/$split"
    curl -fsSL -A "$UA" -o "$tmp/${split}.json" \
      "https://huggingface.co/api/datasets/appleparan/telemanom/tree/main/data/data/${split}"
    python3 - "$tmp/${split}.json" "$SMAP/$split" "$tmp/needed.tsv" <<'PY'
import json, sys
from pathlib import Path
listing = json.loads(Path(sys.argv[1]).read_text())
dest_dir = Path(sys.argv[2])
out = Path(sys.argv[3])
base = "https://huggingface.co/datasets/appleparan/telemanom/resolve/main/"
lines = []
for item in listing:
    path = str(item.get("path", ""))
    if item.get("type") != "file" or not path.endswith(".npy"):
        continue
    dest = dest_dir / path.rsplit("/", 1)[-1]
    size = int(item["size"])
    if dest.exists() and dest.stat().st_size == size:
        continue
    lines.append(f"{base}{path}\t{dest}\t{size}")
with out.open("a") as handle:
    if lines:
        handle.write("\n".join(lines) + "\n")
PY
  done
  needed="$(grep -c . "$tmp/needed.tsv" || true)"
  echo "  ${needed} files to fetch"
  if [[ "$needed" != "0" ]]; then
    < "$tmp/needed.tsv" xargs -P 8 -n 3 bash -c '
      url="$1"; dest="$2"; size="$3"; part="${dest}.part"
      curl -fsSL -L -A "otto-hackathon/1.0 (educational)" -o "$part" "$url"
      actual="$(wc -c < "$part" | tr -d "[:space:]")"
      if [[ "$actual" != "$size" ]]; then
        echo "size mismatch for $dest ($actual != $size)" >&2
        rm -f "$part"
        exit 1
      fi
      mv "$part" "$dest"
    ' _
  fi
else
  echo "SMAP channel files already present ($train_n train, $test_n test)."
fi

if [[ ! -f "$EPHEM/de421.bsp" ]]; then
  echo "Fetching NASA DE421 planetary ephemeris..."
  curl -fL --retry 3 -A "$UA" -o "$EPHEM/de421.bsp" \
    "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/a_old_versions/de421.bsp"
fi

echo "Ready."
echo "  labels:    $SMAP/labeled_anomalies.csv"
echo "  train/test: $SMAP"
echo "  ephemeris: $EPHEM/de421.bsp"
