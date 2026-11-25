"""
tests/test_features.py — tests for shared/features.py.

Each test feeds small, hand-made per-minute data into a feature function and checks the
result against values worked out by hand. Run with:  pytest
"""

import math

import pandas as pd
import pytest

from shared import features as F


def make_minutes(rows: list[dict], start: str = "2024-01-01 10:00") -> pd.DataFrame:
    """
    Build a small per-minute DataFrame for tests.

    In:  a list of dicts with some raw counts (missing counts default to 0), and a start time.
    Out: a DataFrame with all raw count columns and a "time" column, one minute apart.
    """
    table = pd.DataFrame(rows)
    for name in F.RAW_COUNT_COLUMNS:
        if name not in table.columns:
            table[name] = 0
    table["time"] = pd.date_range(start, periods=len(table), freq="min")
    return table


# ---------------------------------------------------------------- ratio features

def test_ratio_features_known_values():
    minutes = make_minutes([{"keystrokes": 100, "error_keys": 10, "shortcut_keys": 5, "clicks": 20, "scrolls": 30}])
    result = F.add_ratio_features(minutes)
    assert result.loc[0, "error_key_ratio"] == pytest.approx(0.10)
    assert result.loc[0, "shortcut_ratio"] == pytest.approx(0.05)
    assert result.loc[0, "keyboard_share"] == pytest.approx(100 / 150)


def test_ratio_features_zero_denominator_gives_zero():
    # A minute with no key presses and no mouse input must not divide by zero.
    minutes = make_minutes([{"keystrokes": 0, "error_keys": 0, "clicks": 0, "scrolls": 0}])
    result = F.add_ratio_features(minutes)
    for name in F.RATIO_COLUMNS:
        assert result.loc[0, name] == 0.0


def test_ratio_features_do_not_change_input():
    minutes = make_minutes([{"keystrokes": 10}])
    F.add_ratio_features(minutes)
    assert "error_key_ratio" not in minutes.columns


# ---------------------------------------------------------------- idle flag

def test_idle_flag():
    minutes = make_minutes([
        {},                        # nothing at all -> idle
        {"mouse_distance": 5.0},   # only mouse movement -> active
        {"app_switches": 2},       # app switched with no input -> still idle
        {"keystrokes": 1},         # one key -> active
    ])
    result = F.add_idle_flag(minutes)
    assert result[F.IDLE_COLUMN].tolist() == [1, 0, 1, 0]


# ---------------------------------------------------------------- rolling features

def test_rolling_mean_and_std_known_values():
    minutes = make_minutes([{"keystrokes": k} for k in [10, 20, 30, 40]])
    result = F.build_features(minutes, time_column="time", windows=(3,))
    # Minute 4 (index 3): window holds 20, 30, 40 -> mean 30, population std sqrt(200/3).
    assert result.loc[3, "keystrokes_mean_3m"] == pytest.approx(30.0)
    assert result.loc[3, "keystrokes_std_3m"] == pytest.approx(math.sqrt(200 / 3))
    # First minute: window holds only itself -> mean = value, std = 0.
    assert result.loc[0, "keystrokes_mean_3m"] == pytest.approx(10.0)
    assert result.loc[0, "keystrokes_std_3m"] == 0.0


def test_rolling_uses_only_past_minutes():
    # A big value in the LAST minute must not change any earlier rolling value.
    minutes = make_minutes([{"keystrokes": k} for k in [1, 1, 1, 1000]])
    result = F.build_features(minutes, time_column="time", windows=(3,))
    assert result.loc[2, "keystrokes_mean_3m"] == pytest.approx(1.0)


def test_rolling_window_is_time_based_with_missing_minutes():
    # Minutes 10:00, 10:01, then a gap, then 10:05. The 3-minute window at 10:05
    # covers 10:03-10:05, so it must contain only the 10:05 row.
    minutes = make_minutes([{"keystrokes": k} for k in [10, 20, 99]])
    minutes.loc[2, "time"] = pd.Timestamp("2024-01-01 10:05")
    result = F.build_features(minutes, time_column="time", windows=(3,))
    assert result.loc[2, "keystrokes_mean_3m"] == pytest.approx(99.0)


def test_rolling_does_not_mix_groups():
    # Two people recorded at the same times: person B's rolling values use only B's rows.
    person_a = make_minutes([{"keystrokes": 100}, {"keystrokes": 100}])
    person_b = make_minutes([{"keystrokes": 0}, {"keystrokes": 0}])
    person_a["person"] = "A"
    person_b["person"] = "B"
    both = pd.concat([person_a, person_b], ignore_index=True)
    result = F.build_features(both, time_column="time", group_column="person", windows=(3,))
    assert result.loc[result["person"] == "B", "keystrokes_mean_3m"].tolist() == [0.0, 0.0]
    # Rows come back in the original order.
    assert result["person"].tolist() == ["A", "A", "B", "B"]


def test_idle_share():
    minutes = make_minutes([{}, {"keystrokes": 5}, {}, {"keystrokes": 5}, {"keystrokes": 5}])
    result = F.build_features(minutes, time_column="time", windows=(5,))
    # Last minute: 5 minutes in the window, 2 of them idle.
    assert result.loc[4, "idle_share_5m"] == pytest.approx(2 / 5)


def test_build_features_accepts_unix_seconds():
    # The live agent stores time as unix seconds; build_features converts it.
    minutes = make_minutes([{"keystrokes": 1}, {"keystrokes": 3}])
    minutes["time"] = [1_700_000_000, 1_700_000_060]
    result = F.build_features(minutes, time_column="time", windows=(3,))
    assert result.loc[1, "keystrokes_mean_3m"] == pytest.approx(2.0)


def test_build_features_missing_column_raises():
    minutes = make_minutes([{"keystrokes": 1}]).drop(columns=["clicks"])
    with pytest.raises(ValueError, match="clicks"):
        F.build_features(minutes, time_column="time")


def test_model_feature_names_all_built_and_unique():
    minutes = make_minutes([{"keystrokes": 1}] * 6)
    result = F.build_features(minutes, time_column="time")
    names = F.model_feature_names()
    assert len(names) == len(set(names))
    assert all(name in result.columns for name in names)
    # 10 per-minute features + for each of 2 windows: 10 means + 10 stds + 1 idle share.
    assert len(names) == 10 + 2 * (10 + 10 + 1)


# ---------------------------------------------------------------- normalisation

def test_compute_and_apply_baseline():
    rows = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    baseline = F.compute_baseline(rows, ["x"])
    assert baseline["x"]["mean"] == pytest.approx(2.0)
    assert baseline["x"]["std"] == pytest.approx(math.sqrt(2 / 3))
    normalised = F.apply_baseline(pd.DataFrame({"x": [2.0, 4.0]}), baseline, ["x"])
    assert normalised["x"].tolist() == pytest.approx([0.0, 2.0 / math.sqrt(2 / 3)])


def test_baseline_zero_std_is_replaced():
    baseline = F.compute_baseline(pd.DataFrame({"x": [5.0, 5.0]}), ["x"])
    assert baseline["x"]["std"] == F.ZERO_STD_REPLACEMENT


def test_baseline_from_no_rows_raises():
    with pytest.raises(ValueError):
        F.compute_baseline(pd.DataFrame({"x": []}), ["x"])


def test_calibration_skips_idle_minutes_and_is_per_person():
    table = pd.DataFrame({
        "person": ["A"] * 4 + ["B"] * 2,
        "time": pd.date_range("2024-01-01 10:00", periods=6, freq="min"),
        F.IDLE_COLUMN: [1, 0, 0, 0, 0, 0],
    })
    mask = F.select_calibration_minutes(table, "time", active_minutes=2, person_column="person")
    # Person A: the idle first minute is skipped, so minutes 2 and 3 are used.
    assert mask.tolist() == [False, True, True, False, True, True]


def test_normalise_per_person_uses_own_baseline():
    table = pd.DataFrame({"person": ["A", "A", "B", "B"], "x": [10.0, 20.0, 100.0, 300.0]})
    is_baseline = pd.Series([True, True, True, True])
    normalised, baselines = F.normalise_per_person(table, "person", is_baseline, ["x"])
    assert baselines["A"]["x"]["mean"] == pytest.approx(15.0)
    assert baselines["B"]["x"]["mean"] == pytest.approx(200.0)
    assert normalised["x"].tolist() == pytest.approx([-1.0, 1.0, -1.0, 1.0])


def test_order_for_model():
    table = pd.DataFrame({"b": [2], "a": [1], "label": ["x"]})
    assert F.order_for_model(table, ["a", "b"]).columns.tolist() == ["a", "b"]
    with pytest.raises(ValueError):
        F.order_for_model(table, ["a", "c"])
