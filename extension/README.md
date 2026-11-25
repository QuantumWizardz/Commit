# extension/ — Commit Chrome extension (Phase 2)

Plain JavaScript, Chrome Manifest V3. Reports the **active tab's domain, title and time** to the Commit app on
this computer (`http://127.0.0.1` only). The app uses the title to choose a category and then discards it.

| File | Job |
|---|---|
| `manifest.json` | Permissions: `tabs`, `idle`, `alarms`, `storage`; host access to `http://127.0.0.1/*` only; never runs in incognito |
| `common.js` | Shared helpers: what to send for a page (domain / Private / Other), private-list matching, calling the app |
| `background.js` | Service worker: tracks the active tab in the focused window, pauses when Chrome loses focus, the screen locks or you are idle; heartbeat on tab/title change and every 30 s |
| `popup.html` / `popup.js` | Connection status, "Don't track this site", the private list, pairing token and port |
| `welcome.html` | Opened on install: what is (and is never) collected, where it goes, how to exclude sites, how to pair |
| `style.css` | Shared look (README 10.3) |

## Install
1. Start the Commit app: `python -m agent.main` (from the project root, with the venv active).
2. Chrome → `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → choose this `extension/` folder.
3. The welcome page opens. In the Mac menu bar: **Commit → Settings → Extension pairing token…** → copy.
4. Click the Commit icon in Chrome's toolbar (pin it via the puzzle icon) → paste under **Pairing** → **Save**.
   The status turns green: **Connected**.

Website tracking must be allowed in Commit's consent choices (switch 2), otherwise the status shows
"website tracking off" and nothing is saved.

## What is sent

| Situation | Sent |
|---|---|
| Normal website | `{domain, title, seconds}` — domain only, never the full URL |
| Domain on the private list (or a subdomain of it) | `{category: "Private", seconds}` |
| `chrome://`, new tab, files, extension pages | `{category: "Other", seconds}` |
| Incognito | nothing (the extension does not run there); the app records Chrome time as "Miscellaneous" |

## Tests
`tests/test_extension.py` runs `common.js` in Node (skipped if Node is not installed).
