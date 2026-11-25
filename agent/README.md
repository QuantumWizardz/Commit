# agent/ — the Commit desktop agent (Phase 1, macOS)

Runs in the background, counts keyboard/mouse activity (never what you type), detects the working condition
(Calm / Interrupted / Pressured), computes a load score, and offers Do Not Disturb or a short break.

## Run

```bash
# from the project root, once
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# start everything
python -m agent.main
```

The models in `shared/models/` must exist (run the Phase 0 notebooks first).

### First launch
1. Welcome and five separate consent switches (activity counts is required).
2. **Permissions:** System Settings → Privacy & Security → **Accessibility** and **Input Monitoring**:
   add the app that runs Python (Terminal or Visual Studio Code), then restart Commit.
3. **Do Not Disturb Shortcuts:** create "Commit Focus On" and "Commit Focus Off" — see `docs/SHORTCUTS_SETUP.md`.
4. **Calibration:** the menu bar shows "Commit · Learning" for your first 15 active minutes.

## Files

| File | Job |
|---|---|
| `main.py` | Starts everything; Pause / Resume / Delete all data / Quit |
| `menubar.py` | Menu-bar icon and menu (rumps) |
| `consent.py` | First-launch consent, permissions, Shortcuts setup |
| `logger.py` | Keyboard/mouse **counts** per minute (pynput) |
| `app_tracker.py` | Frontmost app name every 5 s, app switches |
| `feature_builder.py` | Recent minutes → features via `shared/features.py`; activity mode |
| `calibration.py` | Personal baseline from the first 15 active minutes |
| `detector.py` | Condition model + 5-minute smoothing |
| `load_scorer.py` | 0–100 load score + personal calibration from check-ins |
| `decisions.py` | Pure rules: when to suggest DND or a break |
| `actions.py` | DND via Shortcuts, alert dialogs, break timer |
| `feedback.py` | 👍/👎 after alerts, 1–5 check-ins |
| `engine.py` | The once-a-minute loop tying it all together |
| `storage.py` | SQLite database (README section 13) |
| `config.py` | `config/default.yaml` + user overrides |
| `keychain.py` | The optional API key in the macOS Keychain (P8) |
| `platform/macos.py` | All macOS-specific calls (dialogs, notifications, Shortcuts, frontmost app) |

## Where things are stored
- Database: `~/Library/Application Support/Commit/commit.db`
- Debug log (counts and errors only, never typed text): `~/Library/Logs/Commit/commit.log`

## Phase 2 additions
`main.py` also starts the local server (`server/`) for the Chrome extension. Menu bar:
**Weekly report (PDF)**, **Settings → Website categories** (Off / Rules only / Local AI / My own API key,
AI model…, Set API key…, Test AI connection) and **Settings → Extension pairing token…**.
The engine records Chrome time without extension heartbeats as "Miscellaneous" (e.g. incognito),
never interrupts while a Google Meet tab is in front, and saves the weekly PDF every Monday
(`~/Library/Application Support/Commit/reports/`).

## Phase 3 additions
**Open dashboard** opens `http://127.0.0.1:8765/` (build it first: see `dashboard/README.md`). All settings —
quiet hours, check-in frequency, retention, categoriser, API key, private websites, consent — are in the
dashboard's Settings page. `CommitAgent` gives the API its controls: status, pause/resume, re-run calibration,
and delete all data (then the app quits).

## Tests
`pytest` from the project root. `tests/test_engine.py` runs the real models end to end with simulated minutes.
