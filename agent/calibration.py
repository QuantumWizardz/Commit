"""
agent/calibration.py — learns the user's normal pattern (README module M1.4).

The first 15 ACTIVE minutes after install (config calibration.active_minutes) are the
calibration period. Their features are collected; when there are enough, the mean and
standard deviation of every feature become the user's baseline (shared.features.compute_baseline).
No predictions or alerts happen during calibration. The user can restart calibration.

Progress is saved in the database, so an app restart does not lose collected minutes.
"""

from __future__ import annotations

import pandas as pd

from shared import features as F

BASELINE_KEY = "baseline"
COLLECTED_KEY = "calibration_minutes"


class Calibration:
    """Collects calibration minutes and stores the personal baseline."""

    def __init__(self, storage, active_minutes: int, feature_names: list[str]):
        """
        In:  storage, how many active minutes to collect, the model's feature names.
        """
        self.storage = storage
        self.active_minutes = active_minutes
        self.feature_names = feature_names

    def is_complete(self) -> bool:
        """True once a baseline has been saved."""
        return self.storage.get_setting(BASELINE_KEY) is not None

    def baseline(self) -> dict | None:
        """The saved baseline {feature: {"mean", "std"}}, or None during calibration."""
        return self.storage.get_setting(BASELINE_KEY)

    def progress(self) -> tuple[int, int]:
        """(minutes collected so far, minutes needed)."""
        return len(self.storage.get_setting(COLLECTED_KEY, [])), self.active_minutes

    def add_minute(self, features: dict) -> bool:
        """
        Add one active minute's features.

        In:  feature dict of an active minute (not normalised).
        Out: True if this minute completed the calibration (baseline saved now).
        """
        collected = self.storage.get_setting(COLLECTED_KEY, [])
        collected.append(features)
        if len(collected) < self.active_minutes:
            self.storage.set_setting(COLLECTED_KEY, collected)
            return False

        # Enough minutes: compute and save the baseline, then forget the raw minutes.
        baseline = F.compute_baseline(pd.DataFrame(collected), self.feature_names)
        self.storage.set_setting(BASELINE_KEY, baseline)
        self.storage.delete_setting(COLLECTED_KEY)
        return True

    def restart(self) -> None:
        """Forget the baseline and start collecting again (Settings → Re-run calibration)."""
        self.storage.delete_setting(BASELINE_KEY)
        self.storage.delete_setting(COLLECTED_KEY)
