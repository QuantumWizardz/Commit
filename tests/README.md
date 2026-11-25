# tests/

Automated tests, run from the project root with:

```bash
source venv/bin/activate
pytest
```

| File | Tests |
|---|---|
| `test_features.py` | `shared/features.py`: ratios, idle flag, rolling windows (past-only, time-based, per group), feature names, baselines, calibration minutes |
| `test_logger.py` | Key classification (normal / error / shortcut / modifier), counts, pauses, active seconds, pausing; app switches and app time |
| `test_decisions.py` | DND and break rules, cooldowns, snooze, quiet hours, call apps, DND-vs-break choice, smoothing, activity mode, calibration, personal load calibration, config overrides |
| `test_consent_actions.py` | First-launch consent flow, DND on/off via Shortcuts, missing-Shortcut help, alert and check-in flows |
| `test_engine.py` | The minute loop end to end with the real models: calibration → predictions → database → DND question; Chrome without heartbeat → Miscellaneous (P5) |
| `test_privacy.py` | P1/P12 typed text never in database or logs, P3 titles never stored/logged, P4 private domains never in website time/cache/logs, P6 local SQLite file, P8 API key only in keychain, P9 delete all data, P11 retention |
| `test_redaction.py` | E-mails, links and long numbers removed from titles; 120-character limit |
| `test_categoriser.py` | Domain rules, modes, consent fallbacks, salted-hash cache, offline fallback, safe answer parsing, rate limit, P7 (API request contains only the redacted title), heartbeat processing |
| `test_server.py` | Local API: pairing token and Host checks, dashboard page with embedded token, heartbeats, private list, today/week/activity/PDF, alerts + feedback, settings read/update/validation (API key never returned), pause/resume, calibration, delete all data |
| `test_report.py` | Weekly report numbers, browser time split by website category, highlights, PDF, Monday auto-report, old PDFs deleted |
| `test_extension.py` | Extension page logic in Node: domain only (no URL), Private, Other; minimal manifest permissions |
| `conftest.py` | `FakeSystem` (no real dialogs, notifications or Shortcuts) and temporary-database fixtures |

No test opens a real dialog, changes Do Not Disturb, calls a real language model, or touches the real keychain.
