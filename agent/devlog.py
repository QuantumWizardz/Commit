"""
agent/devlog.py — the Developer mode event log shown on the dashboard's Developer page.

Why this file exists: when developer mode is on, every part of the app (minute loop, predictions,
alert decisions, website heartbeats) adds a short event here, so a developer can watch live
what Commit is tracking and predicting.

Privacy:
  - Memory only. Events are never written to the database or the log file, and are gone when
    Commit quits (the dashboard's "Download log" button saves a copy only when asked).
  - Nothing is recorded while developer mode is off.
  - Events hold the same kind of data the database already holds: counts, app names, domains,
    categories, predictions. Never key content, page titles or URLs (P1, P3, P12).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

DEVELOPER_MODE_KEY = "developer_mode"   # settings table key (bool)
MAX_EVENTS = 1000                       # oldest events are dropped after this

# Event kinds (the dashboard colours and filters by these).
ACTIVITY = "activity"
CALIBRATION = "calibration"
PREDICTION = "prediction"
DECISION = "decision"
ALERT = "alert"
WEBSITE = "website"
SYSTEM = "system"
KINDS = (ACTIVITY, CALIBRATION, PREDICTION, DECISION, ALERT, WEBSITE, SYSTEM)


def developer_mode_on(storage) -> bool:
    """Is developer mode switched on in Settings?"""
    return bool(storage.get_setting(DEVELOPER_MODE_KEY, False))


class DevLog:
    """A thread-safe ring buffer of recent events. Each event gets an increasing id."""

    def __init__(self, is_enabled: Callable[[], bool], max_events: int = MAX_EVENTS, clock=time.time):
        """
        In:  a function that says whether developer mode is on (checked on every add),
             how many events to keep, and a clock (for tests).
        """
        self.is_enabled = is_enabled
        self.clock = clock
        self.events: deque[dict] = deque(maxlen=max_events)
        self.next_id = 1
        self.lock = threading.Lock()

    def add(self, kind: str, message: str, /, **data) -> None:
        """
        Record one event (does nothing while developer mode is off). Never raises.

        In:  one of KINDS, a one-line human-readable message, and any JSON-friendly details.
        """
        try:
            if not self.is_enabled():
                return
        except Exception:
            return
        with self.lock:
            self.events.append({"id": self.next_id, "ts": round(self.clock(), 3), "kind": kind, "message": message, "data": data})
            self.next_id += 1

    def since(self, after_id: int = 0) -> list[dict]:
        """Events newer than `after_id`, oldest first (after_id=0 returns all kept events)."""
        with self.lock:
            return [event for event in self.events if event["id"] > after_id]

    def last_id(self) -> int:
        """The id of the newest event (0 if none yet)."""
        with self.lock:
            return self.next_id - 1

    def clear(self) -> None:
        """Forget every event (ids keep increasing, so open dashboards do not miss new ones)."""
        with self.lock:
            self.events.clear()
