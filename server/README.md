# server/ — local API, dashboard serving, title categoriser, weekly report (Phases 2–3)

The server runs **inside the agent process** (`python -m agent.main` starts it) on
`http://127.0.0.1:8765` only. Nothing listens on other network interfaces.

| File | Job |
|---|---|
| `app.py` | FastAPI routes (README section 14), pairing-token check, `LocalServer` (uvicorn on a background thread) |
| `categoriser.py` | (domain, title) → category: rules → salted-hash cache → local Ollama or the user's API; `HeartbeatProcessor` saves website time in the background |
| `redaction.py` | Removes e-mails, links and long numbers from titles and cuts them to 120 characters |
| `report.py` | Weekly report data and PDF; automatic Monday PDF |

## Routes (all need the header `X-Commit-Token: <pairing token>`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/web/heartbeat` | `{domain?, title?, category?, seconds}` from the extension; returns at once (202) |
| GET / POST / DELETE | `/api/private-domains` | read / add / remove a "Don't track" domain (`{domain}` body) |
| GET | `/api/status` | running, state, load score, paused, website tracking consent |
| GET | `/api/today` | Home screen: today's and yesterday's stats, load score, timeline bands, recent alerts |
| GET | `/api/week?start=YYYY-MM-DD` | weekly report data (default: last 7 days) |
| GET | `/api/report/pdf?start=YYYY-MM-DD` | weekly report PDF |
| GET | `/api/activity?start=YYYY-MM-DD` | categories, top apps, top websites (with category), active time per day |
| PUT | `/api/domain-rules` | `{domain, category}`: the user's correction becomes a rule |
| GET | `/api/alerts` | alert history |
| POST | `/api/alerts/{id}/feedback` | `{feedback: "up" \| "down"}` |
| GET / PUT | `/api/settings` | read / change settings (every value is validated; the API key goes to the keychain and is never returned) |
| POST | `/api/llm/test` | test the language-model connection |
| POST | `/api/calibration/restart` | re-run calibration |
| POST | `/api/pause`, `/api/resume` | pause / resume tracking |
| DELETE | `/api/data` | `{confirm: "DELETE"}`: delete all data, then Commit quits |
| GET | `/` | the dashboard (`dashboard/dist`), with the pairing token embedded in the page |

Requests whose `Host` is not `127.0.0.1`/`localhost` are refused (protects against DNS-rebinding tricks).

## Pairing token
Created on first run and saved in the settings table. Show it with **menu bar → Settings → Extension pairing token…**
and paste it into the extension once. Requests without it get `401`.

## Categoriser modes
Menu bar → Settings → Website categories:

| Mode | What happens | Leaves the computer? |
|---|---|---|
| Off | everything is "Browsing" | no |
| Rules only | built-in domain table (`config/default.yaml` → `categoriser.domain_categories`) + your corrections | no |
| Local AI (Ollama) | rules, then the redacted title (and domain) go to Ollama on `127.0.0.1:11434` | no |
| My own API key | rules, then **only the redacted, shortened title** goes to your OpenAI-compatible endpoint | yes, with consent switch 4 |

Local mode needs consent switch 3; API mode needs switch 4 and a key (stored in the macOS Keychain).
Without them Commit falls back to "Rules only".

### Ollama
```bash
ollama pull llama3.2:3b        # the default model in config/default.yaml
# or use a model you already have: menu bar → Settings → Website categories → AI model…
```
`categoriser.local.extra_body` sends `reasoning_effort: none`, which stops "thinking" models (e.g. qwen3)
from reasoning first; with it they answer in under a second instead of minutes.
