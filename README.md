# Commit

**Computer Interaction to Cognitive Load Prediction — a private, local-first focus and wellbeing app**

> **For Claude Code:** This README is the complete specification. Read the whole file before writing any code.
> Build **one phase at a time**, in the order given in [Section 6](#6-build-order-phases). At the end of each phase,
> stop, run the checks in that phase's "Done when" list, summarise what was built, and wait for the user to approve
> before starting the next phase. Do not skip phases, do not add features that are not in this file, and do not
> change any decision listed in [Section 2](#2-decisions-that-are-already-made-do-not-change). If something in
> this file is unclear or impossible, stop and ask the user instead of guessing.

---

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [Decisions that are already made (do not change)](#2-decisions-that-are-already-made-do-not-change)
3. [Code style rules (very important)](#3-code-style-rules-very-important)
4. [Privacy rules (never break these)](#4-privacy-rules-never-break-these)
5. [System architecture](#5-system-architecture)
6. [Build order (phases)](#6-build-order-phases)
7. [Phase 0 — ML research on SWELL-KW](#7-phase-0--ml-research-on-swell-kw)
8. [Phase 1 — Desktop agent, condition detection, DND, load + breaks, feedback](#8-phase-1--desktop-agent-condition-detection-dnd-load--breaks-feedback)
9. [Phase 2 — Chrome extension, title categoriser, weekly report](#9-phase-2--chrome-extension-title-categoriser-weekly-report)
10. [Phase 3 — Local dashboard (React)](#10-phase-3--local-dashboard-react)
11. [Phase 4 — Windows support](#11-phase-4--windows-support)
12. [Future extensions (do NOT build now)](#12-future-extensions-do-not-build-now)
13. [Database schema](#13-database-schema)
14. [Local server API](#14-local-server-api)
15. [Configuration](#15-configuration)
16. [Testing and evaluation](#16-testing-and-evaluation)
17. [User study protocol](#17-user-study-protocol)
18. [Folder structure](#18-folder-structure)
19. [Setup and run instructions](#19-setup-and-run-instructions)
20. [Known limitations (be honest about these)](#20-known-limitations-be-honest-about-these)
21. [Related research and products](#21-related-research-and-products)

---

## 1. What this project is

### 1.1 The college brief (this is the graded ML task)

> **Computer Interaction to Cognitive Load Prediction**
> Predict low versus high cognitive load using keyboard activity, mouse activity, application usage, interruptions,
> and working behaviour. Instead of detecting procrastination, classify whether someone is working under
> **neutral**, **interrupted**, or **time-pressure** conditions.
> ML type: Classification. Dataset: SWELL-KW (publicly available experimental data).

### 1.2 The product built on top of the ML

**Commit** is a desktop app (macOS first, then Windows) that runs quietly in the background and:

1. Logs **counts** of keyboard and mouse activity and which app is in front. It never records what is typed.
2. Uses an ML model to detect whether the user is working under **Neutral**, **Interruptions**, or **Time-pressure** conditions.
3. When the user is under pressure, **asks** to turn on Do Not Disturb so that only urgent (allowlisted) notifications get through. The user can choose "Always do this automatically".
4. Predicts a **cognitive load score**. When load stays high, it suggests a short break.
5. Asks the user for **feedback** on every alert (was it right or wrong?) and occasional load check-ins, and uses this to personalise the model.
6. Includes a **Chrome extension** that tracks time per website and reads the page/video title (e.g. a YouTube video title) so a **local LLM or the user's own API key** can sort it into a category. Users can mark websites as private.
7. Produces a **weekly report** (dashboard + PDF) of where time was spent, by **domains and categories only**.
8. Has a simple **local web dashboard** (React) that shows everything and holds all settings.

Everything runs on the user's own computer. No accounts, no cloud, no server owned by us.

### 1.3 What we are deliberately NOT using

- No heart rate, skin conductance, or body-posture sensors.
- No camera, no face recording, no screenshots.
- No storage of typed text, passwords, clipboard, URLs, or page titles.

---

## 2. Decisions that are already made (do not change)

| Area | Decision |
|---|---|
| Project name | **Commit** |
| Purpose | College ML project + working product |
| Platforms | **macOS first**, then Windows (Phase 4) |
| Browser | **Chrome only** (Manifest V3). Chromium browsers like Edge/Brave may work but are not targeted |
| Agent + ML language | **Python 3.11+** |
| Local server | **FastAPI**, listening on `127.0.0.1` only |
| Database | **SQLite**, one file on the user's machine |
| Dashboard | **React** (Vite), served locally, opened in the browser at `http://127.0.0.1:<port>` |
| Extension | **Plain JavaScript**, Chrome Manifest V3. No framework |
| Hosting | **Local only**. Nothing is deployed online |
| ML target 1 (main) | **Condition**: Neutral / Interruptions / Time-pressure (3 classes). Trained on **SWELL-KW + our own collected data** |
| ML target 2 | **Load**: low / high (plus a 0–100 score). Comes from model predictions **and** user self-ratings |
| Main ML dataset | SWELL-KW, **computer-interaction features only** |
| Evaluation | **Leave-one-subject-out (LOSO)** cross-validation as the headline result |
| Title categories | Extension reads the tab/video title → **local LLM (Ollama) or user's API key** → category |
| What is stored from the browser | **Domain + category + time only.** Titles are used for categorising and then thrown away |
| Private websites | User adds domains to a "Don't track" list. Their time is shown only as **"Private"**, with no domain name |
| Incognito | Counted as **"Miscellaneous"** time. No detail |
| Do Not Disturb | **Ask first**, with an **"Always do this automatically"** option. Urgent = the user's allowlist (set in the OS Focus settings) |
| Weekly report | Dashboard page **+ PDF export** |
| Deadlines & smart scheduling | **Future extension only.** Do not build now |
| UI style | Simple, clean, based on the design reference in [Section 10.3](#103-design-system) |
| Code style | Simple, readable, heavily commented. See [Section 3](#3-code-style-rules-very-important) |

---

## 3. Code style rules (very important)

The people maintaining this code are students. Every file must be easy to read and understand.

1. **Keep it simple.** Prefer plain functions and simple classes. No metaprogramming, no clever one-liners, no unnecessary design patterns, no deep inheritance.
2. **Comment everything that is not obvious.**
   - Every file starts with a short comment block saying what the file is for.
   - Every function has a docstring/comment explaining **what it does, what goes in, what comes out, and why it exists**.
   - Inside functions, add short comments before each logical step.
3. **Readable names.** `count_app_switches()` not `cas()`. `keys_per_minute` not `kpm`.
4. **Small functions.** One job per function. If a function is longer than ~40 lines, split it.
5. **No magic numbers.** Put thresholds (e.g. 15 minutes, 70 load score) in the config file ([Section 15](#15-configuration)) with a comment explaining them.
6. **Minimal dependencies.** Only add a library if it is clearly needed. List every dependency in `requirements.txt` / `package.json`.
7. **Handle errors gently.** If something fails (LLM offline, permission missing), log it, show a friendly message, and keep the app running. The logger must never crash because of another module.
8. **Type hints** in Python where they help readability.
9. **Same feature code everywhere.** The code that turns raw counts into ML features must live in **one shared module** and be used by both training (Phase 0) and the live app (Phase 1). Never write it twice.
10. **Tests** for core logic (features, redaction, rules, decision engine) using `pytest`.
11. **Each folder has its own short README** explaining what is inside and how to run it.

---

## 4. Privacy rules (never break these)

These are hard rules. Add automated tests that check them ([Section 16.3](#163-privacy-tests)).

| # | Rule |
|---|---|
| P1 | Never store which key was pressed or any typed character. The key is inspected in memory only to decide its type (normal / backspace-delete / shortcut) and then discarded |
| P2 | Never store passwords, clipboard, screenshots, camera, or microphone data |
| P3 | Never store page titles, video titles, or full URLs. Titles are used in memory to get a category, then discarded. Only **domain + category + duration** are stored |
| P4 | Private (user-excluded) domains are stored only as the category **"Private"**, with **no domain name** |
| P5 | Incognito time is stored only as **"Miscellaneous"** |
| P6 | All data stays in a local SQLite file on the user's computer. The local server listens on `127.0.0.1` only |
| P7 | Titles are sent to an external API **only if** the user selected "API key" mode **and** ticked a separate consent box. Before sending, titles are **redacted** (emails, links, long numbers removed) and shortened to 120 characters |
| P8 | The user's API key is stored in the OS keychain (`keyring` library), never in the database, config file, or logs |
| P9 | "Delete all my data" removes the database, cache, consent record, and API key |
| P10 | The user can pause tracking at any time from the menu bar and the dashboard |
| P11 | Data older than the retention period (default 30 days, configurable) is deleted automatically |
| P12 | Logs (debug files) must never contain titles, URLs, or key content |

### 4.1 Consent

On first launch, show a consent screen in plain language with **separate** switches:

1. Activity counts (keyboard/mouse counts, app names) — required to use the app
2. Website tracking through the Chrome extension
3. Title categorisation using a **local** model
4. Title categorisation using **my own API key** (off by default, with a warning that redacted titles will be sent to that provider)
5. Load check-in pop-ups

Store the consent choices, the consent version, and the date. Changing consent later is possible from Settings.

The privacy policy (`docs/PRIVACY.md`) must explain: what is collected, why, where it is stored, how long, who it is shared with (no one, except the optional API provider), how to withdraw consent, and how to delete data. Mention that it is designed with India's **Digital Personal Data Protection Act, 2023** principles in mind: specific consent for a stated purpose, data minimisation, and the right to erasure.

---

## 5. System architecture

All components run on the user's own computer.

```
┌────────────────────────────────────────────────────────────────────────┐
│                          USER'S COMPUTER                               │
│                                                                        │
│  ┌──────────────────────┐        ┌──────────────────────────────────┐  │
│  │ Chrome extension (JS) │──────▶│  Local server (FastAPI)          │  │
│  │ domain + title + time │  HTTP │  127.0.0.1 only                  │  │
│  └──────────────────────┘ +token │                                  │  │
│                                  │  ┌────────────────────────────┐  │  │
│  ┌──────────────────────┐        │  │ Title categoriser          │  │  │
│  │ React dashboard       │◀─────▶│  │ rules → cache → LLM        │──┼──┼─▶ Ollama (local)
│  │ (opens in browser)    │       │  └────────────────────────────┘  │  │   or user's API (optional)
│  └──────────────────────┘        │                                  │  │
│                                  │  ┌────────────────────────────┐  │  │
│  ┌──────────────────────┐        │  │ SQLite database            │  │  │
│  │ Desktop agent (Python)│──────▶│  └────────────────────────────┘  │  │
│  │ logger, ML, alerts,   │       └──────────────────────────────────┘  │
│  │ DND, menu-bar icon    │                                             │
│  └──────────────────────┘                                              │
└────────────────────────────────────────────────────────────────────────┘
```

| Component | Language | Job |
|---|---|---|
| **Desktop agent** | Python | Runs in the background. Logs counts, builds features, runs the models, shows alerts, turns DND on/off, shows the menu-bar icon |
| **Local server** | Python (FastAPI) | Small web server on `127.0.0.1`. Receives data from the extension, serves data to the dashboard, runs the title categoriser |
| **Database** | SQLite | Stores everything (see [Section 13](#13-database-schema)) |
| **Title categoriser** | Python | Turns a title into a category using rules, a cache, then a local LLM or the user's API key |
| **Chrome extension** | JavaScript | Reports the active tab's domain, title, and time to the local server, respecting the private list |
| **Dashboard** | React | Shows reports and holds settings. Talks only to the local server |

The agent and the server can run in the **same Python process** (the server in a background thread) to keep things simple. One command starts everything.

---

## 6. Build order (phases)

| Phase | What | Main features |
|---|---|---|
| **0** | ML research on SWELL-KW (Colab/Jupyter notebooks) | Condition model, load model, evaluation, report charts |
| **1** | Desktop agent (macOS) | Logging, condition detection, DND, load score + break suggestions, feedback, menu bar, consent |
| **2** | Chrome extension + weekly report | Website time, title categorisation (local LLM / API key), private sites, incognito, weekly report + PDF |
| **3** | Local dashboard (React) | All screens and settings |
| **4** | Windows support | Port the agent to Windows |
| Future | Not now | Deadlines, reminders, smart task scheduling |

**Rule for Claude Code:** finish each phase completely, run its checks, write a short summary, and wait for approval before moving on.

---

## 7. Phase 0 — ML research on SWELL-KW

This phase produces the graded ML results **and** the model files the app uses.

### 7.1 Dataset

- **Name:** SWELL Knowledge Work dataset (SWELL-KW), Koldijk et al., 2014.
- **Download:** https://doi.org/10.17026/dans-x55-69zp (DANS data archive). Licence: CC-BY-NC-SA-4.0 (academic use OK, not commercial).
- **Researcher page:** https://cs.ru.nl/~skoldijk/SWELL-KW/Dataset.html
- **Do NOT use** the popular "SWELL" dataset on Kaggle. As far as we know, that one is the heart-rate (HRV) version, which we are excluding.
- The user downloads the files manually and places them in `ml/data/raw/`. Claude Code should not try to download them.
- **Use only the computer-interaction feature file** (per-minute features from the uLog key-logger). Ignore the facial-expression, posture, and physiology files.
- **Also look for the subjective questionnaire data** (self-rated mental effort, task load, perceived stress per participant per condition). This is needed for the load target. Join it to the per-minute rows by participant ID and condition.

**Known facts about SWELL-KW** (from Koldijk et al.):
- 25 participants, about 3 hours each, doing typical office work (writing reports, preparing presentations, reading e-mail, searching for information).
- Three conditions: **Neutral** (N), **Interruptions** (I, e-mails arriving during work), **Time pressure** (T, less time than neutral). There is also a relax phase (R).
- Features are aggregated **per minute**.
- In the original study, computer-interaction features alone scored only **65.51% accuracy against a 61.76% majority baseline** (neutral vs stressed, random 10-fold CV), and an all-sensor model dropped to **58.89% average accuracy** on unseen people. Our job is to improve the computer-only result honestly using better features and personalisation.

**Important:** first open the CSV and **print the real column names**. Do not assume column names. Document the actual columns in `ml/README.md`.

### 7.2 Notebook 1 — `01_eda.ipynb` (exploration)

1. Load the computer-interaction file.
2. Show: number of rows, participants, rows per participant, rows per condition.
3. Check missing values and duplicates.
4. Plot each feature by condition (box plots).
5. Run a simple statistical test per feature (e.g. Kruskal-Wallis) to see which features differ across N / I / T.
6. Save clean data to `ml/data/processed/swell_clean.csv`.

### 7.3 Notebook 2 — `02_features.ipynb` (feature engineering)

All feature functions live in **`shared/features.py`** so the live app can reuse them.

1. **Cleaning:** keep N, I, T rows. Keep R only if needed as an extra experiment. Handle missing minutes.
2. **Feature parity:** keep only features that our own desktop agent can also log (see the feature list in [Section 8.3](#83-module-m13--feature-builder)). Write a mapping table `SWELL column → our feature name` in `ml/README.md`.
3. **Rate and ratio features:** e.g. error-key ratio = error keys ÷ total keys; shortcut ratio; keyboard-to-mouse ratio; share of idle minutes.
4. **Rolling features:** 3-minute and 5-minute rolling mean and standard deviation per participant, in time order.
5. **Per-person normalisation:** z-score each feature using that participant's own **neutral-condition** mean and standard deviation. (In the live app this baseline comes from a calibration period.)
6. **Labels:**
   - `condition` = N / I / T (3-class), plus a binary version `stressed` = I or T vs N.
   - `load` = low / high from the self-rated **mental effort** score (split at each participant's median, or at the overall median; compare both). If the questionnaire file cannot be found or joined, fall back to the proxy N = low, I/T = high, and clearly say so in the report.

### 7.4 Notebook 3 — `03_models.ipynb` (training and evaluation)

1. **Baselines:** majority class; Logistic Regression.
2. **Models:** Random Forest, LightGBM (or XGBoost), SVM (RBF).
3. **Evaluation — LOSO:** `LeaveOneGroupOut` with participant ID as the group. Train on 24 people, test on 1, repeat 25 times.
4. **Tuning:** hyperparameters are tuned **inside the training folds only** (nested CV or `GroupKFold` inside each outer fold). Never tune on the test participant.
5. **Metrics:** macro-F1 (headline), balanced accuracy, confusion matrix, per-participant scores, mean ± standard deviation across the 25 folds. Always show the majority baseline next to the results.
6. **Show the inflation problem:** also report random 10-fold CV results next to LOSO, to show how random splits overestimate performance.
7. **Ablation studies:**
   - keyboard-only vs mouse-only vs app-only features
   - with vs without app-switch / e-mail-related features (to check whether "interruptions" is just "e-mail opened")
   - raw vs per-person normalised features
   - 1-min vs 3-min vs 5-min windows
8. **Explainability:** SHAP values for the best model (summary plot + per-class plots).
9. **Load model:** same process for the low/high load target.
10. **Export** (to `shared/models/`):
    - `condition_model.pkl`
    - `load_model.pkl`
    - `features.json` — exact feature names and order used by the models
    - `model_card.md` — dataset, features, metrics, limitations

### 7.5 Notebook 4 — `04_own_data.ipynb` (after the user study)

Used after we collect our own data ([Section 17](#17-user-study-protocol)):
1. Load our own per-minute data exported from the app.
2. **Cross-dataset test:** test the SWELL-trained model on our participants, with and without personal calibration.
3. **Retrain** the condition model on SWELL + our data (participants kept separate for LOSO).
4. **Personal models** for the two developers' long recordings, using a **time-blocked split** (train on earlier days, test on later days).
5. Compare: generic vs personalised.

### 7.6 Phase 0 — Done when

- [ ] All four notebooks run top-to-bottom without errors (notebook 4 can wait for study data).
- [ ] `shared/features.py` exists and has tests.
- [ ] LOSO results table, confusion matrices, ablation table, and SHAP plots are saved to `ml/reports/`.
- [ ] Model files + `features.json` + `model_card.md` are in `shared/models/`.

---

## 8. Phase 1 — Desktop agent, condition detection, DND, load + breaks, feedback

**Platform:** macOS only in this phase.

### 8.1 Module M1.1 — Consent and onboarding

- First-launch window (simple; a native dialog sequence or a small local web page is fine).
- Shows the consent switches from [Section 4.1](#41-consent).
- Guides the user through macOS permissions, each with a one-line "why we need this":
  - **Accessibility** and **Input Monitoring** (needed for keyboard/mouse counting)
  - **Automation** (needed later to run Shortcuts for DND)
- Guides the user to create **two macOS Shortcuts** (one-time setup):
  - `Commit Focus On` → action "Set Focus: Do Not Disturb → On"
  - `Commit Focus Off` → action "Set Focus: Do Not Disturb → Off"
  - Include clear step-by-step text with a "Test" button that runs each shortcut.
- Explains that **urgent = allowlist**: the user chooses which people/apps can still notify them in macOS **System Settings → Focus → Do Not Disturb → Allowed people/apps**.
- Runs the **calibration period** (see M1.4).

### 8.2 Module M1.2 — Input logger

Library: `pynput`.

Counts per minute (never stores key identity, see P1):

| Feature | Meaning |
|---|---|
| `keystrokes` | number of key presses (excluding modifier keys alone) |
| `error_keys` | backspace + delete presses |
| `shortcut_keys` | key presses while Cmd/Ctrl/Alt is held |
| `pause_count` | gaps between input events longer than 2 seconds (and shorter than 60 seconds) |
| `pause_total_seconds` | total length of those gaps |
| `active_seconds` | number of seconds in the minute with any input |
| `clicks` | mouse button presses |
| `scrolls` | scroll events |
| `mouse_distance` | total pointer distance in pixels |

Later improvement (optional, end of Phase 1): mouse speed and direction-change counts, inspired by Naegelin et al. (2023).

### 8.3 Module M1.3 — App tracker + feature builder

**App tracker** (every 5 seconds):
- Name of the frontmost app (macOS: `NSWorkspace` via `pyobjc`).
- Count of app switches per minute.
- Map app names to categories using an editable table in config (e.g. `Visual Studio Code → Work`, `Slack → Communication`, `Spotify → Entertainment`).
- If the frontmost app is Chrome, the extension provides site detail (Phase 2). If Chrome is frontmost but the extension sends nothing (e.g. incognito), record **"Miscellaneous"**.

**Feature builder** (`shared/features.py`, the same code as Phase 0):
- Every 60 seconds, takes the counts and app data and builds the **same features the model was trained on**, in the order from `features.json`.
- Adds rolling 3/5-minute features.
- Normalises using the user's personal baseline.

**Calibration (M1.4 part):**
- The first **15 active minutes** of normal work after install are the calibration period.
- During calibration, no predictions or alerts. Show "Learning your normal pattern…" in the menu bar.
- Save each feature's mean and standard deviation as the user's baseline. The user can re-run calibration from Settings.

**Activity mode** (simple rules):
| Mode | Rule |
|---|---|
| Idle | fewer than 5 active seconds in the minute |
| Passive | few inputs (< 20 active seconds) while a video/reading category is in front |
| Active | everything else |

Predictions and alerts run only in **Active** mode.

### 8.4 Module M1.5 — Condition detector

- Every minute (Active mode only), load `condition_model.pkl` and predict N / I / T with probabilities.
- **Smoothing:** the shown condition is the most common prediction over the last **5 minutes**, so one noisy minute does not change anything.
- Save the prediction to the database.

### 8.5 Module M1.6 — Load scorer

- Every minute (Active mode), compute a **load score from 0 to 100**:
  - Base: `load_model.pkl` probability of "high load" × 100.
  - Adjust upward when the condition is Interruptions or Time-pressure (small, configurable weight).
- **Personal calibration from self-ratings:** after the user has given at least **20 check-in ratings**, fit a small calibration (e.g. logistic regression from model score to the user's rating) so the score matches how *this* user feels. Refit weekly.
- Save the score to the database.

### 8.6 Module M1.7 — DND controller

| When | What happens |
|---|---|
| Interruptions or Time-pressure condition sustained for **15+ minutes** (most of the last 15 active minutes) | Pop-up: *"You seem to be under pressure. Turn on Do Not Disturb for 25 minutes?"* Buttons: **Yes** / **Not now** / **Always do this automatically** |
| Yes, or auto mode is on | Run the `Commit Focus On` shortcut: `shortcuts run "Commit Focus On"` |
| After **25 minutes** | Run `Commit Focus Off`, and notify: *"Do Not Disturb is off again."* |
| Not now | Don't ask again for the cooldown period |

- Urgent notifications are handled by the user's macOS Focus allowlist, not by our app.
- If the shortcuts are missing or fail, show a friendly message with a link to the setup guide. Never crash.

### 8.7 Module M1.8 — Break suggester

- If the load score is above **70** for most (**60%+**) of the last **20 active minutes**: pop-up *"You've been working hard for a while. Take a 5-minute break?"* Buttons: **Take a break** / **Snooze 30 min** / **Snooze 60 min** / **Dismiss**.
- **Cooldown:** at most one break suggestion every **45 minutes**.
- If the pattern looks like interruptions (many app switches, lots of communication apps), prefer the DND suggestion. If it looks like sustained time pressure (heavy typing, few pauses, few switches), prefer the break suggestion. Never show both at once.
- **Never interrupt** during video calls (frontmost app is a call app such as Zoom, Microsoft Teams, FaceTime, or a Google Meet tab) or during quiet hours set by the user.
- Optional "Take a break" screen: a simple timer with a breathing guide.

### 8.8 Module M1.9 — Feedback and check-ins

- **Every alert** (DND or break) is followed by: *"Was this alert right?"* **👍 / 👎**. Save the answer.
- **Check-in** (optional, if consented) every **45 minutes** of active work: *"How mentally loaded do you feel right now?"* **1 2 3 4 5**. Save the answer.
- These are the **labels** used for personal calibration (M1.6) and for measuring live accuracy in the report.

### 8.9 Module M1.10 — Menu-bar icon

Library: `rumps` (macOS menu-bar apps).

- Icon/text showing the current state: **Calm / Interrupted / Pressured / Paused / Learning**.
- Menu items: Current load score · Pause tracking · Resume · Open dashboard · Settings · Delete all my data · Quit.

### 8.10 Notifications and dialogs (macOS)

- Use `osascript` for notifications and simple button dialogs (`display notification`, `display dialog`, `choose from list`), or a small native library if simpler.
- Every dialog must time out after ~30 seconds without blocking the agent.

### 8.11 Phase 1 — Done when

- [ ] One command starts the agent; it runs for a full workday without crashing.
- [ ] Consent, permissions, and Shortcuts setup work for a new user.
- [ ] Calibration completes and saves a baseline.
- [ ] Condition and load are predicted every active minute and saved.
- [ ] DND pop-up appears under sustained pressure; Yes/Auto turns DND on and off.
- [ ] Break suggestion appears under sustained high load, with cooldown and snooze working.
- [ ] Feedback 👍/👎 and check-ins are saved.
- [ ] Menu bar shows the state; Pause and Delete all data work.
- [ ] Privacy tests pass ([Section 16.3](#163-privacy-tests)).
- [ ] CPU usage stays low (target < 2% average).

---

## 9. Phase 2 — Chrome extension, title categoriser, weekly report

### 9.1 Module M2.1 — Extension install and privacy page

- Chrome **Manifest V3**, plain JavaScript.
- On install, open a simple page that clearly explains:
  - What is collected: the website **domain**, the **page/video title** (used only to choose a category, then discarded), and **time spent**.
  - What is never collected: page content, form inputs, passwords, full URLs.
  - Where it goes: only to the Commit app on this computer (`127.0.0.1`).
  - How to exclude websites.
- A **"Don't track these websites"** list where the user adds domains (e.g. `bank.com`). Editable in the extension popup and in the dashboard.

### 9.2 Module M2.2 — Tab tracker

- Track only the **active tab in the focused window**. Pause when the window loses focus, the screen is locked, or the user is idle (`chrome.idle`).
- Every time the active tab or its title changes, and every 30 seconds while it stays the same, send a "heartbeat" to the local server.

| Situation | What the extension sends |
|---|---|
| Normal website | `domain`, `title`, `seconds` |
| Domain is on the private list | `category: "Private"`, `seconds` (no domain, no title) |
| Incognito | Nothing. The extension does not run in incognito by default. The agent sees Chrome in front with no heartbeat and records **"Miscellaneous"** |
| Chrome internal pages (`chrome://`, new tab) | `category: "Other"`, `seconds` |

- **Pairing:** the local server generates a random token on first run, shown in the dashboard. The user pastes it into the extension once. Every request includes the token, and the server rejects requests without it.
- `host_permissions` only for `http://127.0.0.1/*`. No other network access.

### 9.3 Module M2.3 — Title categoriser (in the local server)

Categories (fixed list, editable names in config):
`Work`, `Learning`, `Communication`, `Entertainment`, `Social media`, `Browsing`, `Other`
(plus the special buckets `Private` and `Miscellaneous`).

Steps for each (domain, title):

| Step | What happens | Data leaves the computer? |
|---|---|---|
| 1. Domain rules | Clear domains map directly (e.g. `netflix.com → Entertainment`, `docs.google.com → Work`, `mail.google.com → Communication`, `instagram.com → Social media`) | No |
| 2. Ambiguous domains | For domains like `youtube.com`, the **video title** decides (e.g. "Contract Law Lecture 5" → Learning; a movie trailer → Entertainment) | — |
| 3. Cache | Look up a **salted hash** of `domain + title`. If seen before, reuse the category | No |
| 4. Redaction | Remove e-mail addresses, links, and numbers with 4+ digits; cut to 120 characters | No |
| 5a. Local LLM (default) | Send the redacted title to **Ollama** on `http://127.0.0.1:11434` using its OpenAI-compatible endpoint (`/v1/chat/completions`). Suggested model: a small one such as `llama3.2:3b` | No |
| 5b. API key (optional) | Send the redacted title to the user's chosen **OpenAI-compatible** endpoint with their API key (from the keychain). Only if the user consented (P7) | **Yes**, the redacted title only |
| 6. Save | Store **domain + category + seconds**. Store the hash → category in the cache. **Discard the title** | No |

- LLM prompt: ask for **exactly one category word** from the list; temperature 0; parse the answer safely; if the answer is not in the list, use `Browsing`.
- **Rate limit:** at most 120 LLM calls per hour (configurable).
- **Offline fallback:** if the LLM is unavailable, use `Browsing` and try again next time the title appears. Never block.
- **User correction:** in the dashboard, the user can change a domain's category; this becomes a rule for the future.
- **Settings:** Categoriser mode = Off / Rules only / Local LLM / API key. Fields: model name, base URL, API key (saved to keychain), "Test connection" button.

### 9.4 Module M2.4 — Weekly report

Generated every Monday for the previous 7 days, and on demand.

Contents (**domains and categories only, never titles**):
1. Total screen time and active time per day.
2. Time by category (Work, Learning, Communication, Entertainment, Social media, Browsing, Other, Private, Miscellaneous).
3. Top apps and top domains (private time shown as one "Private" total).
4. Condition summary: time spent Neutral / Interrupted / Pressured, by day and by hour of day.
5. Average load score by day.
6. Alerts: number of DND and break suggestions, how many accepted, how many rated 👍.
7. One or two plain-language highlights (e.g. "Most interruptions happened on Tuesday afternoon").

**PDF export:** use `reportlab` (simple tables and bar charts). The PDF matches the dashboard style (see [Section 10.3](#103-design-system)).

### 9.5 Phase 2 — Done when

- [ ] Extension installs, shows the privacy page, pairs with the app.
- [ ] Domain time is recorded; private domains show only as "Private"; incognito shows as "Miscellaneous".
- [ ] YouTube video titles are categorised by the local LLM; API-key mode works with consent.
- [ ] No titles are stored anywhere (privacy tests pass).
- [ ] Weekly report data and PDF are generated correctly.

---

## 10. Phase 3 — Local dashboard (React)

### 10.1 Technical setup

- React + Vite. Plain CSS or CSS modules (no heavy UI framework needed).
- Small chart library only if necessary (e.g. Recharts). Keep charts simple.
- The built dashboard is served by the FastAPI server, so the user opens `http://127.0.0.1:<port>`.
- Talks only to the local server API ([Section 14](#14-local-server-api)).

### 10.2 Screens

**Left sidebar:** logo "Commit", navigation (Home, Activity, Weekly report, Alerts, Settings), current state card at the bottom (e.g. "Commit is on · Calm" with a pause toggle).

| Screen | Contents |
|---|---|
| **Home** | Greeting ("Good morning, <name>") · row of stat cards: Active time today, Focus (Neutral) time, Interrupted time, Pressured time, Breaks taken, Current load score (**yellow highlight card**) · Today's timeline (condition bands across the day) · Recent alerts with 👍/👎 buttons |
| **Activity** | Time by category (simple bars) · Top apps · Top domains · Day-by-day bars for the week · Edit a domain's category |
| **Weekly report** | The Phase 2 report as cards · **Download PDF** button |
| **Alerts** | List of all DND and break suggestions with time, reason (e.g. "App switches 3× your normal"), user action, and feedback |
| **Settings** | Name · Categoriser mode (Off / Rules / Local LLM / API key) + model, URL, key, test button · DND mode (Ask / Always auto) · Check-in frequency · Quiet hours · Private websites list · Extension pairing token · Re-run calibration · Data retention days · Pause tracking · **Delete all my data** · Consent choices |

### 10.3 Design system

Based on the user's design reference (a clean, light SaaS dashboard). Keep it **very simple**.

| Element | Style |
|---|---|
| Page background | Warm light grey (around `#E8E6E1`) |
| Sidebar | White panel with large rounded corners, on the grey background |
| Cards | White, large rounded corners (~20–24px), no heavy shadows, generous padding |
| Active nav item / primary buttons | **Black** pill shape with white text |
| Accent | **One** yellow (around `#F3F06A`) used only for the single most important number/card and small tags |
| Secondary buttons | Light grey pill buttons |
| Numbers | Large and bold; small grey label above; small trend arrow (↗ / ↘) with change |
| Status chips | Small rounded tags: Neutral (light green dot), Interrupted (amber dot), Pressured (red dot) |
| Typography | One clean sans-serif (e.g. Inter); two weights only (regular and semibold) |
| Charts | Flat, minimal. Hatched or plain bars; no 3D, no gradients |
| Layout | Sidebar left; header with greeting and a "Download weekly report" black button on the right; stat-card row; then 2–3 content cards per row |

Accessibility: good contrast, keyboard navigable, readable font sizes (body ≥ 14px).

### 10.4 Phase 3 — Done when

- [ ] All five screens work with real data from the local server.
- [ ] All settings save and take effect.
- [ ] Delete all data and Pause work from the dashboard.
- [ ] The design matches Section 10.3.

---

## 11. Phase 4 — Windows support

Port the agent to Windows after macOS works.

| Part | macOS | Windows |
|---|---|---|
| Keyboard/mouse | `pynput` | `pynput` |
| Frontmost app | `NSWorkspace` (`pyobjc`) | `win32gui` + `psutil` |
| Menu-bar / tray icon | `rumps` | `pystray` |
| Notifications / dialogs | `osascript` | a toast library (e.g. `winotify`) + simple dialogs |
| Do Not Disturb | Shortcuts (`shortcuts run`) | **Needs research.** Windows does not offer a simple public way for apps to switch Focus/DND on and off. Fallback: notify the user and ask them to turn it on themselves |
| Keychain | `keyring` | `keyring` (Windows Credential Manager) |

Put all OS-specific code in `agent/platform/macos.py` and `agent/platform/windows.py` behind the same small set of functions (e.g. `get_frontmost_app()`, `set_dnd(on)`, `notify()`, `ask()`), so the rest of the code does not change.

---

## 12. Future extensions (do NOT build now)

Only add placeholders/notes; no code.

1. **Deadlines and reminders:** manual entry of deadlines with effort estimate and priority; reminders "N days before" or at a specific time.
2. **Smart task scheduling:** suggest the best day/time for a task using deadlines + effort + priority + past busy patterns (e.g. "You're usually free on Thursday; Monday has an important meeting and the weekend looks busy → do this on Thursday").
3. Calendar import (e.g. Google Calendar, read-only).
4. More browsers (Firefox, Safari).

---

## 13. Database schema

SQLite, file at the OS app-data folder (`platformdirs.user_data_dir("Commit")`).

```sql
-- One row per minute of activity (counts and predictions only)
CREATE TABLE minutes (
    ts               INTEGER PRIMARY KEY,  -- unix time, start of the minute
    mode             TEXT,                 -- active / passive / idle / paused
    app_category     TEXT,                 -- main category this minute
    features_json    TEXT,                 -- the feature values used by the model
    condition        TEXT,                 -- neutral / interruptions / time_pressure (smoothed)
    condition_probs  TEXT,                 -- JSON of class probabilities
    load_score       REAL                  -- 0 to 100
);

-- Time per app (no window titles)
CREATE TABLE app_time (
    ts INTEGER, app_name TEXT, category TEXT, seconds INTEGER
);

-- Time per website (domain + category only; Private/Misc have domain NULL)
CREATE TABLE web_time (
    ts INTEGER, domain TEXT, category TEXT, seconds INTEGER
);

-- Title categoriser cache (salted hash only, never the title)
CREATE TABLE title_cache (
    hash TEXT PRIMARY KEY, category TEXT, created_at INTEGER
);

-- User rules: domain -> category, and private domains
CREATE TABLE domain_rules (domain TEXT PRIMARY KEY, category TEXT);
CREATE TABLE private_domains (domain TEXT PRIMARY KEY);

-- Alerts shown to the user and what they did
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER,
    kind TEXT,          -- dnd / break
    reason TEXT,        -- short explanation shown to the user
    action TEXT,        -- yes / not_now / auto / snooze_30 / snooze_60 / dismiss
    feedback TEXT       -- up / down / NULL
);

-- Self-rated load check-ins
CREATE TABLE checkins (ts INTEGER PRIMARY KEY, rating INTEGER);  -- 1 to 5

-- Settings, consent, baseline, pairing token (JSON values)
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
```

---

## 14. Local server API

FastAPI on `127.0.0.1` (default port `8765`). Extension requests must include the pairing token header `X-Commit-Token`. The dashboard is served from the same origin.

| Method | Path | Used by | Purpose |
|---|---|---|---|
| POST | `/api/web/heartbeat` | Extension | `{domain?, title?, category?, seconds}` → categorise and store (title discarded) |
| GET | `/api/private-domains` | Extension, Dashboard | List private domains |
| POST / DELETE | `/api/private-domains` | Extension, Dashboard | Add / remove a private domain |
| GET | `/api/today` | Dashboard | Stat cards + today's timeline |
| GET | `/api/week?start=YYYY-MM-DD` | Dashboard | Weekly report data |
| GET | `/api/report/pdf?start=YYYY-MM-DD` | Dashboard | Download the weekly PDF |
| GET | `/api/activity` | Dashboard | Time by category, apps, domains |
| PUT | `/api/domain-rules` | Dashboard | Change a domain's category |
| GET | `/api/alerts` | Dashboard | Alert history |
| POST | `/api/alerts/{id}/feedback` | Dashboard | 👍 / 👎 |
| GET / PUT | `/api/settings` | Dashboard | Read / update settings |
| POST | `/api/llm/test` | Dashboard | Test the LLM connection |
| POST | `/api/calibration/restart` | Dashboard | Re-run calibration |
| POST | `/api/pause` / `/api/resume` | Dashboard | Pause / resume tracking |
| DELETE | `/api/data` | Dashboard | Delete all data (P9) |
| GET | `/api/status` | Dashboard, Extension | Is the app running, current state |

---

## 15. Configuration

`config/default.yaml` (user changes are saved in the `settings` table and override these). Every value has a comment.

```yaml
server:
  port: 8765                    # local server port (127.0.0.1 only)

logging:
  pause_threshold_seconds: 2    # input gap longer than this counts as a pause
  app_sample_seconds: 5         # how often we check the frontmost app

calibration:
  active_minutes: 15            # minutes of normal work used to learn the personal baseline

detection:
  smoothing_minutes: 5          # condition = most common prediction over this window

dnd:
  sustained_minutes: 15         # pressure must last this long before asking
  duration_minutes: 25          # how long DND stays on
  mode: ask                     # ask | auto
  shortcut_on: "Commit Focus On"
  shortcut_off: "Commit Focus Off"

breaks:
  load_threshold: 70            # load score considered "high"
  window_minutes: 20            # look at the last N active minutes
  high_fraction: 0.6            # share of minutes that must be high
  cooldown_minutes: 45          # minimum time between break suggestions
  break_minutes: 5              # suggested break length

checkins:
  enabled: true
  every_active_minutes: 45
  min_ratings_for_personal_model: 20

quiet:
  call_apps: ["zoom.us", "Microsoft Teams", "FaceTime"]   # never interrupt during these
  call_domains: ["meet.google.com"]
  quiet_hours: []               # e.g. ["22:00-08:00"]

categoriser:
  mode: local                   # off | rules | local | api
  categories: [Work, Learning, Communication, Entertainment, Social media, Browsing, Other]
  ambiguous_domains: [youtube.com, vimeo.com]
  max_llm_calls_per_hour: 120
  title_max_chars: 120
  local:
    base_url: "http://127.0.0.1:11434/v1"
    model: "llama3.2:3b"
  api:
    base_url: "https://api.openai.com/v1"   # any OpenAI-compatible endpoint
    model: ""                                # user fills in

app_categories:                 # frontmost app -> category (editable)
  "Visual Studio Code": Work
  "Microsoft Word": Work
  "Notion": Work
  "Slack": Communication
  "Mail": Communication
  "WhatsApp": Communication
  "Spotify": Entertainment

data:
  retention_days: 30
```

---

## 16. Testing and evaluation

### 16.1 Unit tests (`pytest`)
- Feature calculations (`shared/features.py`): known inputs → expected outputs.
- Redaction: e-mails, links, long numbers are removed.
- Domain rules and categoriser fallback behaviour.
- Decision engine: DND and break rules, cooldowns, snooze, quiet hours, call apps.
- Smoothing of predictions.

### 16.2 Integration tests
- 10-minute pilot run: logger → features → model → database → API → dashboard.
- Extension → server → database round trip with the pairing token.

### 16.3 Privacy tests
- After a test session with typing, search the whole database and log files for the typed text: **must not be found** (P1).
- Visit test pages with known titles: titles **must not appear** in the database or logs (P3).
- Private domain: its name **must not appear** anywhere (P4).
- API mode: inspect the outgoing request body: only the **redacted, shortened** title is sent (P7).
- API key is not in the database, config, or logs (P8).
- "Delete all my data" leaves no database, cache, consent record, or keychain entry (P9).

### 16.4 ML evaluation
- SWELL LOSO results vs majority baseline (Phase 0).
- Random CV vs LOSO comparison (shows the inflation).
- Ablations and SHAP.
- Cross-dataset test on our study participants; generic vs personalised.

### 16.5 Live product evaluation
- Share of alerts rated 👍.
- False-alarm rate (target ≤ 1 unhelpful alert per 2 hours).
- Correlation between load score and check-in ratings.
- CPU, memory, and battery impact over a full day.
- Usability questionnaire for study participants (e.g. System Usability Scale) and a short trust/privacy questionnaire.

---

## 17. User study protocol

Needed for our own data and for testing on new people.

### 17.1 Participants
- **4–5 participants**, about **3–4 hours** each → **independent test set** (never used for training or tuning in the headline results).
- **2 developers**, about **8–10 hours** each, **split across 2–3 days** (not one long sitting) → personal-model case study and long-run behaviour. Their data is **not** used as evidence that the model generalises, because they know the hypotheses.
- Everyone, including the developers, signs a consent form. Data is stored under IDs (P1–P5, D1–D2), not names.

### 17.2 Participant session (≈ 3.5 hours)

| Time | Block | Label |
|---|---|---|
| 0:00–0:15 | Setup, consent, calibration (normal light work) | Baseline |
| 0:15–1:00 | Block A | Condition + self-rating after |
| 1:00–1:10 | Break | — |
| 1:10–1:55 | Block B | Condition + self-rating |
| 1:55–2:05 | Break | — |
| 2:05–2:50 | Block C | Condition + self-rating |
| 2:50–3:20 | Passive block: watching a video (lecture or entertainment) | Self-rating; tests the categoriser and passive mode |
| 3:20–3:30 | Exit questionnaire (usability, trust, privacy) | — |

- Blocks A/B/C are **Neutral**, **Interruptions**, **Time-pressure**, in a **different random order for each participant**.
  - **Neutral:** write a short report/essay, no deadline.
  - **Interruptions:** the same type of task, but the researcher sends chat/e-mail messages every few minutes that need a reply.
  - **Time-pressure:** a similar task with a visible countdown and a tight deadline.
- Self-rating after each block: mental effort (and optionally a NASA-TLX form).

### 17.3 Developer sessions
- Normal real work across 2–3 days, with the app's check-in pop-ups every ~45 minutes (1–5 rating) as labels.

### 17.4 Data handling
- Only the per-minute counts CSV (exported from the app, no titles) leaves each laptop.
- Run a **10-minute pilot** on one person before the real sessions to catch bugs.
- The same app version is used for everyone.

---

## 18. Folder structure

```
commit/
├── README.md                    # this file
├── docs/
│   ├── PRIVACY.md               # privacy policy (plain language)
│   ├── CONSENT_FORM.md          # user-study consent form
│   ├── SHORTCUTS_SETUP.md       # how to create the macOS DND shortcuts
│   └── ARCHITECTURE.md          # short architecture notes and diagrams
├── config/
│   └── default.yaml
├── shared/                      # code used by BOTH ml/ and agent/
│   ├── features.py              # the one and only feature-building code
│   └── models/                  # exported .pkl files, features.json, model_card.md
├── ml/
│   ├── README.md                # dataset notes, real column names, feature mapping table
│   ├── data/raw/                # SWELL files go here (not committed to git)
│   ├── data/processed/
│   ├── notebooks/
│   │   ├── 01_eda.ipynb
│   │   ├── 02_features.ipynb
│   │   ├── 03_models.ipynb
│   │   └── 04_own_data.ipynb
│   └── reports/                 # charts, tables, SHAP plots for the college report
├── agent/
│   ├── README.md
│   ├── main.py                  # starts everything (agent + server)
│   ├── logger.py                # keyboard/mouse counters
│   ├── app_tracker.py           # frontmost app + app switches
│   ├── calibration.py
│   ├── detector.py              # condition model + smoothing
│   ├── load_scorer.py           # load model + personal calibration
│   ├── decisions.py             # when to suggest DND / break
│   ├── actions.py               # DND, notifications, dialogs
│   ├── feedback.py              # 👍/👎 and check-ins
│   ├── menubar.py
│   ├── consent.py
│   ├── storage.py               # SQLite helpers
│   └── platform/
│       ├── macos.py
│       └── windows.py           # Phase 4
├── server/
│   ├── README.md
│   ├── app.py                   # FastAPI routes
│   ├── categoriser.py           # rules → cache → local LLM / API
│   ├── redaction.py
│   └── report.py                # weekly report + PDF
├── extension/
│   ├── README.md
│   ├── manifest.json
│   ├── background.js            # tab tracking + heartbeats
│   ├── popup.html / popup.js    # status, private list, pairing token
│   └── welcome.html             # install-time privacy explanation
├── dashboard/
│   ├── README.md
│   ├── package.json
│   └── src/                     # React app
├── tests/
│   ├── test_features.py
│   ├── test_redaction.py
│   ├── test_categoriser.py
│   ├── test_decisions.py
│   └── test_privacy.py
├── requirements.txt
└── .gitignore                   # ignore data/, *.db, models trained on private data, .env
```

---

## 19. Setup and run instructions

Write these out fully in each folder's README as each phase is built. The expected flow:

### 19.1 Requirements
- macOS (Phase 1–3), Windows later.
- Python 3.11+, Node.js LTS (for the dashboard), Google Chrome.
- Optional: **Ollama** for the local LLM (`ollama pull llama3.2:3b`).

### 19.2 Python setup
```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Expected Python packages (add only what is used): `pynput`, `pyobjc-framework-Cocoa` (macOS), `rumps` (macOS), `fastapi`, `uvicorn`, `pyyaml`, `platformdirs`, `keyring`, `requests`, `pandas`, `numpy`, `scikit-learn`, `lightgbm`, `shap`, `joblib`, `reportlab`, `pytest`. Windows later: `pywin32`, `psutil`, `pystray`, `winotify`.

**Important:** use the **same scikit-learn version** for training (Phase 0) and the app, or the `.pkl` files may not load correctly.

### 19.3 Phase 0
- Put the SWELL files in `ml/data/raw/`.
- Run the notebooks in order (Jupyter, VS Code, or Google Colab).

### 19.4 Run the app (after Phase 1)
```bash
python -m agent.main
```
- First run: consent screen, macOS permissions (System Settings → Privacy & Security → **Accessibility** and **Input Monitoring** for the terminal/VS Code running Python), Shortcuts setup, calibration.

### 19.5 Extension (after Phase 2)
- Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → select `extension/`.
- Paste the pairing token from the app/dashboard.

### 19.6 Dashboard (after Phase 3)
```bash
cd dashboard
npm install
npm run build       # the server then serves dashboard/dist
```
- Open `http://127.0.0.1:8765`.

### 19.7 Tests
```bash
pytest
```

---

## 20. Known limitations (be honest about these)

1. **Computer-only signals are weak on SWELL.** Expect modest accuracy. Always report results against the majority baseline and under LOSO.
2. **Condition labels are a proxy.** The experimental condition is not the same as how loaded a person actually feels. That is why the load target uses self-ratings and personal calibration.
3. **Small, specific dataset.** 25 lab participants in the Netherlands; our study adds a few more. Results may not generalise widely.
4. **Individual differences are large.** Generic models struggle on new people; personalisation is essential.
5. **Notification filtering depends on the OS.** We switch Do Not Disturb on/off; the OS decides what gets through based on the user's allowlist. We cannot judge urgency from message content.
6. **Windows DND control is limited** (see Phase 4).
7. **Incognito and private sites** are intentionally reported with no detail.
8. **Not a medical tool.** It gives gentle suggestions only. It must never be used for performance appraisal, hiring, monitoring employees, or exams.

---

## 21. Related research and products

Cite these in the college report and use them for design decisions.

**Research**
- Koldijk, S., Sappelli, M., Verberne, S., Neerincx, M., & Kraaij, W. (2014). *The SWELL Knowledge Work Dataset for Stress and User Modeling Research.* ICMI 2014.
- Koldijk, S., Neerincx, M. A., & Kraaij, W. (2018). *Detecting Work Stress in Offices by Combining Unobtrusive Sensors.* IEEE Transactions on Affective Computing. (Computer-only 65.51% vs 61.76% baseline; unseen-user accuracy drop.)
- Naegelin, M., et al. (2023). *An interpretable machine learning approach to multimodal stress detection in a simulated office environment.* Journal of Biomedical Informatics, 139, 104299. (Mouse + keyboard beat heart rate; 1-minute windows; per-person normalisation; LightGBM; SHAP.)
- Naegelin, M., et al. (2025, preprint). *One does not fit all: Detecting work-related stress from mouse, keyboard, and cardiac data in the field.* medRxiv. (Generic models weak under LOSO; personalised models better.)
- Vizer, L. M., Zhou, L., & Sears, A. (2009). *Automated stress detection using keystroke and linguistic features: An exploratory study.* International Journal of Human-Computer Studies, 67(10).
- Pepa, L., et al. (2021). *Stress detection in computer users from keyboard and mouse dynamics.* IEEE Transactions on Consumer Electronics, 67(1).
- Freihaut, P., & Göritz, A. S. (2021). *Using the computer mouse for stress measurement – An empirical investigation and critical review.* International Journal of Human-Computer Studies, 145. (Counter-evidence.)

**Similar products (how Commit is different)**
- Rize, RescueTime: time tracking, focus sessions, break reminders. They measure *time*, not *mental load*.
- ActivityWatch: open-source, local-first time tracker. Tracking only, no interventions.
- Microsoft Viva Insights: calendar-based focus time and breaks.
- Keybreak, MacBreakZ, Zzzappy: input-based break timers focused on physical strain.
- Stress Signal (Chrome extension), Ontor.ai: typing/mouse-based stress breaks. Stress Signal is browser-only.

**Commit's differentiators:** system-wide (not browser-only) detection of Neutral / Interruptions / Time-pressure; different help for different stress (DND for interruptions, breaks for pressure); context-aware categories using a local LLM; privacy-first design (counts only, no titles stored, local by default); evaluated on SWELL-KW plus our own user study with published results; alerts explain *why* they appeared.
