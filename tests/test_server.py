"""
tests/test_server.py — the local API (server/app.py) with FastAPI's TestClient:
pairing token and host checks, extension routes, dashboard routes, settings validation.
"""

import time

import pytest
from fastapi.testclient import TestClient

from server import app as server_app
from server.app import HOST, ServerContext, create_app, get_or_create_token
from server.categoriser import HeartbeatProcessor, TitleCategoriser
from tests.test_categoriser import FakeModel, consent


class FakeAgent:
    """Records what the dashboard asked the agent to do."""

    def __init__(self):
        self.paused = False
        self.calibration_restarts = 0
        self.deleted = False

    def status(self):
        return {"state": "Calm", "load_score": 40.0, "paused": self.paused,
                "calibration": {"complete": True, "collected": 0, "needed": 15}}

    def set_paused(self, paused):
        self.paused = paused

    def restart_calibration(self):
        self.calibration_restarts += 1

    def delete_all_data(self):
        self.deleted = True


class FakeKeychain:
    def __init__(self):
        self.key = None

    def get_api_key(self):
        return self.key

    def set_api_key(self, key):
        self.key = key

    def delete_api_key(self):
        self.key = None


@pytest.fixture
def parts(storage, config):
    consent(storage)
    keychain = FakeKeychain()
    agent = FakeAgent()
    categoriser = TitleCategoriser(storage, config, keychain.get_api_key, post=FakeModel("Learning"))
    heartbeats = HeartbeatProcessor(storage, config, categoriser)
    context = ServerContext(storage, config, categoriser, heartbeats, agent, keychain)
    client = TestClient(create_app(context), base_url="http://127.0.0.1:8765")
    client.headers["X-Commit-Token"] = get_or_create_token(storage)
    return {"client": client, "heartbeats": heartbeats, "agent": agent, "keychain": keychain}


@pytest.fixture
def client(parts):
    return parts["client"]


# ---------------------------------------------------------------- security

def test_listens_on_localhost_only():
    assert HOST == "127.0.0.1"


def test_token_is_required(client, storage):
    for method, path in [("get", "/api/status"), ("post", "/api/web/heartbeat"), ("get", "/api/settings"),
                         ("get", "/api/today"), ("post", "/api/pause"), ("delete", "/api/data")]:
        assert client.request(method.upper(), path, headers={"X-Commit-Token": ""}).status_code == 401
        assert client.request(method.upper(), path, headers={"X-Commit-Token": "wrong"}).status_code == 401
    assert storage.get_setting("pairing_token") == get_or_create_token(storage)   # token is stable


def test_other_hosts_are_refused(client):
    # A website that points its own domain at 127.0.0.1 ("DNS rebinding") is refused.
    assert client.get("/api/status", headers={"Host": "evil.example.com"}).status_code == 400
    assert client.get("/", headers={"Host": "evil.example.com"}).status_code == 400
    assert client.get("/api/status", headers={"Host": "localhost:8765"}).status_code == 200


def test_dashboard_page_contains_token(client, storage, tmp_path, monkeypatch):
    monkeypatch.setattr(server_app, "DASHBOARD_DIST", tmp_path)
    assert "not built yet" in client.get("/").text
    (tmp_path / "index.html").write_text("<html><head><title>Commit</title></head><body></body></html>")
    page = client.get("/")
    assert f'<meta name="commit-token" content="{get_or_create_token(storage)}">' in page.text
    assert page.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------- extension routes

def test_heartbeat_round_trip(parts, storage):
    client = parts["client"]
    response = client.post("/api/web/heartbeat", json={"domain": "www.youtube.com", "title": "Lecture 5", "seconds": 30})
    assert response.status_code == 202 and response.json() == {"accepted": True}
    parts["heartbeats"].process_pending()
    assert storage.execute("SELECT domain, category, seconds FROM web_time") == [("youtube.com", "Learning", 30)]


def test_heartbeat_validation(client):
    assert client.post("/api/web/heartbeat", json={"domain": "a.com", "seconds": 0}).status_code == 422
    assert client.post("/api/web/heartbeat", json={"category": "Work", "seconds": 5}).status_code == 400


def test_private_domains_crud(client):
    assert client.post("/api/private-domains", json={"domain": "https://www.Bank.com/login"}).json() == {"domains": ["bank.com"]}
    assert client.get("/api/private-domains").json() == {"domains": ["bank.com"]}
    assert client.post("/api/private-domains", json={"domain": "not a domain"}).status_code == 400
    assert client.request("DELETE", "/api/private-domains", json={"domain": "bank.com"}).json() == {"domains": []}


def test_status(client):
    body = client.get("/api/status").json()
    assert body["running"] and body["website_tracking"] and body["state"] == "Calm"


# ---------------------------------------------------------------- dashboard data

def test_today(client, storage):
    now = int(time.time()) // 60 * 60
    for offset, condition in [(-180, "neutral"), (-120, "interruptions"), (-60, "interruptions")]:
        storage.save_minute({"ts": now + offset, "mode": "active", "condition": condition, "load_score": 50.0})
    alert = storage.add_alert(now - 30, "break", "Load score above 70 in 13 of your last 20 active minutes")
    storage.set_alert_action(alert, "yes")
    storage.set_setting("user_name", "Asha")

    today = client.get("/api/today").json()
    assert today["name"] == "Asha"
    assert today["load_score"] == 40.0                       # the agent's live score wins
    stats = today["today"]
    # Minutes just before midnight belong to yesterday; only check what is certain.
    assert stats["active_minutes"] + today["yesterday"]["active_minutes"] == 3
    assert today["recent_alerts"][0]["reason"].startswith("Load score")
    conditions = [band["condition"] for band in today["timeline"]]
    assert conditions in (["neutral", "interruptions"], ["interruptions"], [])


def test_week_activity_and_pdf(client, storage):
    storage.save_web_time(int(time.time()), "youtube.com", "Learning", 120)
    week = client.get("/api/week").json()
    assert len(week["daily"]) == 7
    activity = client.get("/api/activity").json()
    assert activity["top_domains"] == [{"name": "youtube.com", "minutes": 2, "category": "Learning"}]
    assert "Work" in activity["categories_available"]
    pdf = client.get("/api/report/pdf", params={"start": "2026-11-16"})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert client.get("/api/week", params={"start": "16/11/2026"}).status_code == 400


def test_domain_rule(client, storage):
    assert client.put("/api/domain-rules", json={"domain": "example.com", "category": "Work"}).status_code == 200
    assert storage.domain_rules() == {"example.com": "Work"}
    assert client.put("/api/domain-rules", json={"domain": "example.com", "category": "Nonsense"}).status_code == 400


def test_alerts_and_feedback(client, storage):
    alert = storage.add_alert(100, "dnd", "reason")
    assert client.get("/api/alerts").json()["alerts"][0]["id"] == alert
    assert client.post(f"/api/alerts/{alert}/feedback", json={"feedback": "up"}).json() == {"id": alert, "feedback": "up"}
    assert storage.execute("SELECT feedback FROM alerts") == [("up",)]
    assert client.post("/api/alerts/999/feedback", json={"feedback": "up"}).status_code == 404
    assert client.post(f"/api/alerts/{alert}/feedback", json={"feedback": "maybe"}).status_code == 422


# ---------------------------------------------------------------- controls

def test_pause_resume_calibration_delete(parts):
    client, agent = parts["client"], parts["agent"]
    assert client.post("/api/pause").json() == {"paused": True} and agent.paused
    assert client.post("/api/resume").json() == {"paused": False} and not agent.paused
    client.post("/api/calibration/restart")
    assert agent.calibration_restarts == 1
    assert client.request("DELETE", "/api/data", json={}).status_code == 422          # needs the confirm word
    assert not agent.deleted
    assert client.request("DELETE", "/api/data", json={"confirm": "DELETE"}).json() == {"deleted": True}
    assert agent.deleted


def test_llm_test_endpoint(client, config):
    config.set("categoriser.mode", "local")
    assert client.post("/api/llm/test").json() == {"ok": True, "message": "Connected. Test answer: Learning"}


# ---------------------------------------------------------------- settings

def test_settings_read(client):
    settings = client.get("/api/settings").json()
    assert settings["dnd_mode"] == "ask"
    assert settings["categoriser"]["api"]["key_saved"] is False
    assert settings["calibration"]["needed"] == 15
    assert len(settings["pairing_token"]) > 20


def test_settings_update(parts, config, storage):
    client, keychain = parts["client"], parts["keychain"]
    response = client.put("/api/settings", json={
        "name": "Asha", "dnd_mode": "auto", "checkin_every_active_minutes": 60, "quiet_hours": ["22:00-08:00"],
        "retention_days": 14, "consent": {"title_api": True, "checkins": False},
        "categoriser_mode": "api", "api_base_url": "https://api.groq.com/openai/v1", "api_model": "qwen/qwen3-32b",
        "api_disable_thinking": True, "api_key": "gsk-test-key",
    })
    assert response.status_code == 200
    settings = response.json()
    assert settings["name"] == "Asha"
    assert settings["categoriser"]["effective_mode"] == "api"
    assert settings["categoriser"]["api"] == {"base_url": "https://api.groq.com/openai/v1", "model": "qwen/qwen3-32b",
                                              "disable_thinking": True, "key_saved": True}
    assert "gsk-test-key" not in response.text                 # the key is never sent back (P8)
    assert keychain.key == "gsk-test-key"
    assert config.get("categoriser.api")["extra_body"] == {"reasoning_effort": "none"}
    assert config.get("dnd.mode") == "auto" and config.get("checkins.enabled") is False
    assert config.get("data.retention_days") == 14
    assert storage.get_setting("consent")["choices"]["title_api"] is True

    client.put("/api/settings", json={"api_key": ""})
    assert keychain.key is None


@pytest.mark.parametrize("body", [
    {"quiet_hours": ["10pm-8am"]},
    {"retention_days": 0},
    {"checkin_every_active_minutes": 5},
    {"local_base_url": "https://some-cloud.example.com/v1"},     # "local" must really be local
    {"api_base_url": "http://insecure.example.com/v1"},
    {"consent": {"activity_counts": False}},                      # required switch cannot be withdrawn here
    {"categoriser_mode": "magic"},
])
def test_settings_validation(client, body):
    assert client.put("/api/settings", json=body).status_code in (400, 422)


def test_api_mode_requires_consent(client):
    response = client.put("/api/settings", json={"categoriser_mode": "api"})
    assert response.status_code == 400 and "switch 4" in response.json()["detail"]
