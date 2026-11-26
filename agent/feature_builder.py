"""
agent/feature_builder.py — turns each live minute into model features (README module M1.3).

All feature maths lives in shared/features.py (the same code used to train the models).
This file only:
  * keeps the last few minutes of raw counts (enough for the 5-minute rolling windows),
  * calls shared.features.build_features on them,
  * decides the activity mode of a minute (Idle / Passive / Active),
  * reads shared/models/features.json.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import pandas as pd

from shared import features as F

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "shared" / "models"
FEATURE_SPEC_FILE = MODELS_DIR / "features.json"

MODE_IDLE = "idle"
MODE_PASSIVE = "passive"
MODE_ACTIVE = "active"
MODE_PAUSED = "paused"
MODE_COMMIT = "commit"      # a minute spent mostly in Commit itself (dashboard, dialogs): counted nowhere


def load_feature_spec(path: Path = FEATURE_SPEC_FILE) -> dict:
    """
    Read features.json written by Notebook 3.

    Out: dict with feature_names, rolling_windows_minutes, normalisation, model details.
    Raises FileNotFoundError if Phase 0 has not been run.
    """
    return json.loads(Path(path).read_text())


def activity_mode(active_seconds: int, main_category: str, idle_seconds: int, passive_seconds: int, passive_categories: list[str]) -> str:
    """
    Decide the activity mode of a minute (README 8.3).

    In:  active seconds in the minute, the main app category, and the config thresholds
         (activity.idle_active_seconds, activity.passive_active_seconds, activity.passive_categories).
    Out: "idle", "passive" or "active". Predictions and alerts run only for "active".
    """
    if active_seconds < idle_seconds:
        return MODE_IDLE
    if active_seconds < passive_seconds and main_category in passive_categories:
        return MODE_PASSIVE
    return MODE_ACTIVE


class RecentMinutes:
    """The last few minutes of raw counts, used to compute rolling features."""

    def __init__(self, windows: tuple[int, ...]):
        """
        In:  rolling window lengths from features.json (e.g. (3, 5)).
        """
        self.windows = windows
        # Keep exactly as many minutes as the longest window needs.
        self.rows: deque[dict] = deque(maxlen=max(windows))

    def add(self, minute_ts: int, raw_counts: dict) -> None:
        """
        Remember one minute.

        In:  unix time of the minute start, dict with (at least) shared.features.RAW_COUNT_COLUMNS.
        """
        row = {name: raw_counts[name] for name in F.RAW_COUNT_COLUMNS}
        row["ts"] = minute_ts
        self.rows.append(row)

    def latest_features(self) -> dict:
        """
        Features of the most recent minute (not yet normalised).

        Out: {feature name: value} for every feature in shared.features.model_feature_names.
        Time-based windows mean that paused or missing minutes simply are not in the window.
        """
        table = pd.DataFrame(list(self.rows))
        built = F.build_features(table, time_column="ts", windows=self.windows)
        latest = built.iloc[-1]
        return {name: float(latest[name]) for name in F.model_feature_names(self.windows)}

    def clear(self) -> None:
        """Forget all minutes (e.g. after a pause)."""
        self.rows.clear()


def normalised_model_input(features: dict, baseline: dict, feature_names: list[str]) -> pd.DataFrame:
    """
    Z-score one minute's features against the user's baseline, in model order.

    In:  feature dict, baseline from calibration, feature order from features.json.
    Out: a one-row DataFrame ready for model.predict_proba.
    """
    row = pd.DataFrame([features])
    normalised = F.apply_baseline(row, baseline, feature_names)
    return F.order_for_model(normalised, feature_names)
