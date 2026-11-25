"""
tests/test_decisions.py — DND and break rules, cooldowns, snooze, quiet hours, call apps,
plus smoothing, activity mode, calibration and the personal load calibration.
"""

from datetime import datetime

import pandas as pd
import pytest

from agent import decisions as D
from agent.calibration import Calibration
from agent.detector import most_common_recent
from agent.feature_builder import MODE_ACTIVE, MODE_IDLE, MODE_PASSIVE, activity_mode
from agent.load_scorer import apply_personal_calibration, fit_personal_calibration

NOW = 1_700_000_000.0
DAYTIME = datetime(2026, 11, 24, 14, 0)


def minutes(conditions, load=50.0, category="Work"):
    """Build a list of recent active minutes."""
    return [{"condition": c, "load_score": load, "app_category": category, "app_switches": 1} for c in conditions]


# ---------------------------------------------------------------- DND

def test_no_alert_without_enough_history(config):
    recent = minutes(["time_pressure"] * 14)
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Code") is None


def test_dnd_when_pressure_sustained(config):
    recent = minutes(["neutral"] * 7 + ["interruptions"] * 8)   # 8 of 15 = "most"
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Code") == D.DND


def test_no_dnd_when_pressure_is_only_half(config):
    recent = minutes(["neutral"] * 8 + ["interruptions"] * 7)
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Code") is None


def test_not_now_blocks_dnd_for_cooldown(config):
    recent = minutes(["interruptions"] * 15)
    state = D.after_dnd_answer(D.DecisionState(), "not_now", NOW, config)
    cooldown = config.get("dnd.ask_cooldown_minutes") * 60
    assert D.decide(recent, NOW + cooldown - 1, DAYTIME, state, config, "Code") is None
    assert D.decide(recent, NOW + cooldown, DAYTIME, state, config, "Code") == D.DND


def test_yes_turns_dnd_on_and_blocks_until_after_it_ends(config):
    recent = minutes(["interruptions"] * 15)
    state = D.after_dnd_answer(D.DecisionState(), "yes", NOW, config)
    duration = config.get("dnd.duration_minutes") * 60
    cooldown = config.get("dnd.ask_cooldown_minutes") * 60
    assert state.dnd_on_until == NOW + duration
    assert D.decide(recent, NOW + duration + 1, DAYTIME, state, config, "Code") is None
    assert D.decide(recent, NOW + duration + cooldown, DAYTIME, state, config, "Code") == D.DND


# ---------------------------------------------------------------- breaks

def test_break_when_load_high(config):
    recent = minutes(["neutral"] * 8 + ["neutral"] * 12, load=0)
    for minute in recent[-12:]:        # 12 of 20 = 60 % above 70
        minute["load_score"] = 80
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Code") == D.BREAK


def test_no_break_below_high_fraction(config):
    recent = minutes(["neutral"] * 20, load=0)
    for minute in recent[-11:]:        # 11 of 20 = 55 %
        minute["load_score"] = 80
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Code") is None


def test_break_cooldown_and_snooze(config):
    recent = minutes(["neutral"] * 20, load=90)
    cooldown = config.get("breaks.cooldown_minutes") * 60

    state = D.after_break_answer(D.DecisionState(), "dismiss", NOW, config)
    assert D.decide(recent, NOW + cooldown - 1, DAYTIME, state, config, "Code") is None
    assert D.decide(recent, NOW + cooldown, DAYTIME, state, config, "Code") == D.BREAK

    # Snooze 30 asks again after exactly 30 minutes, even though the cooldown is 45.
    state = D.after_break_answer(D.DecisionState(), "snooze_30", NOW, config)
    assert D.decide(recent, NOW + 30 * 60, DAYTIME, state, config, "Code") == D.BREAK
    state = D.after_break_answer(D.DecisionState(), "snooze_60", NOW, config)
    assert D.decide(recent, NOW + 59 * 60, DAYTIME, state, config, "Code") is None


# ---------------------------------------------------------------- both at once

def test_both_wanted_interruptions_pattern_prefers_dnd(config):
    recent = minutes(["neutral"] * 5 + ["interruptions"] * 15, load=90)
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Code") == D.DND


def test_both_wanted_time_pressure_pattern_prefers_break(config):
    recent = minutes(["neutral"] * 5 + ["time_pressure"] * 15, load=90)
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Code") == D.BREAK


def test_both_wanted_with_lots_of_communication_prefers_dnd(config):
    recent = minutes(["neutral"] * 5 + ["time_pressure"] * 15, load=90, category="Communication")
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Code") == D.DND


# ---------------------------------------------------------------- never interrupt

def test_no_alert_during_call(config):
    recent = minutes(["interruptions"] * 20, load=90)
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "zoom.us") is None
    assert D.decide(recent, NOW, DAYTIME, D.DecisionState(), config, "Chrome", current_domain="meet.google.com") is None


def test_no_alert_in_quiet_hours(config):
    config.set("quiet.quiet_hours", ["22:00-08:00"])
    recent = minutes(["interruptions"] * 20, load=90)
    assert D.decide(recent, NOW, datetime(2026, 11, 24, 23, 30), D.DecisionState(), config, "Code") is None
    assert D.decide(recent, NOW, datetime(2026, 11, 24, 7, 59), D.DecisionState(), config, "Code") is None
    assert D.decide(recent, NOW, datetime(2026, 11, 24, 8, 0), D.DecisionState(), config, "Code") == D.DND


def test_quiet_hours_same_day_range():
    assert D.in_quiet_hours(datetime(2026, 1, 1, 12, 30), ["12:00-13:00"])
    assert not D.in_quiet_hours(datetime(2026, 1, 1, 13, 0), ["12:00-13:00"])


def test_decision_state_round_trip():
    state = D.DecisionState(dnd_on_until=1.0, dnd_ask_blocked_until=2.0, break_blocked_until=3.0)
    assert D.DecisionState.from_dict(state.to_dict()) == state
    assert D.DecisionState.from_dict(None) == D.DecisionState()


# ---------------------------------------------------------------- smoothing, activity mode

def test_smoothing_most_common_with_recent_tie_break():
    assert most_common_recent(["neutral", "time_pressure", "neutral"]) == "neutral"
    assert most_common_recent(["neutral", "interruptions"]) == "interruptions"
    assert most_common_recent(["interruptions", "neutral", "neutral", "interruptions"]) == "interruptions"


def test_activity_mode():
    passive = ["Entertainment", "Learning"]
    assert activity_mode(3, "Work", 5, 20, passive) == MODE_IDLE
    assert activity_mode(10, "Entertainment", 5, 20, passive) == MODE_PASSIVE
    assert activity_mode(10, "Work", 5, 20, passive) == MODE_ACTIVE
    assert activity_mode(30, "Entertainment", 5, 20, passive) == MODE_ACTIVE


# ---------------------------------------------------------------- calibration

def test_calibration_completes_after_n_minutes_and_restarts(storage):
    calibration = Calibration(storage, active_minutes=3, feature_names=["x"])
    assert not calibration.add_minute({"x": 1.0})
    assert not calibration.add_minute({"x": 2.0})
    assert calibration.progress() == (2, 3)
    assert calibration.add_minute({"x": 3.0})
    assert calibration.is_complete()
    assert calibration.baseline()["x"]["mean"] == pytest.approx(2.0)
    calibration.restart()
    assert not calibration.is_complete()
    assert calibration.progress() == (0, 3)


# ---------------------------------------------------------------- personal load calibration

def test_personal_calibration_learns_direction():
    # Higher model probability goes with higher ratings -> positive slope.
    pairs = [(0.1, 1), (0.2, 2), (0.3, 2), (0.6, 4), (0.8, 5), (0.9, 5)]
    fitted = fit_personal_calibration(pairs)
    assert fitted["coef"] > 0
    assert apply_personal_calibration(0.9, fitted) > apply_personal_calibration(0.1, fitted)


def test_personal_calibration_needs_variety():
    assert fit_personal_calibration([(0.2, 3), (0.8, 3), (0.5, 3)]) is None


def test_config_override_is_saved(config, storage):
    assert config.get("dnd.mode") == "ask"
    config.set("dnd.mode", "auto")
    assert config.get("dnd.mode") == "auto"
    with pytest.raises(KeyError):
        config.set("no.such_setting", 1)


def test_next_minute_boundary():
    from agent.engine import next_minute_boundary
    assert next_minute_boundary(120.0) == 180       # exactly on a boundary -> the next one
    assert next_minute_boundary(179.999) == 180
    assert next_minute_boundary(181.5) == 240
