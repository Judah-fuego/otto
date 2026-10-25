# otto

A simulated spacecraft flies the space station's real orbit. An LSTM ensemble flags faults in replayed NASA SMAP telemetry, and Grok explains them. The crew keeps the final say on anything that cannot be undone. How much Grok may do alone depends on whether a ground station can see the spacecraft.

## One repo, two folders each

| Who | Owns | Builds |
| --- | --- | --- |
| Person A | `ml/`, `sim/` | LSTM ensemble and the voyage simulator |
| Person B | `agent/`, `app/` | Grok tools, the authority gate, and the Guide |
| Both | `schema.py` | The event format. Change it only together |

Work on your own branch and merge to `main` about once an hour. At 3:45 the join is: Person A's detector emits the same JSON that `mock_events.json` already has, and the Guide reads it.

Fake the other half until it is real. Person B loads `mock_events.json`. Person A writes that same shape, so the swap is one path change.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
bash download_data.sh
python schema.py
```

`download_data.sh` puts these under `data/` (gitignored):

- `data/smap/labeled_anomalies.csv` — NASA labels for scoring, from the telemanom repo
- `data/smap/train/` and `data/smap/test/` — one `.npy` per SMAP and MSL channel. The original S3 zip returns 403, so the script reads the same arrays from the Hugging Face mirror `appleparan/telemanom`. Values are anonymized and scaled to (-1, 1). Column 0 is the telemetry value; the rest are one-hot commands.
- `data/orbit/iss.tle` — ISS (ZARYA), NORAD 25544, from CelesTrak. Refreshed every time you run the script.

Put the xAI key in `.env`. Do not commit `.env` or `data/`.

## The event

`schema.AnomalyEvent` has six fields. The first five are the shared anomaly record; `event_id` ties it to the scenario and the audit log.

| Field | Meaning |
| --- | --- |
| `time` | Mission clock, UTC, `YYYY-MM-DDTHH:MM:SSZ`. Not a SMAP sample index. |
| `channel` | SMAP id, such as `A-1` |
| `subsystem` | A Table 8 id. Always take it from `schema.subsystem_for_channel`. |
| `confidence` | Ensemble score from 0 to 1 |
| `ground_contact` | `true` or `false`. `true` means a ground station can see the spacecraft. |
| `event_id` | Stable id, shared with `sim/scenarios/demo.json` |

```python
from schema import load_events

events = load_events("mock_events.json")
```

Train on `schema.DEFAULT_CHANNELS` (10). If you fall behind, use `schema.FALLBACK_CHANNELS` (5). Do not drop the score charts or the gate.

SMAP letters are anonymized. Telemanom only documents `P` (power) and `R` (radiation). The other letters in `schema.CHANNEL_PREFIX_TO_SUBSYSTEM` are this repo's map onto the survey's Table 8, so the Guide has a subsystem name. There is one map.

## Demo clock

`sim/scenarios/demo.json` is the script both sides code against. `t0` is `2026-10-25T18:00:00Z`. `clock_speed` 60 means one simulated minute per real second, for a short demo.

1. `t_min` 0–8: in contact.
2. `t_min` 8: blackout.
3. `t_min` 12, `rw-blackout`: reaction-wheel fault on `A-1`, confidence 0.93, no contact. Reversible. The gate should choose `auto` and switch to the backup wheel.
4. `t_min` 18, `cabin-leak`: possible cabin leak on `F-1`, confidence 0.71, no contact. Not reversible. The gate should choose `ask_crew`.
5. `t_min` 26: contact returns. The cabin-leak case goes to mission control with Grok's summary (`escalate`).

`reversible` lives on the scenario fault, not on the event. The gate reads it from the diagnosis.

`schema.Authority` is the gate's vocabulary: `auto`, `ask_crew`, `escalate`. The rule that picks one lives in `agent/`.

Ground stations for the pass geometry are in `sim/ground_stations.json`. Sunlight, the battery, and fault injection on cue belong to `sim/`.

## Later, not now

Wire one Streamlit screen with four panels: the ground-track (or a contact timeline if the map slips), telemetry with anomaly shading, the alert card, and the Guide. Cache Grok's answers for `rw-blackout` and `cabin-leak` before the live demo.
