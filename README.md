# otto

An AI copilot for astronauts. Grok's chat is the only interface. Under it: a voyage calculator for mission-planning questions, and SafeMode, an LSTM that watches SMAP telemetry in the background and pushes anomalies into the chat. The crew keeps the final say on anything that cannot be undone.

## One repo

| Who | Owns | Builds |
| --- | --- | --- |
| Person A | `ml/`, `safemode/` | LSTM ensemble, scores, and the background monitor |
| Person B | `voyage/`, `app/` | Voyage calculator, Grok chat, diagnosis, and the authority gate |
| Both | `schema.py` | The alert and the voyage tool. Change it only together |

Merge to `main` about once an hour. At 3:45, point the chat at `queue/alerts.json` instead of `mock_alerts.json`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
bash download_data.sh
python schema.py
```

Person B starts the crew interface with `python -m app` (Grok Voice at http://127.0.0.1:8765). Text fallback: `python -m app.chat`. Check the calculator with `python -m voyage`.

`download_data.sh` fills `data/` (gitignored):

- `data/smap/labeled_anomalies.csv` — NASA labels
- `data/smap/train/` and `data/smap/test/` — one `.npy` per channel, from the Hugging Face mirror `appleparan/telemanom` (the original S3 zip returns 403). Column 0 is the telemetry value, scaled to (-1, 1). The rest are one-hot commands.
- `data/ephemeris/de421.bsp` — NASA planetary positions for the launch window

Put the xAI key in `.env`. Leave `.env`, `data/`, and `queue/alerts.json` out of git.

## Alert

`schema.Alert`: `alert_id`, `time` (UTC `YYYY-MM-DDTHH:MM:SSZ`), `channel`, `subsystem`, `confidence` (0–1), `values` (recent samples, oldest first, last point is the alert).

Subsystem comes from `schema.subsystem_for_channel`. Telemanom documents `P` = power and `R` = radiation. The other letters in `schema.CHANNEL_PREFIX_TO_SUBSYSTEM` are this repo's map onto Table 8.

```python
from schema import MOCK_ALERTS, load_alerts

alerts = load_alerts(MOCK_ALERTS)
```

The live queue is `schema.ALERT_QUEUE` (`queue/alerts.json`). Person A appends with `dump_alerts`. Person B reads that same list.

`schema.Authority`: `auto` (reversible and confident), `ask_crew` (cannot be undone), `escalate` (otherwise, send it to the ground). The rule lives in `app/`.

Demo alerts in `mock_alerts.json`:

1. `rw-backup` — reaction wheel on `A-1`, confidence 0.93. Gate should choose `auto` and switch to the backup.
2. `cabin-leak` — possible cabin leak on `F-2`, confidence 0.71. Gate should choose `ask_crew`.

Train `schema.DEFAULT_CHANNELS` (10). If you fall behind, use `schema.FALLBACK_CHANNELS` (5). F-2 replaced F-1: F-1's forecast error on normal data is larger than on the anomaly. Keep the score charts, the alert showing up in the chat, and the gate.

## Voyage tool

`voyage_calculate` takes a `schema.VoyageRequest` and returns a `schema.VoyageResult`.

| Input | Meaning |
| --- | --- |
| `origin` | `leo` or `earth`. Both leave a 300 km parking orbit |
| `destination` | `schema.DESTINATIONS`: `moon`, or any planet from `mercury` to `pluto` |
| `spacecraft_mass_kg` | Dry mass, no propellant |
| `isp_s` | Specific impulse, seconds |
| `crew` | Number of people |

| Output | Meaning |
| --- | --- |
| `delta_v_m_s` | Hohmann transfer |
| `travel_time_days` | One-way coast |
| `propellant_kg` | Rocket equation |
| `launch_window_utc` | Next window from Skyfield, or `null` if you drop that feature |
| `oxygen_kg`, `water_kg`, `food_kg` | Totals for the crew for the trip |

Planets are direct Hohmann transfers around the Sun with no gravity assists, so Neptune is about 31 years. The giants capture into a long ellipse rather than a low circular orbit. The travel-time checks in `schema.ROUTES` still guard the demo routes: Earth → Mars about 259 days, LEO → Moon about 5 days.

## Chat

```bash
./dev.sh                    # API on :8000 (app/server.py), console on http://localhost:3000 (web/)
OTTO_ALERTS=mock ./dev.sh   # pin the scripted demo alerts
streamlit run app/ui.py     # fallback console, same tools and gate
```

Alerts come from the live queue once it has any, from `mock_alerts.json` until then. Crew decisions and the action log live in `queue/decisions.json`; "reset demo" in the console clears them.

The gate is `app/gate.py`. Code picks `auto`, `ask_crew`, or `escalate`; Grok only explains it. `ask_crew` cards wait for the crew's Approve or Reject. Daily rates are `OXYGEN_KG_PER_PERSON_DAY`, `WATER_KG_PER_PERSON_DAY`, and `FOOD_KG_PER_PERSON_DAY`.

Chat tools: `voyage_calculate(...)`, `safemode_status`, `diagnose(alert_id)`.
