"""
tests/test_devlog.py — Developer mode: the in-memory event log (agent/devlog.py), the decision
explanation (decisions.explain), the events the engine and heartbeat worker add, and the
/api/dev routes. Includes the privacy checks: nothing is recorded while developer mode is off,
titles never reach the log, and private sites appear without a name.
"""

import json
import random
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from agent import decisions
from agent.devlog import DEVELOPER_MODE_KEY, DevLog, developer_mode_on
from agent.feature_builder import FEATURE_SPEC_FILE
from server.app import ServerContext, create_app, get_or_create_token
from server.categoriser import HeartbeatProcessor
from tests.test_categoriser import FakeModel, consent, make
from tests.test_engine import START_TS, engine_parts, run_minutes  # noqa: F401 (engine_parts is a fixture)
from tests.test_server import FakeAgent, FakeKeychain

SECRET_TITLE = "Secret medical results for Jane"


# ---------------------------------------------------------------- the log itself

def test_devlog_records_only_when_enabled():
    enabled = {"on": False}
    log = DevLog(lambda: enabled["on"], clock=lambda: 100.0)
    log.add("activity", "ignored")
    assert log.since() == [] and log.last_id() == 0

    enabled["on"] = True
    log.add("activity", "first", keystrokes=3)
    log.add("prediction", "second", kind="not the event kind")   # detail names may clash with parameter names
    events = log.since()
    assert [e["message"] for e in events] == ["first", "second"]
    assert events[0] == {"id": 1, "ts": 100.0, "kind": "activity", "message": "first", "data": {"keystrokes": 3}}
    assert events[1]["kind"] == "prediction" and events[1]["data"]["kind"] == "not the event kind"
    assert [e["id"] for e in log.since(1)] == [2]


def test_devlog_is_a_ring_buffer_and_clear_keeps_ids_increasing():
    log = DevLog(lambda: True, max_events=3)
    for number in range(5):
        log.add("system", f"event {number}")
    assert [e["message"] for e in log.since()] == ["event 2", "event 3", "event 4"]
    log.clear()
    assert log.since() == []
    log.add("system", "after clear")
    assert log.since()[0]["id"] == 6


def test_devlog_never_raises_when_the_switch_check_fails():
    def broken():
        raise RuntimeError("database closed")
    log = DevLog(broken)
    log.add("system", "x")          # must not raise
    assert log.since() == []


def test_developer_mode_setting(storage):
    assert developer_mode_on(storage) is False
    storage.set_setting(DEVELOPER_MODE_KEY, True)
    assert developer_mode_on(storage) is True


# ---------------------------------------------------------------- decision explanation

def test_explain_matches_decide(config):
    state = decisions.DecisionState()
    now, now_local = 1_000_000.0, datetime(2026, 11, 25, 11, 0)
    pressured = [{"condition": "time_pressure", "load_score": 90, "app_category": "Work"}] * 20

    checks = decisions.explain(pressured, now, now_local, state, config, "Code")
    assert checks["pressure_sustained"] and checks["load_high"]
    assert checks["reason"] == "rules met"
    assert decisions.decide(pressured, now, now_local, state, config, "Code") is not None

    calm = [{"condition": "neutral", "load_score": 10, "app_category": "Work"}] * 20
    assert decisions.explain(calm, now, now_local, state, config, "Code")["reason"] == "no sustained pressure or high load"
    assert decisions.explain(calm[:2], now, now_local, state, config, "Code")["reason"].startswith("not enough history")

    in_call = decisions.explain(pressured, now, now_local, state, config, config.get("quiet.call_apps")[0])
    assert in_call["in_call"] and in_call["reason"].startswith("never interrupt")

    state.dnd_ask_blocked_until = now + 120
    state.break_blocked_until = now + 60
    blocked = decisions.explain(pressured, now, now_local, state, config, "Code")
    assert blocked["dnd_blocked_seconds"] == 120 and "cooldown" in blocked["reason"]


# ---------------------------------------------------------------- website events

@pytest.fixture
def heartbeat_parts(storage, config):
    consent(storage)
    storage.set_setting(DEVELOPER_MODE_KEY, True)
    log = DevLog(lambda: developer_mode_on(storage))
    processor = HeartbeatProcessor(storage, config, make(storage, config, FakeModel("Learning")), dev_log=log)
    return processor, log


def test_heartbeat_events_show_domain_category_and_source(heartbeat_parts):
    processor, log = heartbeat_parts
    processor.submit("youtube.com", "Linear algebra lecture", None, 30)
    processor.process_pending()
    event = log.since()[-1]
    assert event["kind"] == "website"
    assert event["data"] == {"domain": "youtube.com", "category": "Learning", "seconds": 30, "source": "local model"}

    processor.submit("youtube.com", "Linear algebra lecture", None, 30)   # same title again: from the cache
    processor.process_pending()
    assert log.since()[-1]["data"]["source"] == "cache"


def test_titles_and_private_domains_never_reach_the_log(heartbeat_parts, storage):
    processor, log = heartbeat_parts
    storage.add_private_domain("mybank.com")
    processor.submit("youtube.com", SECRET_TITLE, None, 30)
    processor.submit("online.mybank.com", SECRET_TITLE, None, 30)        # extension missed it: server safety net
    processor.submit(None, None, "Private", 30)
    processor.process_pending()

    text = json.dumps(log.since())
    assert "Secret" not in text and "Jane" not in text
    assert "mybank" not in text
    assert [e["data"]["category"] for e in log.since()][-2:] == ["Private", "Private"]


def test_nothing_logged_when_developer_mode_is_off(heartbeat_parts, storage):
    processor, log = heartbeat_parts
    storage.set_setting(DEVELOPER_MODE_KEY, False)
    processor.submit("youtube.com", "A lecture", None, 30)
    processor.process_pending()
    assert log.since() == []


# ---------------------------------------------------------------- engine events (real models)

@pytest.mark.skipif(not FEATURE_SPEC_FILE.exists(), reason="Run the Phase 0 notebooks first (models missing).")
def test_engine_logs_activity_calibration_predictions_and_decisions(engine_parts):
    engine, _, _, storage = engine_parts
    storage.set_setting(DEVELOPER_MODE_KEY, True)
    engine.dev_log = DevLog(lambda: developer_mode_on(storage))
    rng = random.Random(4)

    run_minutes(engine, 15, START_TS, rng)              # calibration
    run_minutes(engine, 2, START_TS + 15 * 60, rng)     # predictions
    events = engine.dev_log.since()
    kinds = [e["kind"] for e in events]
    assert kinds.count("activity") == 17
    assert kinds.count("calibration") == 15
    assert kinds.count("prediction") == 2 and kinds.count("decision") == 2

    activity = next(e for e in events if e["kind"] == "activity")
    assert activity["data"]["counts"]["keystrokes"] >= 0 and activity["data"]["app_seconds"] == {"Code": 50, "Slack": 10}
    prediction = next(e for e in events if e["kind"] == "prediction")
    assert set(prediction["data"]) >= {"raw_condition", "condition", "probabilities", "load_score", "features"}
    decision = next(e for e in events if e["kind"] == "decision")
    assert decision["message"].startswith("No alert") and "reason" in decision["data"]["checks"]

    engine.set_paused(True)
    assert engine.dev_log.since()[-1]["message"] == "Tracking paused"


# ---------------------------------------------------------------- API routes

@pytest.fixture
def dev_client(storage, config):
    consent(storage)
    log = DevLog(lambda: developer_mode_on(storage))
    categoriser = make(storage, config, FakeModel("Learning"))
    heartbeats = HeartbeatProcessor(storage, config, categoriser, dev_log=log)
    context = ServerContext(storage, config, categoriser, heartbeats, FakeAgent(), FakeKeychain(), dev_log=log)
    client = TestClient(create_app(context), base_url="http://127.0.0.1:8765")
    client.headers["X-Commit-Token"] = get_or_create_token(storage)
    return client, heartbeats, log


def test_dev_routes_are_refused_while_developer_mode_is_off(dev_client):
    client, _, _ = dev_client
    assert client.get("/api/settings").json()["developer_mode"] is False
    for method, path in [("GET", "/api/dev/events"), ("GET", "/api/dev/snapshot"), ("DELETE", "/api/dev/events")]:
        assert client.request(method, path).status_code == 403
    assert client.get("/api/dev/events", headers={"X-Commit-Token": "wrong"}).status_code == 401


def test_dev_routes_when_on(dev_client, storage):
    client, heartbeats, log = dev_client
    assert client.put("/api/settings", json={"developer_mode": True}).json()["developer_mode"] is True

    client.post("/api/web/heartbeat", json={"domain": "github.com", "title": "PR #1", "seconds": 30})
    heartbeats.process_pending()
    storage.save_minute({"ts": 60, "mode": "active", "app_category": "Work", "features": {"keystrokes": 1.5},
                         "condition": "neutral", "condition_probs": {"neutral": 0.9}, "load_score": 20.0})

    events = client.get("/api/dev/events").json()
    assert [e["message"] for e in events["events"]][0] == "Developer mode turned on"
    assert events["events"][-1]["data"]["domain"] == "github.com"
    assert client.get(f"/api/dev/events?after={events['last_id']}").json()["events"] == []

    snapshot = client.get("/api/dev/snapshot").json()
    assert snapshot["status"]["state"] == "Calm"
    assert snapshot["minutes"][0]["features"] == {"keystrokes": 1.5}
    assert snapshot["minutes"][0]["condition_probs"] == {"neutral": 0.9}
    assert snapshot["web_time"][0]["domain"] == "github.com"
    assert snapshot["row_counts"]["web_time"] == 1
    assert "dnd" in snapshot["rules"]

    assert client.delete("/api/dev/events").json() == {"cleared": True}
    assert client.get("/api/dev/events").json()["events"] == []


def test_turning_developer_mode_off_forgets_the_log(dev_client):
    client, _, log = dev_client
    client.put("/api/settings", json={"developer_mode": True})
    assert log.since() != []
    client.put("/api/settings", json={"developer_mode": False})
    assert log.since() == []
