"""
agent/load_scorer.py — the 0–100 cognitive load score (README module M1.6).

Every active minute:
  1. base score = load_model.pkl probability of "high" load (0–1);
  2. if the user has a personal calibration, it maps that probability to how THIS user rates
     their load; otherwise score = probability × 100;
  3. add a small configurable boost (load.condition_boost) under Interruptions or Time pressure;
  4. clip to 0–100.

Personal calibration: once there are at least 20 check-in ratings
(checkins.min_ratings_for_personal_model), we fit a logistic regression from the model's
probability (averaged over the active minutes before each check-in) to "was this rating above
the user's own median rating?". It is refitted every 7 days (load.refit_days).

Why: in Phase 0 the generic load model was close to chance on new people, so personal
calibration from the user's own ratings is what makes this score meaningful.
"""

from __future__ import annotations

import logging
import math
import statistics
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

log = logging.getLogger(__name__)

CALIBRATION_KEY = "load_personal_calibration"
ATTEMPT_KEY = "load_calibration_attempt_checkins"   # number of check-ins at the last fit attempt
HIGH_LOAD_CLASS = "high"
PRESSURE_CONDITIONS = ("interruptions", "time_pressure")
SECONDS_PER_DAY = 24 * 60 * 60
SECONDS_PER_MINUTE = 60
MAX_SCORE = 100.0


def fit_personal_calibration(pairs: list[tuple[float, int]]) -> dict | None:
    """
    Fit the mapping from model probability to the user's own ratings.

    In:  list of (model probability of high load, user's 1–5 rating), one per check-in.
    Out: {"coef", "intercept"} of a logistic regression, or None if the ratings are all
         on one side of the median (nothing to learn yet).
    """
    probabilities = np.array([[p] for p, _ in pairs])
    ratings = [rating for _, rating in pairs]
    median_rating = statistics.median(ratings)
    labels = np.array([1 if rating > median_rating else 0 for rating in ratings])
    if labels.min() == labels.max():
        return None
    model = LogisticRegression().fit(probabilities, labels)
    return {"coef": float(model.coef_[0][0]), "intercept": float(model.intercept_[0])}


def apply_personal_calibration(probability: float, calibration: dict) -> float:
    """
    Map a model probability to a personal 0–100 score.

    In:  probability of high load, the fitted {"coef", "intercept"}.
    Out: 100 × sigmoid(coef × probability + intercept).
    """
    logit = calibration["coef"] * probability + calibration["intercept"]
    return MAX_SCORE / (1.0 + math.exp(-logit))


class LoadScorer:
    """Computes the load score and keeps the personal calibration up to date."""

    def __init__(self, model_path, feature_names: list[str], storage, config):
        """
        In:  path to load_model.pkl, the model's feature names, storage, config.
        """
        self.model = joblib.load(model_path)
        self.high_column = [str(c) for c in self.model.classes_].index(HIGH_LOAD_CLASS)
        self.feature_names = feature_names
        self.storage = storage
        self.config = config

    def high_probability(self, model_input: pd.DataFrame) -> list[float]:
        """Model probability of high load for each row of a normalised feature table."""
        return [float(p) for p in self.model.predict_proba(model_input)[:, self.high_column]]

    def score(self, model_input: pd.DataFrame, smoothed_condition: str) -> float:
        """
        The 0–100 load score of one minute.

        In:  one-row normalised feature table, the smoothed condition.
        Out: the load score (rounded to 1 decimal).
        """
        probability = self.high_probability(model_input)[0]
        calibration = self.storage.get_setting(CALIBRATION_KEY)
        if calibration is not None:
            score = apply_personal_calibration(probability, calibration)
        else:
            score = probability * MAX_SCORE
        if smoothed_condition in PRESSURE_CONDITIONS:
            score += self.config.get("load.condition_boost")
        return round(min(max(score, 0.0), MAX_SCORE), 1)

    # ------------------------------------------------------------ personal calibration

    def checkin_pairs(self) -> list[tuple[float, int]]:
        """
        Pair each check-in rating with the model's average probability in the active minutes
        just before it (load.checkin_window_minutes).

        Out: list of (probability, rating). Check-ins with no active minutes before them are skipped.
        """
        window_seconds = self.config.get("load.checkin_window_minutes") * SECONDS_PER_MINUTE
        pairs = []
        for checkin_ts, rating in self.storage.all_checkins():
            minutes = self.storage.active_minutes_between(checkin_ts - window_seconds, checkin_ts)
            if not minutes:
                continue
            model_input = pd.DataFrame([m["features"] for m in minutes])[self.feature_names]
            pairs.append((float(np.mean(self.high_probability(model_input))), rating))
        return pairs

    def needs_refit(self, now: float) -> bool:
        """
        True if a (re)fit should be tried now:
          * at least checkins.min_ratings_for_personal_model ratings exist, and
          * a new rating arrived since the last attempt, and
          * there is no calibration yet, or it is older than load.refit_days.
        """
        checkin_count = len(self.storage.all_checkins())
        if checkin_count < self.config.get("checkins.min_ratings_for_personal_model"):
            return False
        if checkin_count == self.storage.get_setting(ATTEMPT_KEY):
            return False  # nothing new since the last try
        calibration = self.storage.get_setting(CALIBRATION_KEY)
        if calibration is None:
            return True
        return now - calibration["fitted_at"] >= self.config.get("load.refit_days") * SECONDS_PER_DAY

    def maybe_refit(self, now: float | None = None) -> None:
        """Refit the personal calibration when needed. Errors are logged, never raised."""
        now = time.time() if now is None else now
        try:
            if not self.needs_refit(now):
                return
            # Remember how many ratings this attempt used, so a failed fit is not retried every minute.
            self.storage.set_setting(ATTEMPT_KEY, len(self.storage.all_checkins()))
            pairs = self.checkin_pairs()
            fitted = fit_personal_calibration(pairs) if len(pairs) >= 2 else None
            if fitted is None:
                log.info("Personal load calibration: ratings do not vary enough yet.")
                return
            fitted.update({"fitted_at": now, "ratings_used": len(pairs)})
            self.storage.set_setting(CALIBRATION_KEY, fitted)
            log.info("Personal load calibration fitted on %d check-ins.", len(pairs))
        except Exception:
            log.exception("Personal load calibration failed; keeping the previous one.")
