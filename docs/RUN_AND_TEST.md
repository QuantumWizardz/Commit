# Run and test Commit — step by step

This guide takes you from zero to seeing every feature of Phases 0–3 working on your Mac.
Tick the boxes as you go. Expected results are in *italics*.

Time needed: about 45 minutes for Parts 1–6 with **demo mode** (Part 4), otherwise most of a working day.

---

## Part 1 — One-time setup (5 min)

Open the project in VS Code and use its terminal (**Terminal → New Terminal**).

```bash
cd /Users/matrix/Desktop/Commit
source venv/bin/activate          # the prompt now starts with (venv)
pip install -r requirements.txt   # already done, quick check
```

- [ ] **Automated tests**
  ```bash
  pytest
  ```
  *`137 passed`.* These cover features, decisions, privacy rules, the server, the report and the extension logic.

- [ ] **Dashboard is built** (already done; repeat only after changing dashboard code)
  ```bash
  cd dashboard && npm install && npm run build && cd ..
  ```
  *`✓ built`; the folder `dashboard/dist/` exists.*

- [ ] **Model files exist** (from Phase 0)
  ```bash
  ls shared/models
  ```
  *`condition_model.pkl  features.json  load_model.pkl  model_card.md`.*

---

## Part 2 — macOS permissions and Shortcuts (10 min, once)

### 2a. Keyboard and mouse permission
Commit counts key presses and mouse activity, so macOS must allow the app that **runs Python**. If you start
Commit from VS Code's terminal, that app is **Visual Studio Code**; from Terminal.app it is **Terminal**.

1. System Settings → **Privacy & Security → Accessibility** → **+** → add *Visual Studio Code* → switch on.
2. System Settings → **Privacy & Security → Input Monitoring** → **+** → add *Visual Studio Code* → switch on.
3. **Quit VS Code completely (⌘Q) and open it again.** Permissions only apply after a restart.

### 2b. Do Not Disturb Shortcuts
Follow `docs/SHORTCUTS_SETUP.md` (two shortcuts: **Commit Focus On** and **Commit Focus Off**). Test them:
```bash
shortcuts run "Commit Focus On"     # the moon icon appears in the menu bar
shortcuts run "Commit Focus Off"    # it disappears
```
- [ ] *Both commands work.* (macOS may ask once whether VS Code may control Shortcuts → **Allow**.)

### 2c. Notifications
Commit's banners are shown through AppleScript, which macOS lists as **Script Editor**.
- [ ] System Settings → **Notifications → Script Editor** → *Allow notifications* is on.

---

## Part 3 — First launch (5 min)

```bash
cd /Users/matrix/Desktop/Commit && source venv/bin/activate
python -m agent.main
```
Keep this terminal open while Commit runs (log messages appear here). **To stop Commit:** menu bar → Commit → **Quit**.

The setup dialogs appear:

| Dialog | Choose |
|---|---|
| Welcome | *Read privacy policy* (optional), then **Continue** |
| 1. Activity counts (required) | **I agree** |
| 2. Website tracking | **Yes** (needed for the extension) |
| 3. Title categorisation on this computer | **Yes** (local AI with Ollama) |
| 4. Title categorisation with my own API key | **No** for now (choose Yes later if you use Groq — Part 6c) |
| 5. Load check-in pop-ups | **Yes** |
| macOS permissions | **Continue** (done in Part 2a) |
| Do Not Disturb setup | **Test Focus On** → OK, **Test Focus Off** → OK, then **Continue** |
| Urgent notifications | **OK** |

- [ ] *A banner says "Learning your normal pattern…".*
- [ ] *The menu bar shows* **Commit · Learning**.
- [ ] *No banner saying "Commit cannot see keyboard/mouse activity yet".* If you get it, redo Part 2a (and restart VS Code).

Useful while testing — watch the log in a second terminal:
```bash
tail -f ~/Library/Logs/Commit/commit.log
```

---

## Part 4 — Demo mode: see alerts in minutes, not hours (optional but recommended)

Normally Commit needs 15 active minutes to calibrate, then 15–20 more before it may suggest anything.
For a demo, use short timings. **Quit Commit first** (menu bar → Quit), then:

```bash
cp config/default.yaml config/default.yaml.backup
```

Open `config/default.yaml` and change only these values:

| Setting | Normal | Demo | Why |
|---|---|---|---|
| `calibration.active_minutes` | 15 | **3** | learn your baseline in 3 active minutes |
| `dnd.sustained_minutes` | 15 | **3** | look at the last 3 minutes |
| `dnd.sustained_fraction` | 0.5 | **-1** | demo only: always "under pressure", so the DND question appears |
| `dnd.duration_minutes` | 25 | **2** | DND turns itself off after 2 minutes |
| `dnd.ask_cooldown_minutes` | 60 | **2** | can ask again soon |
| `breaks.window_minutes` | 20 | **3** | |
| `breaks.load_threshold` | 70 | **0** | demo only: every minute counts as "high load" |
| `breaks.cooldown_minutes` | 45 | **2** | |
| `checkins.every_active_minutes` | 45 | **4** | check-in after 4 active minutes |

Start Commit again (`python -m agent.main`) and **keep using the computer normally** (an "active" minute
needs at least 5 seconds of typing/mouse use).

**Undo demo mode when you are done** (Part 8).

---

## Part 5 — Phase 1: the desktop agent

### 5a. Calibration and prediction
- [ ] *After 15 active minutes (demo: 3) a banner says* "Commit has learned your normal pattern and is now active."
- [ ] *The menu bar changes to* **Commit · Calm**, **Commit · Interrupted** or **Commit · Pressured**.
- [ ] Click the menu bar item: *"Current load score: NN" shows a number.*

### 5b. Do Not Disturb (demo: a few minutes after calibration)
- [ ] *Dialog: "You seem to be under pressure. Turn on Do Not Disturb for 25 minutes? Why: …"* — the reason explains which minutes and app switches triggered it.
- [ ] Click **Yes** → *the moon (DND) appears in the macOS menu bar.*
- [ ] *Dialog "Was this alert right?"* → click 👍 or 👎.
- [ ] *After the DND duration (demo: 2 min) a banner says "Do Not Disturb is off again."*
- [ ] Next time, try **Not now** (*no new DND question for the cooldown*) and **Always do this automatically** (*future DND turns on by itself with a banner; menu Settings shows "Do Not Disturb: always automatic" ticked*).

### 5c. Break suggestion
- [ ] *A list dialog: "You've been working hard for a while. Take a 5-minute break?"* with Take a break / Snooze 30 min / Snooze 60 min / Dismiss.
- [ ] Choose **Take a break** → *banner "Break started…", and "Break over" after 5 minutes.* Then answer 👍/👎.
- [ ] *Never two dialogs at once:* DND and break questions appear one after the other.

### 5d. Check-in
- [ ] *After 45 active minutes (demo: 4): "How mentally loaded do you feel right now? (1–5)".* Pick a number.

### 5e. Never interrupt
- [ ] Open **FaceTime** (or Zoom/Teams) and keep it in front: *no alerts or check-ins appear while it is in front.*
- [ ] (After Part 6) a **Google Meet** tab in front: *no alerts either.*

### 5f. Menu bar
- [ ] **Pause tracking** → *title "Commit · Paused"; nothing is counted.* **Resume** → *back to normal.*
- [ ] **Settings ▸** shows: DND ask/automatic, Load check-ins, Website categories, Extension pairing token…, Re-run calibration, Consent choices…, Do Not Disturb setup…, Privacy policy.
- [ ] **Settings → Re-run calibration** → *"Learning…" again.*

### 5g. What is stored (privacy check)
Type a made-up word somewhere, e.g. `pineapple42`, wait one minute, then:
```bash
grep -c "pineapple42" ~/Library/Application\ Support/Commit/commit.db ~/Library/Logs/Commit/commit.log
```
- [ ] *Both counts are `0`* — typed text is never stored (rule P1). Only counts are:
```bash
sqlite3 ~/Library/Application\ Support/Commit/commit.db \
  "SELECT datetime(ts,'unixepoch','localtime'), mode, app_category, condition, round(load_score) FROM minutes ORDER BY ts DESC LIMIT 10;"
```

---

## Part 6 — Phase 2: Chrome extension, categories, weekly report

### 6a. Install and pair the extension
1. Chrome → `chrome://extensions` → switch on **Developer mode** (top right) → **Load unpacked** → choose
   `/Users/matrix/Desktop/Commit/extension`.
2. - [ ] *A "Welcome to the Commit extension" page opens* explaining what is and is never collected.
3. Pin it: puzzle icon → pin **Commit — website time**.
4. Get the token: menu bar → Commit → **Settings → Extension pairing token…** (select the text, ⌘C)
   — or later in the dashboard: Settings → Chrome extension pairing → **Copy**.
5. Click the Commit icon in Chrome → paste into **Pairing token** → **Save**.
6. - [ ] *Status chip turns green: "Connected · Calm"* (or Learning/Interrupted/…).

### 6b. Website time and private sites
- [ ] Browse a few sites for a couple of minutes (Google Docs, GitHub, Wikipedia, YouTube).
- [ ] On your bank's site, click the Commit icon → **Don't track** → *"(private)" appears.*
- [ ] Check what was stored:
  ```bash
  sqlite3 ~/Library/Application\ Support/Commit/commit.db \
    "SELECT datetime(ts,'unixepoch','localtime'), domain, category, seconds FROM web_time ORDER BY ts DESC LIMIT 15;"
  ```
  *Rows have a domain + category + seconds only. Private time has an empty domain and category `Private`.
  No titles, no full URLs anywhere.*
- [ ] Open an **incognito window** and browse for a minute → *rows with empty domain and category `Miscellaneous`.*

### 6c. Title categorisation with AI (YouTube)
Choose **one** option (in the dashboard: Settings → Website categories, see Part 7):

- **Local (Ollama, nothing leaves the Mac):** mode **Local AI**, model name `qwen3.5:2b` (what you have installed)
  → **Save model settings** → **Test connection** → *"Connected. Test answer: Learning".*
- **Groq (your API key):** mode **My API key** → allow consent switch 4 → address `https://api.groq.com/openai/v1`,
  the exact model id from Groq, paste the key, keep **Turn off model "thinking"** on → **Save model settings** →
  **Test connection**. *The key is stored only in the macOS Keychain.*

Then:
- [ ] Watch a lecture on YouTube (e.g. "MIT 18.06 Linear Algebra Lecture 1") and a movie trailer, 1 minute each.
  ```bash
  sqlite3 ~/Library/Application\ Support/Commit/commit.db \
    "SELECT domain, category, sum(seconds) FROM web_time WHERE domain='youtube.com' GROUP BY category;"
  ```
  *youtube.com time is split into Learning and Entertainment.*
- [ ] Privacy check: pick a word from the video title, e.g. `Linear`:
  ```bash
  grep -c "Linear" ~/Library/Application\ Support/Commit/commit.db ~/Library/Logs/Commit/commit.log
  ```
  *`0` — titles are used for the category and then thrown away (rule P3).*

### 6d. Weekly report
- [ ] Menu bar → **Weekly report (PDF)** → *a PDF opens in Preview: screen/active time, average load (yellow),
  highlights, time by category, day by day, top apps and domains (Private as one total), suggestions.*
- [ ] Every Monday Commit also saves last week's PDF automatically to
  `~/Library/Application Support/Commit/reports/` and shows a banner.

---

## Part 7 — Phase 3: the dashboard

Menu bar → Commit → **Open dashboard** (or open `http://127.0.0.1:8765/` in Chrome).

### Home
- [ ] *"Good evening" (add your name in Settings), today's date, black "Download weekly report" button.*
- [ ] *Six cards: Active time, Focus (Neutral), Interrupted, Pressured, Breaks taken, and the **yellow** Current load score; small ↗/↘ trends vs yesterday.*
- [ ] *Today's timeline: green/amber/red bands across the day.*
- [ ] *Recent alerts with 👍/👎* — click one; *the button turns black (saved).*

### Activity
- [ ] *Time by category bars, active time per day, top apps, top websites.*
- [ ] Change a website's category in the dropdown → *"Saved — used from now on."* (future time on that site uses your category)
- [ ] **← Previous / Next →** switch weeks.

### Weekly report
- [ ] *The weekly report as cards and tables.* **Download PDF** → *the PDF downloads.*

### Alerts
- [ ] *Every DND/break suggestion with time, reason, what you did, and feedback buttons; totals at the top.*

### Settings (each change takes effect within a minute)
- [ ] **Your name** → Save → *Home greeting uses it.*
- [ ] **Website categories** → Off / Rules only / Local AI / My API key; model fields; **Test connection**.
- [ ] **Do Not Disturb** → Ask first / Always automatic *(the menu bar ticks follow).*
- [ ] **Load check-ins** → on/off and frequency.
- [ ] **Quiet hours** → add e.g. a period covering *now* → *no alerts or check-ins during it.* Remove it afterwards.
- [ ] **Private websites** → add/remove *(the extension's list updates within 30 seconds).*
- [ ] **Chrome extension pairing** → Show / Copy token.
- [ ] **Calibration** → progress, **Re-run calibration**.
- [ ] **Your data** → Pause switch *(sidebar shows "Commit is paused")*, retention days.
- [ ] **Consent choices** → switches 2–5 can be changed; activity counts is required.
- [ ] Sidebar state card → *"Commit is on · Calm" with a tracking switch.*

---

## Part 8 — Finish: undo demo mode, then a real test day

1. Quit Commit (menu bar → **Quit**).
2. Restore normal timings:
   ```bash
   mv config/default.yaml.backup config/default.yaml
   ```
3. Start Commit again and in the dashboard: **Settings → Calibration → Re-run calibration**
   (demo mode learned your baseline from only 3 minutes).
4. **Full-day test (Phase 1 "done when"):** leave Commit running during a normal workday.
   - [ ] *No crash; the terminal shows no tracebacks* (`grep -c Traceback ~/Library/Logs/Commit/commit.log` → 0).
   - [ ] Activity Monitor → search `Python` → *% CPU stays low (target < 2 % on average).*
   - [ ] *Alerts are rare (target ≤ 1 unhelpful alert per 2 hours); rate each one.*

### Delete all my data (last — this really deletes everything)
Dashboard **Settings → Your data → type DELETE → Delete everything** (or menu bar → Delete all my data).
- [ ] *Commit quits;* `ls ~/Library/Application\ Support/Commit/` *shows no `commit.db`; logs and reports are gone.*
  Starting Commit again shows the first-launch setup.

---

## Phase 0 (ML) — optional re-run

The trained models are already in `shared/models/`. To see or re-run the research:
- Open `ml/notebooks/01_eda.ipynb` … `04_own_data.ipynb` in VS Code, choose the **venv** Python kernel, **Run All**
  (Notebook 3 takes about 25 minutes).
- Results for the college report: `ml/reports/` (charts, tables) and `shared/models/model_card.md`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Menu bar stays "Learning" for a long time | Minutes only count when *active* (≥ 5 s of input). Check Part 2a permissions: the terminal shows "This process is not trusted!" if they are missing |
| "This process is not trusted!" in the terminal | Add VS Code (or Terminal) to Accessibility **and** Input Monitoring, quit VS Code with ⌘Q, reopen |
| No banners | System Settings → Notifications → Script Editor → allow |
| "Commit could not switch Do Not Disturb" | Shortcut names must be exactly `Commit Focus On` / `Commit Focus Off` (Part 2b) |
| Extension says "App not running" | Start `python -m agent.main`; port must be 8765 |
| Extension says "Wrong token" | Copy the token again (Part 6a step 4) and Save |
| Extension says "website tracking off" | Dashboard → Settings → Consent choices → turn on Website tracking |
| Dashboard says "not built yet" | `cd dashboard && npm install && npm run build`, reload |
| YouTube time is always "Browsing" | Categoriser mode must be Local AI or My API key, consent on, and **Test connection** must succeed |
| "Website tracking is off: port 8765 is already in use" | Another Commit is still running: `pkill -f agent.main`, then start again |
| Quit does not respond | In the terminal press Ctrl+C (twice if needed) |
