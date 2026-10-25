#!/usr/bin/env bash
# Download the files both people need. Safe to run again.
# Channel arrays that are already present and the right size are left in place.
# The ISS element set is refreshed every run. data/ is gitignored.
#
# Uses curl for HTTPS. The python.org install on macOS often fails certificate
# checks inside urllib, and curl uses the system trust store.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA="$ROOT/data"
SMAP="$DATA/smap"
ORBIT="$DATA/orbit"
mkdir -p "$SMAP" "$ORBIT"

UA="otto-hackathon/1.0 (educational; spacecraft-anomaly demo)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [[ ! -f "$SMAP/labeled_anomalies.csv" ]]; then
  echo "Fetching anomaly labels..."
  curl -fsSL -A "$UA" -o "$SMAP/labeled_anomalies.csv" \
    "https://raw.githubusercontent.com/khundman/telemanom/master/labeled_anomalies.csv"
fi

echo "Fetching SMAP/MSL channel files from the Hugging Face mirror..."
: > "$tmp/needed.tsv"
for split in train test; do
  mkdir -p "$SMAP/$split"
  curl -fsSL -A "$UA" -o "$tmp/${split}.json" \
    "https://huggingface.co/api/datasets/appleparan/telemanom/tree/main/data/data/${split}"
  python3 - "$tmp/${split}.json" "$SMAP/$split" "$tmp/needed.tsv" <<'PY'
import json
import sys
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
    handle.write("\n".join(lines) + ("\n" if lines else ""))
PY
done

needed="$(grep -c . "$tmp/needed.tsv" || true)"
echo "  ${needed} files to fetch"
if [[ "$needed" != "0" ]]; then
  # xargs -P is available on macOS. The trailing "_" is bash's $0.
  < "$tmp/needed.tsv" xargs -P 8 -n 3 bash -c '
    url="$1"
    dest="$2"
    size="$3"
    tmp="${dest}.part"
    curl -fsSL -L -A "otto-hackathon/1.0 (educational)" -o "$tmp" "$url"
    actual="$(wc -c < "$tmp" | tr -d "[:space:]")"
    if [[ "$actual" != "$size" ]]; then
      echo "size mismatch for $dest ($actual != $size)" >&2
      rm -f "$tmp"
      exit 1
    fi
    mv "$tmp" "$dest"
  ' _
fi

echo "Fetching ISS (ZARYA, NORAD 25544) elements from CelesTrak..."
curl -fsSL -A "$UA" -o "$ORBIT/iss.tle" \
  "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"

train_n="$(find "$SMAP/train" -name '*.npy' | wc -l | tr -d '[:space:]')"
test_n="$(find "$SMAP/test" -name '*.npy' | wc -l | tr -d '[:space:]')"
if [[ "$train_n" -lt 1 || "$test_n" -lt 1 ]]; then
  echo "No channel files landed in $SMAP" >&2
  exit 1
fi

echo "Ready."
echo "  labels:    $SMAP/labeled_anomalies.csv"
echo "  train:     $SMAP/train ($train_n files)"
echo "  test:      $SMAP/test ($test_n files)"
echo "  ISS orbit: $ORBIT/iss.tle"
