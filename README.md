# Otto

An AI copilot for a crewed spacecraft. The crew talks only to Grok. Under the chat, three things do the work:

- **Voyage** answers planning questions with Hohmann transfers, the rocket equation, Skyfield launch windows, and crew consumables. Grok never does the orbital math itself.
- **SafeMode** watches NASA SMAP telemetry with a Telemanom LSTM and pushes anomalies into the chat.
- **The authority gate** decides who acts. Reversible and confident actions run on their own. Anything that cannot be undone waits for the crew. Anything else goes to the ground. The model only explains the decision the code already made.

The crew console is a Next.js app. It shows the ship, the map, supplies, open alerts, and the action log. A live Grok Voice call is the mic.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # put the xAI key in XAI_API_KEY
bash download_data.sh         # SMAP telemetry + NASA DE421 ephemeris
bash dev.sh                   # API on :8000, console on http://localhost:3000
```

`dev.sh` installs the web dependencies if they are missing, starts `uvicorn app.server:app` on port 8000, and `next dev` on port 3000. The API starts a SafeMode replay in the background the first time it comes up.

For the three-minute walkthrough, follow `demo-script.md`. Reset the console first and leave the ship staged. A full coast is about five minutes and fires faults by itself.

```bash
OTTO_ALERTS=mock ./dev.sh     # pin the two scripted alerts and ignore the live queue
python -m voyage              # Earth → Mars ~259 days, LEO → Moon ~5 days
python schema.py              # checks mock_alerts.json and a voyage request
python -m app                 # gate self-check, then the API only
```

Leave `.env`, `data/`, trained weights (`*.pt`), and the live files under `queue/` out of git. See `.gitignore`.

## How a turn works

The browser polls `GET /api/state` about every 1.5 seconds. Each new alert is diagnosed once. The gate picks `auto`, `ask_crew`, or `escalate`, and the server writes that outcome to `queue/decisions.json`. A background thread asks Grok for a short narration so the page does not wait on the model.

Chat goes to `POST /api/chat`. Grok can call `mission_status`, `voyage_calculate`, `safemode_status`, and `diagnose`. An irreversible action is recorded only when the crew holds the button on the alert card. Saying yes in the chat does not count.

Voice is a live call. `POST /api/voice/session` mints a short-lived token; the browser talks to xAI directly, and tool calls come back through `POST /api/voice/tool`. Push-to-talk uses `POST /api/stt` and `POST /api/tts`.

## Authority gate

`app/gate.py`. Confidence at or above **0.85** plus a reversible action is `auto`. An irreversible action is always `ask_crew`, whatever the confidence. A reversible action below 0.85 is `escalate` (ground).

| Subsystem | Channel | Proposed action | Who acts |
| --- | --- | --- | --- |
| Attitude | A, G | Switch to the backup reaction wheel | auto, if confident |
| Power | P, B | Shed loads, move to the redundant bus | auto, if confident |
| Thermal | T | Switch to the redundant cooling loop | auto, if confident |
| Communications | S | Fail over to the backup transponder | auto, if confident |
| Data handling | R | Reboot onto the backup image | auto, if confident |
| Propulsion | D | Isolate the thruster branch | crew |
| Mechanisms | E | Force the deployment | crew |
| Life support | F | Seal the leaking module and vent it | crew |

A few channels override that table with their own irreversible procedure: `F-3` CO2 scrubber, `P-3` battery jettison, `T-2` avionics fire, `G-2` detumble, `R-2` solar flare. Each one has a checklist and a line for what happens if the crew rejects it or runs out of time.

The two scripted alerts in `mock_alerts.json`:

1. `rw-backup` — reaction wheel on `A-1`, confidence 0.93. Gate chooses `auto`.
2. `cabin-leak` — cabin pressure on `F-2`, confidence 0.71. Gate chooses `ask_crew`.

During a flight the crew has **60 seconds** of real time to answer an open decision. Pausing the coast does not stop that clock. If it expires, the mission is lost and the log records why.

Channel letters come from `schema.CHANNEL_PREFIX_TO_SUBSYSTEM`. Telemanom documents `P` = power and `R` = radiation. The other letters are this repo's map onto the eight spacecraft subsystems.

## Chat tools

| Tool | What it returns |
| --- | --- |
| `mission_status` | Where the selected ship is, days left, supplies after arrival, light delay, and open problems |
| `voyage_calculate` | Delta-v, coast time, propellant, next launch window, oxygen, water, food |
| `safemode_status` | Whether the monitor is running, and the latest alerts |
| `diagnose(alert_id)` | The shift in the trace, the proposed action, the checklist, and what happens if it is not done |

`voyage_calculate` takes `origin` (`leo` or `earth`), `destination` (`moon`, or any planet from `mercury` to `pluto`), `spacecraft_mass_kg` (dry mass), `isp_s`, and `crew`. Both origins leave a 300 km parking orbit. Daily rates, shared by the calculator and the chat: oxygen 0.84 kg, water 2.50 kg, food 1.80 kg, per person.

Planets are direct Hohmann transfers around the Sun, with no gravity assists, so Neptune is on the order of decades. Rocky worlds capture into a low circular orbit. The giants capture into a long ellipse. The checks in `schema.ROUTES` still guard the demo routes: Earth to Mars about 259 days, LEO to the Moon about 5 days. Launch windows come from Skyfield and `data/ephemeris/de421.bsp`, and are `null` if that file is missing.

## Missions and flight

`app/missions.py` is the catalog. The default is **Ares**, a four-person Mars landing at Jezero. The rest are the six Apollo landings, later Mars and Jupiter expeditions, and further-out trips (Venus clouds, Mercury, Titan, Pluto). Choosing one in the console sets the map, the supplies, and the next launch. The choice is stored in `queue/mission.json`. Change it only while the ship is not flying.

**Launch** runs the selected coast in about five minutes of real time at 1× (`app/flight.py`). Speed can be 0.5×, 1×, 2×, or 4×. Thirteen scripted faults are spread along the route. Each one shows as a caution a few mission days early, then injects an alert through `app/simulate.py`. The ship holds while a crew decision is open, so faults arrive one at a time. Reset clears decisions, the log, and simulated alerts, and marks alerts already in the queue as cleared so they do not dump back onto the next poll.

## SafeMode

SafeMode is a PyTorch port of NASA Telemanom (Hundman et al., 2018). Two stacked LSTMs (80, 80) read 250 samples and forecast the next telemetry value. Forecast error is smoothed, then thresholded per window. No labels are used to pick the threshold. NASA's `labeled_anomalies.csv` only scores the result.

Train the ten channels in `schema.DEFAULT_CHANNELS` (`P-1`, `A-1`, `T-1`, `S-1`, `F-2`, `E-1`, `G-1`, `R-1`, `D-1`, `B-1`). `F-2` stands in for `F-1`: on `F-1` the forecast error on normal data is larger than on the anomaly. If a run falls behind, `schema.FALLBACK_CHANNELS` is the first five.

```bash
python -m ml.telemanom --channels default --seed 0
python -m ml.ensemble --seeds 0 1 2 --channels default
python -m safemode.monitor --fresh --speed 35 --tick 0.4 --start 4400
```

`ml/telemanom.py` writes checkpoints under `ml/runs/`, score charts under `ml/figures/`, and a results CSV under `ml/results/`. The ensemble merges windows across seeds into another CSV. The monitor replays `data/smap/test/` and, when the cursor crosses a detected window, appends an `Alert` to `queue/alerts.json`. `--source labels` uses NASA's spans instead, which is the answer key, so use it only to exercise the pipe before a model run exists.

Column 0 of each `.npy` is the telemetry value, scaled to (−1, 1). The rest are one-hot commands. The files come from the Hugging Face mirror `appleparan/telemanom`. The original S3 zip returns 403.

An alert is `schema.Alert`: `alert_id`, `time` (UTC `YYYY-MM-DDTHH:MM:SSZ`), `channel`, `subsystem`, `confidence` (0–1), and `values` (oldest first; the last point is the alert). The live queue is `queue/alerts.json`. Until that file has anything, the console reads `mock_alerts.json`. `OTTO_ALERTS=mock` forces the scripted pair even when the queue exists. Hand-injected demo faults go to `queue/simulated.json` and sit beside the live ones. The side panel can fire any scenario in `app/simulate.py` (`reaction_wheel`, `cabin_leak`, `transponder`, and the rest of the flight list).

## Layout

```
schema.py            Alert, VoyageRequest, VoyageResult, channel map, consumable rates
app/                 API, Grok chat, voice token, gate, missions, flight, scripted faults
voyage/              Hohmann math, rocket equation, Skyfield windows
safemode/            Detection windows and the telemetry replay
ml/                  Telemanom LSTM, seed ensemble, score charts
web/                 Next.js crew console (do not start it on its own; use dev.sh)
mock_alerts.json     The two scripted demo alerts
demo-script.md       Three-minute walkthrough
download_data.sh     SMAP channels, labels, and DE421
queue/               Live alerts, decisions, flight, mission selection (gitignored)
data/                Telemetry and ephemeris (gitignored)
```

`schema.py` is the contract between the model and the chat. An alert written by SafeMode and a voyage result returned to Grok both have to pass the parsers in that file.

## HTTP API

All of these are on `http://127.0.0.1:8000`. The console proxies them.

| Method | Path | Role |
| --- | --- | --- |
| GET | `/api/state` | Alerts, log, mission, flight, SafeMode status |
| POST | `/api/chat` | One Grok turn, with tool calls |
| POST | `/api/alerts/{id}/decision` | `{ "approved": true \| false }` for an `ask_crew` alert |
| POST | `/api/alerts/{id}/reopen` | Put a rejected alert back in front of the crew |
| POST | `/api/reset` | Quiet ship. Narrations are kept |
| POST | `/api/mission` | `{ "id": "ares" }` while nothing is flying |
| POST | `/api/flight/start` | `{ "speed": 1 }` from a clean ship |
| POST | `/api/flight/control` | Pause, resume, or change speed |
| POST | `/api/flight/stop` | End the coast |
| GET | `/api/simulate` | Scenario names |
| POST | `/api/simulate/{scenario}` | Inject one scripted fault |
| GET | `/api/figures/{channel}` | Score chart from `ml/figures/` |
| POST | `/api/voice/session` | Ephemeral Grok Voice token |
| POST | `/api/voice/tool` | Run a tool from the live call |
| POST | `/api/tts` | MP3 of a line |
| POST | `/api/stt` | Raw audio body, returns text |

## Tests

```bash
python -m unittest discover -s tests
```

`tests/test_person_b.py` covers the gate, the voyage checks, and the chat tools. `tests/test_missions.py` covers the catalog and the trajectory.
