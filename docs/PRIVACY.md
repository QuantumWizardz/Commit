# Commit — Privacy policy

*Plain-language version. Consent version 1.*

Commit is a focus and wellbeing app that runs **only on your own computer**. There is no account,
no cloud and no server run by us. This page explains what Commit collects, why, and how you stay in control.

## What Commit collects

| What | Why | Needs your consent |
|---|---|---|
| **Counts** of key presses, corrections (backspace/delete), shortcuts, pauses, mouse clicks, scrolls and mouse distance, **per minute** | To notice when you are working under interruptions or time pressure | Yes (switch 1, required) |
| **Name** of the app in front (e.g. "Slack") and how often you switch apps | Same as above; also shows where your time goes | Yes (switch 1) |
| Website **domain**, category and time (Chrome extension) | Weekly report of where time was spent | Yes (switch 2) |
| Page/video **titles**, only for a moment, to choose a category, then thrown away | Sort websites into categories | Yes (switch 3 or 4) |
| Your **1–5 load ratings** and 👍/👎 answers to alerts | Make the load score match how *you* feel; measure if alerts help | Yes (switch 5 for check-ins) |
| The model's predictions (condition, load score) per minute | Show your day and decide when to offer help | With switch 1 |

## What Commit never collects
- Which keys you pressed or anything you type. Each key is looked at in memory only to decide if it is a
  normal key, a correction or a shortcut, and is then forgotten.
- Passwords, the clipboard, screenshots, the camera or the microphone.
- Full web addresses (URLs) or page titles — titles are discarded right after categorising.
- Time on websites in your "Don't track" list: it shows only as "Private", without the site's name. (The names
  you type into that list are kept only in the list itself, so it can work.)
- Anything from incognito windows (shown only as "Miscellaneous").

## Where it is stored
In one SQLite database file on your computer
(`~/Library/Application Support/Commit/commit.db` on macOS). Commit's local server listens only on `127.0.0.1`,
so other computers cannot reach it, and it answers only the paired Chrome extension. An optional API key is kept in the
macOS Keychain, never in the database, settings or logs.

## How long
Data older than **30 days** (you can change this) is deleted automatically, including saved weekly report PDFs.

## Who it is shared with
**No one.** The only exception: if you turn on switch 4 ("title categorisation with my own API key"),
shortened page titles — with e-mail addresses, links and long numbers removed — are sent to the AI provider
whose API key *you* entered. That switch is off unless you turn it on.

## Your control
- **Pause** tracking at any time from the menu bar.
- **Change your consent** at any time: menu bar → Settings → Consent choices…
  Withdrawing consent for activity counts stops Commit.
- **Delete all my data** (menu bar): removes the database, cache, consent record, API key and logs.

## Not for monitoring others
Commit gives gentle suggestions to *you*. It is not a medical tool and must never be used for performance
appraisal, hiring, employee monitoring or exams.

## Data protection principles
Commit is designed with the principles of India's **Digital Personal Data Protection Act, 2023** in mind:
**specific consent for a stated purpose** (five separate switches), **data minimisation** (counts, domains and
categories only; titles discarded) and the **right to erasure** ("Delete all my data", automatic deletion after
the retention period).
