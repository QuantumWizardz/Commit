"""
agent/detector.py — predicts the working condition every active minute (README module M1.5).

Uses shared/models/condition_model.pkl (from Notebook 3). The shown condition is SMOOTHED:
the most common prediction over the last 5 active minutes (config detection.smoothing_minutes),
so one noisy minute does not change anything.
"""

from __future__ import annotations

from collections import Counter, deque

import joblib
import pandas as pd

CONDITIONS = ["neutral", "interruptions", "time_pressure"]


def most_common_recent(labels: list[str]) -> str:
    """
    The most common label; on a tie, the tied label that appeared most recently.

    In:  labels in time order (oldest first), at least one.
    Out: one label.
    Why: smoothing rule from README 8.4.
    """
    counts = Counter(labels)
    highest = max(counts.values())
    for label in reversed(labels):
        if counts[label] == highest:
            return label
    raise ValueError("labels must not be empty")


class ConditionDetector:
    """Loads the condition model, predicts, and smooths the predictions."""

    def __init__(self, model_path, smoothing_minutes: int):
        """
        In:  path to condition_model.pkl, smoothing window length in active minutes.
        """
        self.model = joblib.load(model_path)
        self.classes = [str(name) for name in self.model.classes_]
        self.recent_predictions: deque[str] = deque(maxlen=smoothing_minutes)

    def predict(self, model_input: pd.DataFrame) -> tuple[str, str, dict[str, float]]:
        """
        Predict one minute and update the smoothing window.

        In:  one-row normalised feature table (feature_builder.normalised_model_input).
        Out: (raw prediction, smoothed condition, {class: probability}).
        """
        probabilities = self.model.predict_proba(model_input)[0]
        probability_by_class = {name: round(float(p), 4) for name, p in zip(self.classes, probabilities)}
        raw_prediction = max(probability_by_class, key=probability_by_class.get)
        self.recent_predictions.append(raw_prediction)
        return raw_prediction, most_common_recent(list(self.recent_predictions)), probability_by_class

    def reset(self) -> None:
        """Forget recent predictions (after a pause or a new calibration)."""
        self.recent_predictions.clear()
