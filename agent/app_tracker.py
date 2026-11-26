"""
agent/app_tracker.py — which app is in front, and how often it changes (README module M1.3).

Every few seconds (config logging.app_sample_seconds) we read the NAME of the frontmost app.
Window titles are never read. Per minute we report:
    app_switches   how many times the frontmost app changed
    app_seconds    {app name: seconds in front}
    main_app       the app that was in front the longest
    main_category  that app's category (from the editable app_categories table in the config)

If Chrome is in front, the Chrome extension will give site details from Phase 2 on.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from typing import Callable

log = logging.getLogger(__name__)

# Category for apps that are not in the app_categories table.
UNKNOWN_CATEGORY = "Other"


def category_for_app(app_name: str | None, app_categories: dict[str, str]) -> str:
    """
    Look up an app's category.

    In:  app name (or None), the {app: category} table from the config.
    Out: the category, or "Other" if the app is not listed.
    """
    if app_name is None:
        return UNKNOWN_CATEGORY
    return app_categories.get(app_name, UNKNOWN_CATEGORY)


class AppTracker:
    """Samples the frontmost app on a background thread and summarises it per minute."""

    def __init__(self, get_frontmost_app: Callable[[], str | None], sample_seconds: float,
                 app_categories: dict[str, str] | Callable[[], dict[str, str]]):
        """
        In:  a function returning the frontmost app name (platform layer, or a fake in tests),
             seconds between samples, and the app → category table — or a function returning it,
             so changes made on the dashboard apply from the next minute.
        """
        self.get_frontmost_app = get_frontmost_app
        self.sample_seconds = sample_seconds
        self.app_categories = app_categories
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.previous_app: str | None = None
        self.current_app: str | None = None
        self.reset_minute()

    def reset_minute(self) -> None:
        """Start a new, empty minute."""
        self.app_switches = 0
        self.app_seconds: Counter = Counter()

    def take_sample(self) -> None:
        """Read the frontmost app once and add it to this minute's totals."""
        app_name = self.get_frontmost_app()
        with self.lock:
            self.current_app = app_name
            if app_name is None:
                return
            if self.previous_app is not None and app_name != self.previous_app:
                self.app_switches += 1
            self.previous_app = app_name
            self.app_seconds[app_name] += self.sample_seconds

    def snapshot_and_reset(self) -> dict:
        """
        Return this minute's app summary and start a new minute.

        Out: {"app_switches", "app_seconds", "main_app", "main_category", "app_categories"}.
        """
        table = self.app_categories() if callable(self.app_categories) else self.app_categories
        with self.lock:
            app_seconds = dict(self.app_seconds)
            main_app = max(app_seconds, key=app_seconds.get) if app_seconds else self.current_app
            summary = {
                "app_switches": self.app_switches,
                "app_seconds": {name: int(seconds) for name, seconds in app_seconds.items()},
                "main_app": main_app,
                "main_category": category_for_app(main_app, table),
                "app_categories": {name: category_for_app(name, table) for name in app_seconds},
            }
            self.reset_minute()
            return summary

    def frontmost_app(self) -> str | None:
        """The most recently seen frontmost app (used to avoid interrupting calls)."""
        with self.lock:
            return self.current_app

    # ------------------------------------------------------------ background thread

    def run(self) -> None:
        """Sampling loop. Errors are logged and the loop keeps going (README rule 7)."""
        while not self.stop_event.is_set():
            try:
                self.take_sample()
            except Exception:
                log.exception("App sample failed; continuing.")
            self.stop_event.wait(self.sample_seconds)

    def start(self) -> None:
        """Start sampling in a background thread."""
        self.thread = threading.Thread(target=self.run, name="app-tracker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop sampling."""
        self.stop_event.set()
