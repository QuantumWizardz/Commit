"""
agent/actions.py — things the agent DOES: Do Not Disturb, alert dialogs, break timer
(README modules M1.7, M1.8, M1.9 and section 8.10).

Three parts:
  DndController  turns DND on/off by running the user's two macOS Shortcuts, and turns it
                 off again after dnd.duration_minutes (also after an app restart).
  AlertWorker    runs one dialog flow at a time on its own thread, so the minute loop never
                 waits for the user, and two alerts are never shown at once.
  AlertFlows     the actual DND question, break suggestion and check-in, each followed by feedback.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from agent import feedback

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHORTCUTS_GUIDE = PROJECT_ROOT / "docs" / "SHORTCUTS_SETUP.md"

DND_UNTIL_KEY = "dnd_turned_on_until"   # unix time until which WE turned DND on
SECONDS_PER_MINUTE = 60

# Break dialog choices → alert actions stored in the database.
BREAK_CHOICES = {
    "Take a break": "yes",
    "Snooze 30 min": "snooze_30",
    "Snooze 60 min": "snooze_60",
    "Dismiss": "dismiss",
}
# DND dialog buttons → alert actions.
DND_BUTTONS = {"Not now": "not_now", "Always do this automatically": "auto", "Yes": "yes"}
NO_ANSWER = "no_answer"


class DndController:
    """Switches macOS Do Not Disturb with the "Commit Focus On/Off" Shortcuts."""

    def __init__(self, system, storage, config):
        self.system = system
        self.storage = storage
        self.config = config
        self.off_timer: threading.Timer | None = None

    def show_setup_help(self) -> None:
        """Friendly message with a link to the Shortcuts setup guide (shortcuts missing or failing)."""
        answer = self.system.ask(
            "Commit could not switch Do Not Disturb. The Shortcuts "
            f"\"{self.config.get('dnd.shortcut_on')}\" and \"{self.config.get('dnd.shortcut_off')}\" "
            "may be missing.",
            ["OK", "Open setup guide"],
            default_button="Open setup guide",
            timeout_seconds=self.config.get("dialogs.timeout_seconds"),
        )
        if answer == "Open setup guide":
            self.system.open_url(SHORTCUTS_GUIDE.as_uri())

    def turn_on(self) -> bool:
        """
        Turn DND on for dnd.duration_minutes and schedule turning it off.

        Out: True if the Shortcut ran.
        """
        if not self.system.run_shortcut(self.config.get("dnd.shortcut_on")):
            self.show_setup_help()
            return False
        duration_seconds = self.config.get("dnd.duration_minutes") * SECONDS_PER_MINUTE
        self.storage.set_setting(DND_UNTIL_KEY, time.time() + duration_seconds)
        self.schedule_off(duration_seconds)
        return True

    def schedule_off(self, seconds: float) -> None:
        """Turn DND off after `seconds` (replaces any earlier timer)."""
        if self.off_timer is not None:
            self.off_timer.cancel()
        self.off_timer = threading.Timer(max(seconds, 0), self.turn_off)
        self.off_timer.daemon = True
        self.off_timer.start()

    def turn_off(self, announce: bool = True) -> None:
        """Turn DND off (only if we turned it on) and tell the user."""
        if self.storage.get_setting(DND_UNTIL_KEY) is None:
            return
        self.storage.delete_setting(DND_UNTIL_KEY)
        if self.off_timer is not None:
            self.off_timer.cancel()
            self.off_timer = None
        if self.system.run_shortcut(self.config.get("dnd.shortcut_off")):
            if announce:
                self.system.notify("Commit", "Do Not Disturb is off again.")
        else:
            self.show_setup_help()

    def restore_after_restart(self) -> None:
        """If we had turned DND on before the app stopped, turn it off now or when it is due."""
        until = self.storage.get_setting(DND_UNTIL_KEY)
        if until is None:
            return
        remaining = until - time.time()
        if remaining <= 0:
            self.turn_off()
        else:
            self.schedule_off(remaining)


class AlertWorker:
    """Runs dialog flows one at a time on a background thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.busy = False

    def submit(self, flow: Callable[[], None]) -> bool:
        """
        Start a dialog flow if no other flow is showing.

        In:  a function that shows dialogs.
        Out: True if it was started, False if another dialog is already open (the new one is dropped,
             it would be out of date by the time the user sees it).
        """
        with self.lock:
            if self.busy:
                return False
            self.busy = True
        threading.Thread(target=self.run_flow, args=(flow,), name="alert-flow", daemon=True).start()
        return True

    def run_flow(self, flow: Callable[[], None]) -> None:
        """Run one flow; errors are logged and never stop the agent."""
        try:
            flow()
        except Exception:
            log.exception("An alert dialog failed; continuing.")
        finally:
            with self.lock:
                self.busy = False

    def is_busy(self) -> bool:
        with self.lock:
            return self.busy


class AlertFlows:
    """The dialogs the user sees. Each method runs on the AlertWorker thread."""

    def __init__(self, system, storage, config, dnd: DndController, record_answer: Callable[[str, str, float], None]):
        """
        In:  platform module, storage, config, the DND controller, and a callback
             record_answer(kind, action, time) that updates the decision state.
        """
        self.system = system
        self.storage = storage
        self.config = config
        self.dnd = dnd
        self.record_answer = record_answer

    def timeout(self) -> int:
        return self.config.get("dialogs.timeout_seconds")

    def dnd_flow(self, reason: str) -> None:
        """Ask to turn on DND (or do it automatically), then ask for feedback."""
        alert_id = self.storage.add_alert(int(time.time()), "dnd", reason)
        minutes = self.config.get("dnd.duration_minutes")

        if self.config.get("dnd.mode") == "auto":
            action = "auto"
        else:
            question = f"You seem to be under pressure. Turn on Do Not Disturb for {minutes} minutes?\n\nWhy: {reason}"
            answer = self.system.ask(question, list(DND_BUTTONS), default_button="Yes", timeout_seconds=self.timeout())
            action = DND_BUTTONS.get(answer, NO_ANSWER)
            if action == "auto":
                self.config.set("dnd.mode", "auto")

        self.storage.set_alert_action(alert_id, action)
        self.record_answer("dnd", action, time.time())
        if action in ("yes", "auto"):
            if self.dnd.turn_on() and self.config.get("dnd.mode") == "auto":
                self.system.notify("Commit", f"Do Not Disturb is on for {minutes} minutes. Why: {reason}")
        if action != NO_ANSWER:
            feedback.ask_alert_feedback(self.system, self.storage, alert_id, self.timeout())

    def break_flow(self, reason: str) -> None:
        """Suggest a short break, then ask for feedback."""
        alert_id = self.storage.add_alert(int(time.time()), "break", reason)
        break_minutes = self.config.get("breaks.break_minutes")
        question = f"You've been working hard for a while. Take a {break_minutes}-minute break?\n\nWhy: {reason}"
        answer = self.system.choose(question, list(BREAK_CHOICES), timeout_seconds=self.timeout())
        action = BREAK_CHOICES.get(answer, NO_ANSWER)

        self.storage.set_alert_action(alert_id, action)
        self.record_answer("break", action, time.time())
        if action == "yes":
            self.start_break_timer(break_minutes)
        if action != NO_ANSWER:
            feedback.ask_alert_feedback(self.system, self.storage, alert_id, self.timeout())

    def start_break_timer(self, break_minutes: int) -> None:
        """Simple break timer: a notification now and one when the break is over."""
        self.system.notify("Commit", f"Break started. Step away for {break_minutes} minutes and breathe slowly.")
        timer = threading.Timer(break_minutes * SECONDS_PER_MINUTE, self.system.notify, args=("Commit", "Break over. Welcome back!"))
        timer.daemon = True
        timer.start()

    def checkin_flow(self) -> None:
        """Ask for a 1–5 load rating."""
        feedback.ask_checkin(self.system, self.storage, self.timeout())
