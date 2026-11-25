"""
agent/storage.py — the local SQLite database (README section 13).

Why this file exists: every module saves and reads data through these few functions, so all
SQL is in one place. The database is one file in the user's app-data folder (privacy rule P6).

Thread safety: the agent writes from several threads (minute loop, dialogs, menu bar).
One connection is shared and every call holds a lock.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import platformdirs

APP_NAME = "Commit"

# README section 13, unchanged.
SCHEMA = """
CREATE TABLE IF NOT EXISTS minutes (
    ts               INTEGER PRIMARY KEY,
    mode             TEXT,
    app_category     TEXT,
    features_json    TEXT,
    condition        TEXT,
    condition_probs  TEXT,
    load_score       REAL
);
CREATE TABLE IF NOT EXISTS app_time (ts INTEGER, app_name TEXT, category TEXT, seconds INTEGER);
CREATE TABLE IF NOT EXISTS web_time (ts INTEGER, domain TEXT, category TEXT, seconds INTEGER);
CREATE TABLE IF NOT EXISTS title_cache (hash TEXT PRIMARY KEY, category TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS domain_rules (domain TEXT PRIMARY KEY, category TEXT);
CREATE TABLE IF NOT EXISTS private_domains (domain TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER,
    kind TEXT,
    reason TEXT,
    action TEXT,
    feedback TEXT
);
CREATE TABLE IF NOT EXISTS checkins (ts INTEGER PRIMARY KEY, rating INTEGER);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

# Tables with a "ts" column that are cleaned up after the retention period (P11).
TIMESTAMPED_TABLES = ["minutes", "app_time", "web_time", "alerts", "checkins"]

SECONDS_PER_DAY = 24 * 60 * 60


def default_database_path() -> Path:
    """The database file in the OS app-data folder, e.g. ~/Library/Application Support/Commit/commit.db."""
    folder = Path(platformdirs.user_data_dir(APP_NAME))
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "commit.db"


class Storage:
    """Small wrapper around one SQLite file."""

    def __init__(self, path: Path | None = None):
        """
        Open (and if needed create) the database.

        In:  path to the database file; None = the default app-data location.
        """
        self.path = Path(path) if path is not None else default_database_path()
        self.lock = threading.Lock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        with self.lock:
            self.connection.executescript(SCHEMA)
            self.connection.commit()

    # ------------------------------------------------------------------ basics

    def execute(self, sql: str, parameters: tuple = ()) -> list[tuple]:
        """
        Run one SQL statement and commit.

        In:  SQL text with ? placeholders and their values.
        Out: all result rows (empty list for INSERT/UPDATE/DELETE).
        """
        with self.lock:
            cursor = self.connection.execute(sql, parameters)
            rows = cursor.fetchall()
            self.connection.commit()
            return rows

    def close(self) -> None:
        """Close the database connection."""
        with self.lock:
            self.connection.close()

    # ------------------------------------------------------------------ settings

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Read a JSON value from the settings table (default if missing)."""
        rows = self.execute("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        """Save a JSON-serialisable value in the settings table."""
        self.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def delete_setting(self, key: str) -> None:
        """Remove one setting."""
        self.execute("DELETE FROM settings WHERE key = ?", (key,))

    # ------------------------------------------------------------------ minutes

    def save_minute(self, record: dict) -> None:
        """
        Save one minute (counts/predictions only, never key content).

        In:  dict with ts, mode, app_category, features (dict or None), condition,
             condition_probs (dict or None), load_score.
        """
        self.execute(
            "INSERT OR REPLACE INTO minutes VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record["ts"],
                record["mode"],
                record.get("app_category"),
                json.dumps(record["features"]) if record.get("features") is not None else None,
                record.get("condition"),
                json.dumps(record["condition_probs"]) if record.get("condition_probs") is not None else None,
                record.get("load_score"),
            ),
        )

    def active_minutes_between(self, start_ts: int, end_ts: int) -> list[dict]:
        """
        Active minutes (with features) in a time range, oldest first.

        Out: list of {"ts", "features", "load_score"}.
        """
        rows = self.execute(
            "SELECT ts, features_json, load_score FROM minutes "
            "WHERE mode = 'active' AND features_json IS NOT NULL AND ts >= ? AND ts < ? ORDER BY ts",
            (start_ts, end_ts),
        )
        return [{"ts": ts, "features": json.loads(features), "load_score": score} for ts, features, score in rows]

    def save_app_time(self, ts: int, app_seconds: dict[str, int], categories: dict[str, str]) -> None:
        """
        Save time per app for one minute (app names only, never window titles).

        In:  minute start, {app name: seconds}, {app name: category}.
        """
        for app_name, seconds in app_seconds.items():
            self.execute("INSERT INTO app_time VALUES (?, ?, ?, ?)", (ts, app_name, categories.get(app_name), seconds))

    # ------------------------------------------------------------------ websites (Phase 2)

    def save_web_time(self, ts: int, domain: str | None, category: str, seconds: int) -> None:
        """
        Save time on a website: domain + category + seconds only (P3). Private and
        Miscellaneous time is saved with domain None (P4, P5).
        """
        self.execute("INSERT INTO web_time VALUES (?, ?, ?, ?)", (ts, domain, category, seconds))

    def cached_category(self, title_hash: str) -> str | None:
        """Category stored for a salted (domain + title) hash, or None."""
        rows = self.execute("SELECT category FROM title_cache WHERE hash = ?", (title_hash,))
        return rows[0][0] if rows else None

    def cache_category(self, title_hash: str, category: str, created_at: int) -> None:
        """Remember the category of a salted hash (never the title itself)."""
        self.execute("INSERT OR REPLACE INTO title_cache VALUES (?, ?, ?)", (title_hash, category, created_at))

    def domain_rules(self) -> dict[str, str]:
        """User corrections: {domain: category}."""
        return dict(self.execute("SELECT domain, category FROM domain_rules"))

    def set_domain_rule(self, domain: str, category: str) -> None:
        """Save a user correction: this domain always gets this category."""
        self.execute(
            "INSERT INTO domain_rules VALUES (?, ?) ON CONFLICT(domain) DO UPDATE SET category = excluded.category",
            (domain, category),
        )

    def private_domains(self) -> list[str]:
        """The user's "Don't track" list, sorted."""
        return [row[0] for row in self.execute("SELECT domain FROM private_domains ORDER BY domain")]

    def add_private_domain(self, domain: str) -> None:
        self.execute("INSERT OR IGNORE INTO private_domains VALUES (?)", (domain,))

    def remove_private_domain(self, domain: str) -> None:
        self.execute("DELETE FROM private_domains WHERE domain = ?", (domain,))

    # ------------------------------------------------------------------ alerts and check-ins

    def add_alert(self, ts: int, kind: str, reason: str) -> int:
        """Create an alert row and return its id. action/feedback are filled in later."""
        with self.lock:
            cursor = self.connection.execute(
                "INSERT INTO alerts (ts, kind, reason) VALUES (?, ?, ?)", (ts, kind, reason)
            )
            self.connection.commit()
            return cursor.lastrowid

    def set_alert_action(self, alert_id: int, action: str) -> None:
        """Record what the user did with an alert (yes / not_now / auto / snooze_30 / ...)."""
        self.execute("UPDATE alerts SET action = ? WHERE id = ?", (action, alert_id))

    def set_alert_feedback(self, alert_id: int, feedback: str) -> None:
        """Record the 👍/👎 answer as "up" or "down"."""
        self.execute("UPDATE alerts SET feedback = ? WHERE id = ?", (feedback, alert_id))

    def add_checkin(self, ts: int, rating: int) -> None:
        """Save a 1–5 load self-rating."""
        self.execute("INSERT OR REPLACE INTO checkins VALUES (?, ?)", (ts, rating))

    def all_checkins(self) -> list[tuple[int, int]]:
        """All (ts, rating) check-ins, oldest first."""
        return self.execute("SELECT ts, rating FROM checkins ORDER BY ts")

    # ------------------------------------------------------------------ privacy

    def delete_older_than(self, days: int, now: float | None = None) -> None:
        """
        Delete data older than the retention period (P11).

        In:  retention in days; current time (for tests).
        """
        now = time.time() if now is None else now
        cutoff = int(now - days * SECONDS_PER_DAY)
        for table in TIMESTAMPED_TABLES:
            self.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
        self.execute("DELETE FROM title_cache WHERE created_at < ?", (cutoff,))

    def delete_database_file(self) -> None:
        """
        Close the connection and delete the database file and SQLite's side files (P9).
        """
        self.close()
        for suffix in ["", "-journal", "-wal", "-shm"]:
            Path(str(self.path) + suffix).unlink(missing_ok=True)
