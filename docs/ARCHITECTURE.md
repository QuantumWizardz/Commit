# Architecture notes

See README section 5 for the full picture. This file describes what exists so far.

## Phase 1: desktop agent (one Python process)

```
 main thread            background threads
 ┌──────────────┐       ┌─────────────────┐  counts   ┌──────────────────────────────────────┐
 │ menubar.py   │       │ logger.py       │──────────▶│ engine.py  (every minute)            │
 │ (rumps)      │◀──────│ pynput listeners│           │  feature_builder → shared/features.py│
 │ state, menu  │status │                 │           │  calibration / detector / load_scorer│
 └──────────────┘       ├─────────────────┤  apps     │  decisions.py (pure rules)           │
                        │ app_tracker.py  │──────────▶│  storage.py (SQLite)                 │
                        │ every 5 s       │           └───────────────┬──────────────────────┘
                        └─────────────────┘                           │ submit flow
                                                       ┌──────────────▼──────────────┐
                                                       │ actions.AlertWorker          │
                                                       │  one dialog at a time:       │
                                                       │  DND / break / check-in      │
                                                       │  + feedback.py (👍/👎, 1–5)   │
                                                       └──────────────┬──────────────┘
                                                                      │
                                                     platform/macos.py: osascript dialogs,
                                                     notifications, `shortcuts run`, NSWorkspace
```

* **One feature code path.** `shared/features.py` is used by the Phase 0 notebooks and by `feature_builder.py`.
* **Pure decision rules.** `decisions.py` takes data in and returns "dnd" / "break" / None. No I/O, so it is fully tested.
* **Dialogs never block the minute loop.** They run on the AlertWorker thread and time out after 30 s.
* **OS-specific code** lives only in `agent/platform/` (Windows in Phase 4).
* **Settings** = `config/default.yaml` + user overrides in the `settings` table (`agent/config.py`).

## Phase 2: extension, local server, categoriser, weekly report

```
 Chrome extension (MV3)                    same Python process as the agent
 ┌──────────────────────┐  POST heartbeat  ┌──────────────────────────────────────────────┐
 │ background.js        │ ───────────────▶ │ server/app.py (FastAPI, 127.0.0.1:8765)      │
 │ active tab, 30 s     │  X-Commit-Token  │   returns 202 at once                        │
 │ popup: private list  │ ◀──────────────▶ │ categoriser.HeartbeatProcessor (thread)      │
 └──────────────────────┘                  │   rules → cache(hash) → redaction → LLM      │──▶ Ollama 127.0.0.1:11434
                                           │   saves domain + category + seconds only     │    (or user's API, consent)
                                           │ report.py: /api/week, /api/report/pdf        │
                                           └───────────────┬──────────────────────────────┘
                                                           │ received seconds, current domain
                                           engine.py: Chrome in front + no heartbeat → "Miscellaneous";
                                           Meet tab in front → never interrupt; Monday → weekly PDF
```

* The title exists only in the heartbeat request and the categoriser's local variables; the cache keys are salted hashes.
* Every API route needs the pairing token; no CORS headers, so web pages cannot use the API.

## Phase 3: dashboard

```
 Browser: http://127.0.0.1:8765/            server/app.py
 ┌────────────────────────────────┐  GET /  ┌──────────────────────────────────────────────┐
 │ dashboard/dist (React)         │ ◀────── │ index.html + <meta commit-token>             │
 │ Home · Activity · Weekly report│ /api/*  │ /api/today, /week, /activity, /alerts,       │
 │ Alerts · Settings              │ ──────▶ │ /settings, /pause, /calibration, DELETE /data│
 └────────────────────────────────┘  token  └──────────────┬───────────────────────────────┘
                                                            │ agent controls (status, pause, recalibrate, delete)
                                                            ▼
                                                     agent/main.py CommitAgent
```

* Settings written by the dashboard go to the `settings` table (config overrides); the agent reads them every minute.
* The dashboard downloads nothing from the internet (no CDN scripts, no web fonts).
