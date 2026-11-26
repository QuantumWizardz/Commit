"""
tests/test_engine.py — the minute loop end to end with the REAL exported models:
counts → features → calibration → condition + load → database → decisions → alert flow.

No keyboard, mouse, clock or dialogs: everything is fed in by hand.
"""

import json
import random

import pytest

from agent.actions import AlertFlows, DndController
from agent.app_tracker import AppTracker
from agent.calibration import Calibration
from agent.detector import ConditionDetector
from agent.engine import Engine
from agent.feature_builder import FEATURE_SPEC_FILE, MODELS_DIR, load_feature_spec
from agent.load_scorer import LoadScorer
from agent.logger import InputCounter
from tests.conftest import FakeSystem

pytestmark = pytest.mark.skipif(not FEATURE_SPEC_FILE.exists(), reason="Run the Phase 0 notebooks first (models missing).")

START_TS = 1_700_000_040   # a minute boundary


class RecordingWorker:
    """Collects submitted dialog flows instead of running them on a thread."""

    def __init__(self):
        self.flows = []

    def submit(self, flow):
        self.flows.append(flow)
        return True

    def is_busy(self):
        return False


class AlwaysPressured:
    """Stand-in condition model that always says time pressure (to trigger DND rules)."""

    def predict(self, model_input):
        return "time_pressure", "time_pressure", {"interruptions": 0.1, "neutral": 0.1, "time_pressure": 0.8}

    def reset(self):
        pass


def active_counts(rng):
    """A believable active minute of counts."""
    return {
        "keystrokes": rng.randint(20, 150), "error_keys": rng.randint(0, 15), "shortcut_keys": rng.randint(0, 3),
        "pause_count": rng.randint(0, 8), "pause_total_seconds": rng.uniform(0, 30), "active_seconds": rng.randint(25, 60),
        "clicks": rng.randint(1, 15), "scrolls": rng.randint(0, 10), "mouse_distance": rng.uniform(500, 15000),
    }


def idle_counts():
    return {name: 0 for name in ["keystrokes", "error_keys", "shortcut_keys", "pause_count", "pause_total_seconds",
                                 "active_seconds", "clicks", "scrolls", "mouse_distance"]}


def app_summary(switches=2, category="Work"):
    return {"app_switches": switches, "app_seconds": {"Code": 50, "Slack": 10}, "main_app": "Code",
            "main_category": category, "app_categories": {"Code": "Work", "Slack": "Communication"}}


@pytest.fixture
def engine_parts(storage, config, tmp_path):
    """Build an Engine like agent/main.py does, but with fakes for the OS and the dialog thread."""
    spec = load_feature_spec()
    system = FakeSystem()
    tracker = AppTracker(lambda: "Code", sample_seconds=5, app_categories=config.get("app_categories"))
    tracker.take_sample()
    detector = ConditionDetector(MODELS_DIR / spec["condition_model"]["file"], config.get("detection.smoothing_minutes"))
    scorer = LoadScorer(MODELS_DIR / spec["load_model"]["file"], spec["feature_names"], storage, config)
    calibration = Calibration(storage, config.get("calibration.active_minutes"), spec["feature_names"])
    worker = RecordingWorker()
    dnd = DndController(system, storage, config)
    holder = {}
    flows = AlertFlows(system, storage, config, dnd, record_answer=lambda *a: holder["engine"].record_answer(*a))
    counter = InputCounter(2, 60)
    engine = Engine(config, storage, counter, tracker, calibration, detector, scorer, worker, flows, spec, system,
                    reports_folder=tmp_path / "reports")
    holder["engine"] = engine
    return engine, system, worker, storage


def run_minutes(engine, count, start_ts, rng, counts_fn=None):
    """Feed `count` minutes into the engine; returns the saved records."""
    records = []
    for index in range(count):
        ts = start_ts + index * 60
        counts = counts_fn() if counts_fn else active_counts(rng)
        records.append(engine.process_minute(ts, counts, app_summary(), now=ts + 60))
    return records


def test_calibration_then_predictions(engine_parts):
    engine, system, _, storage = engine_parts
    rng = random.Random(0)

    records = run_minutes(engine, 15, START_TS, rng)
    assert all(r["condition"] is None for r in records)          # no predictions while learning
    assert engine.calibration.is_complete()
    assert any("learned your normal pattern" in n for n in system.notifications)

    records = run_minutes(engine, 5, START_TS + 15 * 60, rng)
    for record in records:
        assert record["mode"] == "active"
        assert record["condition"] in ("neutral", "interruptions", "time_pressure")
        assert 0 <= record["load_score"] <= 100
        assert len(record["features"]) == len(load_feature_spec()["feature_names"])

    # Saved in the database.
    rows = storage.execute("SELECT condition, load_score, features_json FROM minutes WHERE condition IS NOT NULL")
    assert len(rows) == 5
    assert set(json.loads(rows[0][2])) == set(load_feature_spec()["feature_names"])
    assert engine.status["state"] in ("Calm", "Interrupted", "Pressured")


def test_idle_and_paused_minutes_have_no_predictions(engine_parts):
    engine, _, _, storage = engine_parts
    rng = random.Random(1)
    run_minutes(engine, 15, START_TS, rng)

    idle = engine.process_minute(START_TS + 15 * 60, idle_counts(), app_summary(switches=0), now=START_TS + 16 * 60)
    assert idle["mode"] == "idle" and idle["condition"] is None

    engine.set_paused(True)
    paused = engine.process_minute(START_TS + 16 * 60, active_counts(rng), app_summary(), now=START_TS + 17 * 60)
    assert paused["mode"] == "paused" and paused["condition"] is None
    assert engine.status["state"] == "Paused"
    assert storage.get_setting("paused") is True


def test_sustained_pressure_triggers_dnd_flow(engine_parts):
    engine, system, worker, storage = engine_parts
    rng = random.Random(2)
    run_minutes(engine, 15, START_TS, rng)              # calibration
    engine.detector = AlwaysPressured()

    run_minutes(engine, 14, START_TS + 15 * 60, rng)
    assert worker.flows == []                          # not yet 15 active minutes of pressure
    run_minutes(engine, 1, START_TS + 29 * 60, rng)
    assert len(worker.flows) == 1

    # Run the flow: the user clicks "Yes", then 👍.
    system.answers = ["Yes", "👍"]
    worker.flows[0]()
    assert system.shortcuts_run == ["Commit Focus On"]
    kind, reason, action, feedback = storage.execute("SELECT kind, reason, action, feedback FROM alerts")[0]
    assert (kind, action, feedback) == ("dnd", "yes", "up")
    assert "of your last 15 active minutes" in reason
    assert engine.decision_state.dnd_on_until > 0

    # DND is on now, so no new DND question next minute.
    run_minutes(engine, 1, START_TS + 30 * 60, rng)
    assert len(worker.flows) == 1


def test_checkin_due_after_45_active_minutes(engine_parts, config):
    engine, _, worker, storage = engine_parts
    storage.set_setting("consent", {"version": 1, "date": "2026-11-24", "choices": {"activity_counts": True, "checkins": True}})
    rng = random.Random(3)
    run_minutes(engine, 15, START_TS, rng)
    config.set("breaks.load_threshold", 101)     # make sure no break suggestion gets in the way
    config.set("dnd.sustained_minutes", 1000)    # and no DND question
    run_minutes(engine, 44, START_TS + 15 * 60, rng)
    assert worker.flows == []
    run_minutes(engine, 1, START_TS + 59 * 60, rng)
    assert len(worker.flows) == 1
    assert engine.active_minutes_since_checkin == 0


def test_chrome_without_heartbeat_is_miscellaneous(engine_parts):
    # P5: Chrome in front but the extension sent nothing (e.g. incognito) -> "Miscellaneous", no detail.
    engine, _, _, storage = engine_parts

    class NoHeartbeats:
        def take_received_seconds(self):
            return 0

        def take_commit_seconds(self):
            return 0

        def current_domain(self, max_age_seconds):
            return None

    engine.heartbeats = NoHeartbeats()
    chrome_minute = {"app_switches": 0, "app_seconds": {"Google Chrome": 60}, "main_app": "Google Chrome",
                     "main_category": "Other", "app_categories": {"Google Chrome": "Other"}}
    engine.process_minute(START_TS, active_counts(random.Random(4)), chrome_minute, now=START_TS + 60)
    assert storage.execute("SELECT domain, category, seconds FROM web_time") == [(None, "Miscellaneous", 60)]


class FakeHeartbeats:
    """The extension reported `received` website seconds, `commit` of them on the Commit dashboard."""

    def __init__(self, received, commit):
        self.received, self.commit = received, commit

    def take_received_seconds(self):
        value, self.received = self.received, 0
        return value

    def take_commit_seconds(self):
        value, self.commit = self.commit, 0
        return value

    def current_domain(self, max_age_seconds):
        return None


def test_commit_dashboard_and_dialogs_are_never_counted(engine_parts):
    engine, _, _, storage = engine_parts
    rng = random.Random(5)

    # Mostly on the Commit dashboard (50 s of 60 s in Brave) -> a "commit" minute: nothing counted.
    engine.heartbeats = FakeHeartbeats(received=50, commit=50)
    minute = {"app_switches": 1, "app_seconds": {"Brave Browser": 50, "Code": 10}, "main_app": "Brave Browser",
              "main_category": "Other", "app_categories": {"Brave Browser": "Other", "Code": "Work"}}
    record = engine.process_minute(START_TS, active_counts(rng), minute, now=START_TS + 60)
    assert record["mode"] == "commit" and record["condition"] is None
    assert storage.execute("SELECT COUNT(*) FROM app_time")[0][0] == 0
    assert storage.execute("SELECT COUNT(*) FROM web_time")[0][0] == 0
    assert engine.calibration.progress()[0] == 0              # not used for calibration either

    # A little Commit (a dialog via osascript + 10 s of dashboard): removed, the rest is counted normally.
    engine.heartbeats = FakeHeartbeats(received=10, commit=10)
    minute = {"app_switches": 2, "app_seconds": {"Code": 40, "Brave Browser": 15, "osascript": 5}, "main_app": "Code",
              "main_category": "Work", "app_categories": {"Code": "Work", "Brave Browser": "Other", "osascript": "Other"}}
    record = engine.process_minute(START_TS + 60, active_counts(rng), minute, now=START_TS + 120)
    assert record["mode"] == "active"
    assert sorted(storage.execute("SELECT app_name, seconds FROM app_time")) == [("Brave Browser", 5), ("Code", 40)]
    assert storage.execute("SELECT COUNT(*) FROM web_time")[0][0] == 0   # no "Miscellaneous" for the Commit seconds


def test_lock_screen_time_is_never_counted(engine_parts):
    engine, _, _, storage = engine_parts
    rng = random.Random(6)
    engine.heartbeats = None
    minute = {"app_switches": 1, "app_seconds": {"loginwindow": 50, "Code": 10}, "main_app": "loginwindow",
              "main_category": "Other", "app_categories": {"loginwindow": "Other", "Code": "Work"}}
    record = engine.process_minute(START_TS, active_counts(rng), minute, now=START_TS + 60)
    assert record["mode"] != "commit" and record["app_category"] == "Work"   # the lock screen is not the main app
    assert storage.execute("SELECT app_name, seconds FROM app_time") == [("Code", 10)]

    only_locked = {"app_switches": 0, "app_seconds": {"loginwindow": 60}, "main_app": "loginwindow",
                   "main_category": "Other", "app_categories": {"loginwindow": "Other"}}
    engine.process_minute(START_TS + 60, {**active_counts(rng), "active_seconds": 0}, only_locked, now=START_TS + 120)
    assert storage.execute("SELECT COUNT(*) FROM app_time WHERE app_name = 'loginwindow'")[0][0] == 0


def test_app_categories_are_read_live():
    from agent.app_tracker import AppTracker
    table = {"Slack": "Communication"}
    tracker = AppTracker(lambda: "Slack", sample_seconds=5, app_categories=lambda: dict(table))
    tracker.take_sample()
    assert tracker.snapshot_and_reset()["main_category"] == "Communication"
    table["Slack"] = "Work"                    # changed on the dashboard
    tracker.take_sample()
    assert tracker.snapshot_and_reset()["main_category"] == "Work"
