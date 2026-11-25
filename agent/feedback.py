"""
agent/feedback.py — 👍/👎 after every alert and the optional load check-in (README module M1.9).

These answers are the labels used for personal calibration (load_scorer.py) and for measuring
how useful the alerts are in practice.
"""

from __future__ import annotations

import time

THUMBS_UP = "👍"
THUMBS_DOWN = "👎"
FEEDBACK_VALUES = {THUMBS_UP: "up", THUMBS_DOWN: "down"}

CHECKIN_QUESTION = "How mentally loaded do you feel right now?\n(1 = not at all, 5 = very loaded)"
CHECKIN_CHOICES = ["1", "2", "3", "4", "5"]


def ask_alert_feedback(system, storage, alert_id: int, timeout_seconds: int) -> str | None:
    """
    Ask "Was this alert right?" and save the answer.

    In:  platform module, storage, the alert's id, dialog timeout.
    Out: "up", "down", or None if the dialog timed out (nothing is saved then).
    """
    answer = system.ask("Was this alert right?", [THUMBS_DOWN, THUMBS_UP], default_button=THUMBS_UP, timeout_seconds=timeout_seconds)
    if answer is None:
        return None
    feedback = FEEDBACK_VALUES[answer]
    storage.set_alert_feedback(alert_id, feedback)
    return feedback


def ask_checkin(system, storage, timeout_seconds: int) -> int | None:
    """
    Ask for a 1–5 load rating and save it.

    In:  platform module, storage, dialog timeout.
    Out: the rating, or None if the user did not answer.
    """
    answer = system.choose(CHECKIN_QUESTION, CHECKIN_CHOICES, timeout_seconds=timeout_seconds)
    if answer is None:
        return None
    rating = int(answer)
    storage.add_checkin(int(time.time()), rating)
    return rating
