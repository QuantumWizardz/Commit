"""
shared/features.py — the ONE place where raw per-minute counts become ML features.

Why this file exists
--------------------
The model is trained on SWELL-KW in Phase 0 and then used live by the desktop agent in
Phase 1. If training and the live app computed features differently, the model would get
inputs it was never trained on. So BOTH use the functions in this file, and nothing else.

What goes in
------------
A pandas DataFrame with one row per minute and these raw count columns
(see RAW_COUNT_COLUMNS):

    keystrokes      number of key presses
    error_keys      backspace / delete presses
    shortcut_keys   key presses while Cmd/Ctrl/Alt is held
    clicks          mouse button presses
    scrolls         scroll (mouse wheel) events
    mouse_distance  pointer distance moved in the minute (pixels)
    app_switches    number of times the frontmost application changed

plus a datetime column with the start of each minute.
(Phase 0 renames the SWELL columns to these names; Phase 1 logs them directly.)

What comes out
--------------
The same rows with extra feature columns:
  1. ratio features   (e.g. error_key_ratio)
  2. an idle flag     (is_idle: no input at all in the minute)
  3. rolling features (mean / standard deviation over the last 3 and 5 minutes,
                       and the share of idle minutes in that window)
and helper functions for per-person normalisation (z-scores against a personal baseline).

The exact list and order of model features is given by `model_feature_names()` and is saved
to shared/models/features.json by Notebook 3.
"""

from __future__ import annotations

import math

import pandas as pd

# ---------------------------------------------------------------------------
# Constants (these define the model's inputs, so they are fixed here, not in user config)
# ---------------------------------------------------------------------------

# Raw counts that BOTH the SWELL dataset and our own desktop agent provide.
RAW_COUNT_COLUMNS = [
    "keystrokes",
    "error_keys",
    "shortcut_keys",
    "clicks",
    "scrolls",
    "mouse_distance",
    "app_switches",
]

# Ratio features computed from the raw counts of the same minute.
RATIO_COLUMNS = [
    "error_key_ratio",   # error_keys / keystrokes
    "shortcut_ratio",    # shortcut_keys / keystrokes
    "keyboard_share",    # keystrokes / (keystrokes + clicks + scrolls)
]

# Every feature that describes a single minute.
PER_MINUTE_FEATURES = RAW_COUNT_COLUMNS + RATIO_COLUMNS

# Name of the 0/1 column that marks a minute with no input at all.
IDLE_COLUMN = "is_idle"

# Raw columns that count as "input". If all of them are zero, the minute is idle.
# (app_switches is left out on purpose: an app can change without the user touching anything.)
INPUT_COLUMNS_FOR_IDLE = ["keystrokes", "clicks", "scrolls", "mouse_distance"]

# Lengths (in minutes) of the trailing rolling windows. A 3-minute window at time t
# covers the minutes t-2, t-1 and t. Only PAST and current minutes are used, never future
# ones, because the live app cannot see the future.
DEFAULT_ROLLING_WINDOWS = (3, 5)

# If a feature never changed during the baseline period, its standard deviation is 0 and
# a z-score would divide by zero. In that case we divide by 1 instead, so the feature becomes
# "difference from the personal mean" in its own units.
ZERO_STD_REPLACEMENT = 1.0

# Standard deviations smaller than this are treated as zero (protects against rounding noise).
ZERO_STD_TOLERANCE = 1e-9


# ---------------------------------------------------------------------------
# 1. Per-minute features
# ---------------------------------------------------------------------------

def check_raw_columns(minutes: pd.DataFrame) -> None:
    """
    Make sure every raw count column is present.

    In:  a DataFrame of per-minute counts.
    Out: nothing. Raises ValueError with a clear message if a column is missing.
    Why: a missing column would otherwise cause a confusing error much later.
    """
    missing = [name for name in RAW_COUNT_COLUMNS if name not in minutes.columns]
    if missing:
        raise ValueError(f"Missing raw count columns: {missing}")


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """
    Divide two columns, returning 0 where the denominator is 0.

    In:  two numeric Series of the same length.
    Out: numerator / denominator, with 0 instead of "division by zero".
    Why: a minute with no key presses has no error-key ratio; 0 is a sensible neutral value.
    """
    # Replace zero denominators by "missing" so the division gives NaN there ...
    safe_denominator = denominator.where(denominator > 0)
    result = numerator / safe_denominator
    # ... and then turn those NaN values into 0.
    return result.fillna(0.0)


def add_ratio_features(minutes: pd.DataFrame) -> pd.DataFrame:
    """
    Add the ratio features listed in RATIO_COLUMNS.

    In:  per-minute DataFrame with the raw count columns.
    Out: a copy with the extra columns error_key_ratio, shortcut_ratio, keyboard_share.
    Why: ratios describe HOW someone works (e.g. how much they correct themselves),
         independent of how much they work in that minute.
    """
    result = minutes.copy()

    # Share of key presses that were corrections (backspace / delete).
    result["error_key_ratio"] = safe_divide(result["error_keys"], result["keystrokes"])

    # Share of key presses that were shortcuts.
    result["shortcut_ratio"] = safe_divide(result["shortcut_keys"], result["keystrokes"])

    # How keyboard-heavy the minute was compared with the mouse (0 = only mouse, 1 = only keyboard).
    total_inputs = result["keystrokes"] + result["clicks"] + result["scrolls"]
    result["keyboard_share"] = safe_divide(result["keystrokes"], total_inputs)

    return result


def add_idle_flag(minutes: pd.DataFrame) -> pd.DataFrame:
    """
    Add the 0/1 column `is_idle` (1 = no keyboard or mouse input at all in this minute).

    In:  per-minute DataFrame with the raw count columns.
    Out: a copy with the extra column is_idle.
    Why: the rolling "share of idle minutes" feature needs it, and idle minutes are
         skipped when choosing calibration minutes and when making predictions.
    """
    result = minutes.copy()
    total_input = result[INPUT_COLUMNS_FOR_IDLE].sum(axis=1)
    result[IDLE_COLUMN] = (total_input == 0).astype(int)
    return result


# ---------------------------------------------------------------------------
# 2. Rolling (multi-minute) features
# ---------------------------------------------------------------------------

def rolling_feature_name(feature: str, statistic: str, window_minutes: int) -> str:
    """
    Build the column name of a rolling feature, e.g. ("keystrokes", "mean", 3) -> "keystrokes_mean_3m".

    In:  the per-minute feature name, the statistic ("mean" or "std"), the window length.
    Out: the column name.
    Why: one function for naming keeps training and the live app consistent.
    """
    return f"{feature}_{statistic}_{window_minutes}m"


def idle_share_name(window_minutes: int) -> str:
    """
    Column name of the "share of idle minutes" feature for one window, e.g. "idle_share_5m".

    In:  window length in minutes.
    Out: the column name.
    """
    return f"idle_share_{window_minutes}m"


def rolling_features_for_one_group(
    group: pd.DataFrame, time_column: str, windows: tuple[int, ...]
) -> pd.DataFrame:
    """
    Compute rolling features for ONE continuous recording (one person, one session).

    In:  the rows of one group, a datetime column name, and the window lengths in minutes.
    Out: a DataFrame (same index as `group`) holding only the new rolling columns.
    Why: rolling windows must never mix two people or two separate sessions.

    The windows are time-based: a 3-minute window at 10:05 uses the rows stamped
    10:03, 10:04 and 10:05 that EXIST. If a minute is missing (e.g. a logger crash),
    the window simply contains fewer rows instead of reaching further back.
    """
    # Sort by time and use the time as the index, so pandas can make time-based windows.
    ordered = group.sort_values(time_column)
    timed = ordered.set_index(time_column)

    new_columns: dict[str, object] = {}
    for window in windows:
        # "3min" means: rows with time in (t - 3 minutes, t], i.e. t-2, t-1 and t.
        roller = timed[PER_MINUTE_FEATURES + [IDLE_COLUMN]].rolling(f"{window}min")
        means = roller.mean()
        # ddof=0 gives 0 (not NaN) when the window holds a single row.
        stds = roller.std(ddof=0)

        for feature in PER_MINUTE_FEATURES:
            new_columns[rolling_feature_name(feature, "mean", window)] = means[feature].to_numpy()
            new_columns[rolling_feature_name(feature, "std", window)] = stds[feature].to_numpy()

        # Mean of a 0/1 column = share of idle minutes in the window.
        new_columns[idle_share_name(window)] = means[IDLE_COLUMN].to_numpy()

    rolled = pd.DataFrame(new_columns, index=ordered.index)
    # Rounding noise can make a std of identical values slightly non-zero or NaN; tidy it.
    return rolled.fillna(0.0)


def add_rolling_features(
    minutes: pd.DataFrame,
    time_column: str,
    group_column: str | None = None,
    windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS,
) -> pd.DataFrame:
    """
    Add rolling mean / std / idle-share features for every window length.

    In:  per-minute DataFrame that already has ratio features and is_idle;
         the datetime column name; optionally a column that separates recordings
         (Phase 0: one participant's block; Phase 1: None, there is only one user);
         the window lengths.
    Out: a copy with the rolling columns added, rows in the original order.
    Why: stress shows up over several minutes, not in one; rolling features capture that.
    """
    # Treat the whole table as one group when no group column is given.
    if group_column is None:
        groups = [minutes]
    else:
        groups = [group for _, group in minutes.groupby(group_column, sort=False)]

    # Compute the rolling columns group by group, then put them back in the original order.
    rolled_parts = [rolling_features_for_one_group(group, time_column, windows) for group in groups]
    rolled = pd.concat(rolled_parts).loc[minutes.index]

    return pd.concat([minutes, rolled], axis=1)


# ---------------------------------------------------------------------------
# 3. Full pipeline and feature list
# ---------------------------------------------------------------------------

def build_features(
    minutes: pd.DataFrame,
    time_column: str,
    group_column: str | None = None,
    windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS,
) -> pd.DataFrame:
    """
    Turn raw per-minute counts into all model features (before per-person normalisation).

    In:  per-minute DataFrame with RAW_COUNT_COLUMNS and a datetime column;
         optional group column; rolling window lengths.
    Out: a copy with ratio features, is_idle and rolling features added.
    Why: this is the single entry point used by Notebook 2 and by the live agent.
    """
    check_raw_columns(minutes)

    # Make sure the time column really is a datetime (the agent stores unix seconds).
    result = minutes.copy()
    if not pd.api.types.is_datetime64_any_dtype(result[time_column]):
        result[time_column] = pd.to_datetime(result[time_column], unit="s")

    result = add_ratio_features(result)
    result = add_idle_flag(result)
    result = add_rolling_features(result, time_column, group_column, windows)
    return result


def model_feature_names(windows: tuple[int, ...] = DEFAULT_ROLLING_WINDOWS) -> list[str]:
    """
    The full, ordered list of feature names the models use.

    In:  the rolling window lengths.
    Out: list of column names: per-minute features first, then for each window the
         rolling means and stds and the idle share.
    Why: the model needs the columns in exactly this order; Notebook 3 saves this list
         to features.json and the live app reads it back.
    """
    names = list(PER_MINUTE_FEATURES)
    for window in windows:
        for feature in PER_MINUTE_FEATURES:
            names.append(rolling_feature_name(feature, "mean", window))
            names.append(rolling_feature_name(feature, "std", window))
        names.append(idle_share_name(window))
    return names


# ---------------------------------------------------------------------------
# 4. Per-person normalisation (personal baseline)
# ---------------------------------------------------------------------------

def select_calibration_minutes(
    features: pd.DataFrame,
    time_column: str,
    active_minutes: int,
    person_column: str | None = None,
) -> pd.Series:
    """
    Mark each person's first `active_minutes` NON-idle minutes as the calibration period.

    In:  feature DataFrame (must contain is_idle), the datetime column, how many active
         minutes to use, and optionally the person column (None = one person).
    Out: a True/False Series (same index) — True for calibration minutes.
    Why: the live app learns the user's "normal" from their first active minutes after
         install. Phase 0 does the same with each SWELL participant's first minutes,
         so the evaluation matches what the app can really do.
    """
    is_calibration = pd.Series(False, index=features.index)

    # Treat the whole table as one person when no person column is given.
    if person_column is None:
        people = [features]
    else:
        people = [rows for _, rows in features.groupby(person_column, sort=False)]

    for rows in people:
        # Keep only minutes with some input, in time order, and take the first N.
        active_rows = rows[rows[IDLE_COLUMN] == 0].sort_values(time_column)
        first_rows = active_rows.head(active_minutes)
        is_calibration.loc[first_rows.index] = True

    return is_calibration


def compute_baseline(rows: pd.DataFrame, feature_names: list[str]) -> dict[str, dict[str, float]]:
    """
    Compute the personal baseline: the mean and standard deviation of every feature.

    In:  the baseline rows of ONE person (e.g. their calibration minutes) and the feature names.
    Out: {"feature name": {"mean": ..., "std": ...}, ...} — plain floats, so it can be saved as JSON.
    Why: z-scores against a personal baseline remove differences between people
         (some people simply type faster than others).
    """
    if len(rows) == 0:
        raise ValueError("Cannot compute a baseline from zero rows.")

    baseline: dict[str, dict[str, float]] = {}
    for name in feature_names:
        mean = float(rows[name].mean())
        std = float(rows[name].std(ddof=0))
        # A feature that never changed (std 0) would cause a division by zero.
        if not math.isfinite(std) or std < ZERO_STD_TOLERANCE:
            std = ZERO_STD_REPLACEMENT
        baseline[name] = {"mean": mean, "std": std}
    return baseline


def apply_baseline(
    features: pd.DataFrame, baseline: dict[str, dict[str, float]], feature_names: list[str]
) -> pd.DataFrame:
    """
    Replace each feature by its z-score against a personal baseline.

    In:  feature rows of ONE person, that person's baseline, and the feature names.
    Out: a copy where every listed feature = (value - baseline mean) / baseline std.
         Other columns (labels, time, ...) are left unchanged.
    Why: used in training (per SWELL participant) and live (with the user's saved baseline).
    """
    result = features.copy()
    for name in feature_names:
        result[name] = (result[name] - baseline[name]["mean"]) / baseline[name]["std"]
    return result


def normalise_per_person(
    features: pd.DataFrame,
    person_column: str,
    is_baseline_row: pd.Series,
    feature_names: list[str],
) -> tuple[pd.DataFrame, dict[str, dict[str, dict[str, float]]]]:
    """
    Z-score every person's features against their OWN baseline rows.

    In:  feature DataFrame for many people, the person column, a True/False Series saying
         which rows form each person's baseline, and the feature names.
    Out: (normalised copy of the DataFrame, {person: baseline}).
    Why: Phase 0 needs this for all 25 SWELL participants at once.
    """
    normalised_parts = []
    baselines: dict[str, dict[str, dict[str, float]]] = {}

    for person, rows in features.groupby(person_column, sort=False):
        # Learn this person's baseline from their baseline rows only ...
        baseline_rows = rows[is_baseline_row.loc[rows.index]]
        baseline = compute_baseline(baseline_rows, feature_names)
        baselines[str(person)] = baseline
        # ... and apply it to ALL of their rows.
        normalised_parts.append(apply_baseline(rows, baseline, feature_names))

    # Put the rows back in the original order.
    normalised = pd.concat(normalised_parts).loc[features.index]
    return normalised, baselines


def order_for_model(features: pd.DataFrame, feature_names: list[str]) -> pd.DataFrame:
    """
    Select the model's feature columns in the exact order the model was trained with.

    In:  a feature DataFrame and the ordered names (from features.json).
    Out: a DataFrame with exactly those columns, in that order.
    Why: models silently give wrong answers if the columns are in a different order.
    """
    missing = [name for name in feature_names if name not in features.columns]
    if missing:
        raise ValueError(f"Features missing for the model: {missing}")
    return features[feature_names]
