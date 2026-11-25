# dashboard/ — Commit local dashboard (Phase 3)

React + Vite, plain CSS, no chart or router library. It runs **only on your computer**: the Commit app
serves the built files at `http://127.0.0.1:8765/` and the dashboard talks only to that local API.

## Build (once, and after changing the code)

```bash
cd dashboard
npm install
npm run build        # writes dashboard/dist/, which the Commit app serves
```

Then start Commit (`python -m agent.main` from the project root) and open the dashboard from the
menu bar (**Commit → Open dashboard**) or go to `http://127.0.0.1:8765/`.

### Editing the UI with live reload (optional)
```bash
COMMIT_TOKEN=<token from Settings → Chrome extension pairing> npm run dev
```
Vite serves the page on `http://localhost:5173` and forwards `/api` to the running Commit app with the token.

## Files

| File | Job |
|---|---|
| `index.html` | Page shell. The Commit app adds the pairing token as `<meta name="commit-token">` when serving it |
| `src/main.jsx` | Starts React |
| `src/App.jsx` | Sidebar + header ("Good morning, <name>" and "Download weekly report") + the current screen (chosen by `#/home`, `#/activity`, …) |
| `src/api.js` | The only code that calls the local API (adds the token, turns errors into friendly messages, downloads the PDF) |
| `src/format.js` | Minutes/time/date formatting, labels |
| `src/styles.css` | The whole design system (README 10.3) |
| `src/components/` | `Sidebar`, `StatCard`, `Charts` (bars, day columns, timeline), `AlertList` (with 👍/👎), `WeekNav`, `useLoad` (loads API data) |
| `src/pages/Home.jsx` | Stat cards, today's timeline, recent alerts |
| `src/pages/Activity.jsx` | Time by category, top apps, top websites (change a site's category), active time per day |
| `src/pages/WeeklyReport.jsx` | The weekly report as cards + Download PDF |
| `src/pages/Alerts.jsx` | All DND/break suggestions with reason, action and feedback |
| `src/pages/Settings.jsx` | Name, website categories (local AI / your API key, test connection), DND mode, check-ins, quiet hours, private websites, pairing token, calibration, retention, pause, delete all data, consent |

## Design
Warm grey page (`#E8E6E1`), white panels with large rounded corners, black pill for the active navigation item
and primary buttons, light grey pills for secondary buttons, and one yellow accent (`#F3F06A`) for the single
most important number (the load score). One font family (Inter if installed, otherwise the system font — no web
fonts are downloaded, so opening the dashboard contacts no outside server), two weights.

## Using your own API key (e.g. Groq)
Settings → Website categories → **My API key** (allow consent switch 4 when asked) → API address
`https://api.groq.com/openai/v1`, the exact model id from your provider, paste the key, keep
**Turn off model "thinking"** on for reasoning models such as Qwen 3, **Save model settings**, then **Test connection**.
The key is stored only in the macOS Keychain.
