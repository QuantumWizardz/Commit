"""
server/app.py — the local web server (README sections 5 and 14), FastAPI on 127.0.0.1 only (P6).

Extension routes (Phase 2)
  POST   /api/web/heartbeat       {domain?, title?, category?, seconds}; title used, then discarded
  GET    /api/private-domains     the "Don't track" list
  POST   /api/private-domains     {domain} add one
  DELETE /api/private-domains     {domain} remove one
  GET    /api/status              is Commit running, current state

Dashboard routes (Phase 3)
  GET    /api/today               Home screen: stat cards, today's timeline, recent alerts
  GET    /api/week?start=…        weekly report data          GET /api/report/pdf?start=…  PDF
  GET    /api/activity?start=…    categories, apps, domains, day-by-day
  PUT    /api/domain-rules        {domain, category} user correction → rule for the future
  GET    /api/alerts              alert history               POST /api/alerts/{id}/feedback  👍/👎
  GET    /api/settings            all settings                PUT  /api/settings  change some
  POST   /api/llm/test            test the language-model connection
  POST   /api/calibration/restart re-run calibration
  POST   /api/pause, /api/resume  pause / resume tracking (P10)
  DELETE /api/data                delete all my data (P9)
  GET    /                        the dashboard itself (dashboard/dist)

Security: every /api request must carry the pairing token in the X-Commit-Token header.
The extension gets it from the user; the dashboard page gets it embedded when it is served
(only a page on 127.0.0.1 can read it). Requests whose Host is not 127.0.0.1/localhost are refused,
which blocks "DNS rebinding" tricks by other websites. No CORS headers are ever sent.
"""

from __future__ import annotations

import html
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from server import report
from server.categoriser import SPECIAL_CATEGORIES, HeartbeatProcessor, TitleCategoriser, normalise_domain

log = logging.getLogger(__name__)

TOKEN_KEY = "pairing_token"
USER_NAME_KEY = "user_name"
CONSENT_KEY = "consent"
HOST = "127.0.0.1"                      # never listen on other network interfaces (P6)
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
MAX_TITLE_CHARS = 1000                  # longer titles are rejected (they are cut to 120 before any model anyway)
DOMAIN_PATTERN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
QUIET_PERIOD_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")
LOCAL_MODEL_HOSTS = ("http://127.0.0.1", "http://localhost")
SERVER_START_WAIT_SECONDS = 3
DAYS_IN_WEEK = 7
RECENT_ALERTS_ON_HOME = 5
ALERT_HISTORY_LIMIT = 200
ACTIVITY_TOP_ITEMS = 20                 # the Activity page lists more domains than the PDF
OPTIONAL_CONSENTS = ("website_tracking", "title_local", "title_api", "checkins")
NO_THINKING = {"reasoning_effort": "none"}   # turns off "thinking" in reasoning models (e.g. Qwen 3)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIST = PROJECT_ROOT / "dashboard" / "dist"
DASHBOARD_MISSING_PAGE = (
    "<!doctype html><title>Commit</title><body style='font-family:sans-serif;padding:40px'>"
    "<h1>The dashboard is not built yet</h1><p>Run <code>cd dashboard &amp;&amp; npm install &amp;&amp; npm run build</code>, "
    "then reload this page.</p></body>"
)


def get_or_create_token(storage) -> str:
    """The pairing token; created (random, URL-safe) the first time."""
    token = storage.get_setting(TOKEN_KEY)
    if token is None:
        token = secrets.token_urlsafe(24)
        storage.set_setting(TOKEN_KEY, token)
    return token


@dataclass
class ServerContext:
    """
    Everything the routes need from the rest of the app.

    agent:    object with status() -> dict, set_paused(bool), restart_calibration(), delete_all_data()
    keychain: object with get_api_key(), set_api_key(key), delete_api_key()   (agent/keychain.py)
    """
    storage: object
    config: object
    categoriser: TitleCategoriser
    heartbeats: HeartbeatProcessor
    agent: object
    keychain: object


# ---------------------------------------------------------------- request bodies

class Heartbeat(BaseModel):
    domain: str | None = Field(default=None, max_length=253)
    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    category: str | None = None
    seconds: int = Field(ge=1)


class DomainBody(BaseModel):
    domain: str = Field(max_length=253)


class DomainRule(BaseModel):
    domain: str = Field(max_length=253)
    category: str


class FeedbackBody(BaseModel):
    feedback: Literal["up", "down"]


class DeleteBody(BaseModel):
    confirm: Literal["DELETE"]           # the dashboard must send this exact word


class SettingsUpdate(BaseModel):
    """Every field is optional: only the ones sent are changed."""
    name: str | None = Field(default=None, max_length=60)
    categoriser_mode: Literal["off", "rules", "local", "api"] | None = None
    local_base_url: str | None = Field(default=None, max_length=200)
    local_model: str | None = Field(default=None, max_length=100)
    api_base_url: str | None = Field(default=None, max_length=200)
    api_model: str | None = Field(default=None, max_length=100)
    api_disable_thinking: bool | None = None
    api_key: str | None = Field(default=None, max_length=500)       # "" removes the saved key
    dnd_mode: Literal["ask", "auto"] | None = None
    checkin_every_active_minutes: int | None = Field(default=None, ge=15, le=240)
    quiet_hours: list[str] | None = None
    retention_days: int | None = Field(default=None, ge=1, le=365)
    consent: dict[str, bool] | None = None


# ---------------------------------------------------------------- small helpers

def clean_domain(raw: str) -> str:
    """Normalise a domain typed by the user and check that it looks like one (else HTTP 400)."""
    domain = normalise_domain(raw.replace("https://", "").replace("http://", "").split("/")[0])
    if not DOMAIN_PATTERN.match(domain):
        raise HTTPException(status_code=400, detail="That does not look like a website domain (example: bank.com).")
    return domain


def parse_start(start: str | None) -> date:
    """Report start date from ?start=YYYY-MM-DD; default = the last 7 days including today."""
    if start is None:
        return date.today() - timedelta(days=DAYS_IN_WEEK - 1)
    try:
        return date.fromisoformat(start)
    except ValueError:
        raise HTTPException(status_code=400, detail="start must look like 2026-11-23")


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


# ---------------------------------------------------------------- settings

def read_settings(context: ServerContext) -> dict:
    """Everything the Settings screen shows. The API key itself is never returned, only whether one is saved."""
    storage, config = context.storage, context.config
    status = context.agent.status()
    api = config.get("categoriser.api")
    local = config.get("categoriser.local")
    return {
        "name": storage.get_setting(USER_NAME_KEY, ""),
        "categoriser": {
            "mode": config.get("categoriser.mode"),
            "effective_mode": context.categoriser.effective_mode(),
            "local": {"base_url": local["base_url"], "model": local["model"]},
            "api": {"base_url": api["base_url"], "model": api["model"],
                    "disable_thinking": (api.get("extra_body") or {}) == NO_THINKING,
                    "key_saved": bool(context.keychain.get_api_key())},
        },
        "dnd_mode": config.get("dnd.mode"),
        "checkin_every_active_minutes": config.get("checkins.every_active_minutes"),
        "quiet_hours": config.get("quiet.quiet_hours"),
        "retention_days": config.get("data.retention_days"),
        "pairing_token": get_or_create_token(storage),
        "paused": status.get("paused", False),
        "calibration": status.get("calibration"),
        "consent": storage.get_setting(CONSENT_KEY),
        "categories": config.get("categoriser.categories"),
    }


def apply_consent(context: ServerContext, changes: dict[str, bool]) -> None:
    """Change optional consent switches. Activity counts (required) cannot be withdrawn here."""
    unknown = set(changes) - set(OPTIONAL_CONSENTS)
    if unknown:
        raise bad_request(f"These consent switches cannot be changed here: {sorted(unknown)}. "
                          "To stop Commit completely, use Delete all my data or the menu bar.")
    saved = context.storage.get_setting(CONSENT_KEY) or {"choices": {"activity_counts": True}}
    choices = {**saved["choices"], **changes}
    context.storage.set_setting(CONSENT_KEY, {"version": saved.get("version", 1), "date": date.today().isoformat(), "choices": choices})
    if "checkins" in changes:
        context.config.set("checkins.enabled", changes["checkins"])


def check_categoriser_mode(context: ServerContext, mode: str) -> None:
    """Local AI needs consent switch 3, API key mode needs switch 4 (P7)."""
    choices = (context.storage.get_setting(CONSENT_KEY) or {}).get("choices", {})
    if mode == "local" and not choices.get("title_local"):
        raise bad_request("Turn on consent switch 3 (title categorisation on this computer) first.")
    if mode == "api" and not choices.get("title_api"):
        raise bad_request("Turn on consent switch 4 (title categorisation with my own API key) first.")


def update_model_settings(context: ServerContext, update: SettingsUpdate) -> None:
    """Model names, addresses, the thinking switch and the API key (keychain only, P8)."""
    config = context.config
    local = config.get("categoriser.local")
    if update.local_base_url is not None:
        if not update.local_base_url.startswith(LOCAL_MODEL_HOSTS):
            raise bad_request("The local model must run on this computer (http://127.0.0.1:… or http://localhost:…).")
        local["base_url"] = update.local_base_url.strip()
    if update.local_model is not None:
        local["model"] = update.local_model.strip()
    config.set("categoriser.local", local)

    api = config.get("categoriser.api")
    if update.api_base_url is not None:
        if not update.api_base_url.startswith("https://"):
            raise bad_request("The API address must start with https://")
        api["base_url"] = update.api_base_url.strip()
    if update.api_model is not None:
        api["model"] = update.api_model.strip()
    if update.api_disable_thinking is not None:
        api["extra_body"] = dict(NO_THINKING) if update.api_disable_thinking else {}
    config.set("categoriser.api", api)

    if update.api_key is not None:
        if update.api_key.strip():
            context.keychain.set_api_key(update.api_key.strip())
        else:
            context.keychain.delete_api_key()


def apply_settings(context: ServerContext, update: SettingsUpdate) -> None:
    """Validate and save every field that was sent. Changes take effect at once (the agent reads them each minute)."""
    storage, config = context.storage, context.config
    if update.quiet_hours is not None and not all(QUIET_PERIOD_PATTERN.match(p) for p in update.quiet_hours):
        raise bad_request("Quiet hours must look like 22:00-08:00.")
    if update.consent is not None:
        apply_consent(context, update.consent)
    if update.categoriser_mode is not None:
        check_categoriser_mode(context, update.categoriser_mode)
        config.set("categoriser.mode", update.categoriser_mode)
    update_model_settings(context, update)
    if update.name is not None:
        storage.set_setting(USER_NAME_KEY, update.name.strip())
    if update.dnd_mode is not None:
        config.set("dnd.mode", update.dnd_mode)
    if update.checkin_every_active_minutes is not None:
        config.set("checkins.every_active_minutes", update.checkin_every_active_minutes)
    if update.quiet_hours is not None:
        config.set("quiet.quiet_hours", update.quiet_hours)
    if update.retention_days is not None:
        config.set("data.retention_days", update.retention_days)


# ---------------------------------------------------------------- dashboard page

def dashboard_page(storage) -> str:
    """index.html of the built dashboard, with the pairing token added as a <meta> tag."""
    index = DASHBOARD_DIST / "index.html"
    if not index.exists():
        return DASHBOARD_MISSING_PAGE
    token_tag = f'<meta name="commit-token" content="{html.escape(get_or_create_token(storage))}">'
    return index.read_text(encoding="utf-8").replace("</head>", token_tag + "</head>", 1)


# ---------------------------------------------------------------- the app

def add_extension_routes(app: FastAPI, context: ServerContext, protected: list) -> None:
    """Routes used by the Chrome extension (and the dashboard's private list)."""
    storage = context.storage

    @app.post("/api/web/heartbeat", dependencies=protected, status_code=202)
    def web_heartbeat(heartbeat: Heartbeat) -> dict:
        """Queue one heartbeat; it is categorised in the background (never blocks)."""
        if heartbeat.category is not None and heartbeat.category not in SPECIAL_CATEGORIES:
            raise bad_request("category may only be Private or Other.")
        accepted = context.heartbeats.submit(heartbeat.domain, heartbeat.title, heartbeat.category, heartbeat.seconds)
        return {"accepted": accepted}

    @app.get("/api/private-domains", dependencies=protected)
    def list_private_domains() -> dict:
        return {"domains": storage.private_domains()}

    @app.post("/api/private-domains", dependencies=protected)
    def add_private_domain(body: DomainBody) -> dict:
        storage.add_private_domain(clean_domain(body.domain))
        return {"domains": storage.private_domains()}

    @app.delete("/api/private-domains", dependencies=protected)
    def remove_private_domain(body: DomainBody) -> dict:
        storage.remove_private_domain(clean_domain(body.domain))
        return {"domains": storage.private_domains()}

    @app.get("/api/status", dependencies=protected)
    def status() -> dict:
        choices = (storage.get_setting(CONSENT_KEY) or {}).get("choices", {})
        return {"running": True, "website_tracking": bool(choices.get("website_tracking")), **context.agent.status()}


def add_report_routes(app: FastAPI, context: ServerContext, protected: list) -> None:
    """Home, weekly report, activity, domain rules."""
    storage, config = context.storage, context.config

    @app.get("/api/today", dependencies=protected)
    def today() -> dict:
        status = context.agent.status()
        data = report.build_today(storage, time.time(), status.get("load_score"), RECENT_ALERTS_ON_HOME)
        data["name"] = storage.get_setting(USER_NAME_KEY, "")
        data["status"] = status
        return data

    @app.get("/api/week", dependencies=protected)
    def week(start: str | None = Query(default=None)) -> dict:
        return report.build_week_report(storage, config, parse_start(start))

    @app.get("/api/report/pdf", dependencies=protected)
    def week_pdf(start: str | None = Query(default=None)) -> Response:
        first_day = parse_start(start)
        pdf = report.render_pdf(report.build_week_report(storage, config, first_day))
        headers = {"Content-Disposition": f'attachment; filename="commit-week-{first_day.isoformat()}.pdf"'}
        return Response(content=pdf, media_type="application/pdf", headers=headers)

    @app.get("/api/activity", dependencies=protected)
    def activity(start: str | None = Query(default=None)) -> dict:
        first_day = parse_start(start)
        begin, end = report.week_bounds(first_day)
        days = [first_day + timedelta(days=offset) for offset in range(DAYS_IN_WEEK)]
        return {
            "start": first_day.isoformat(),
            "end": (first_day + timedelta(days=DAYS_IN_WEEK - 1)).isoformat(),
            "daily": report.minutes_summary(storage, begin, end, days)["daily"],
            **report.time_summary(storage, config, begin, end, ACTIVITY_TOP_ITEMS),
            "categories_available": config.get("categoriser.categories"),
        }

    @app.put("/api/domain-rules", dependencies=protected)
    def set_domain_rule(rule: DomainRule) -> dict:
        allowed = config.get("categoriser.categories")
        if rule.category not in allowed:
            raise bad_request(f"category must be one of {allowed}")
        domain = clean_domain(rule.domain)
        storage.set_domain_rule(domain, rule.category)
        return {"domain": domain, "category": rule.category}


def add_control_routes(app: FastAPI, context: ServerContext, protected: list) -> None:
    """Alerts, settings, LLM test, calibration, pause/resume, delete all data."""
    storage = context.storage

    @app.get("/api/alerts", dependencies=protected)
    def alerts() -> dict:
        return {"alerts": report.recent_alerts(storage, ALERT_HISTORY_LIMIT)}

    @app.post("/api/alerts/{alert_id}/feedback", dependencies=protected)
    def alert_feedback(alert_id: int, body: FeedbackBody) -> dict:
        if not storage.execute("SELECT id FROM alerts WHERE id = ?", (alert_id,)):
            raise HTTPException(status_code=404, detail="No such alert.")
        storage.set_alert_feedback(alert_id, body.feedback)
        return {"id": alert_id, "feedback": body.feedback}

    @app.get("/api/settings", dependencies=protected)
    def get_settings() -> dict:
        return read_settings(context)

    @app.put("/api/settings", dependencies=protected)
    def put_settings(update: SettingsUpdate) -> dict:
        apply_settings(context, update)
        return read_settings(context)

    @app.post("/api/llm/test", dependencies=protected)
    def test_llm() -> dict:
        worked, message = context.categoriser.test_connection()
        return {"ok": worked, "message": message}

    @app.post("/api/calibration/restart", dependencies=protected)
    def restart_calibration() -> dict:
        context.agent.restart_calibration()
        return {"ok": True}

    @app.post("/api/pause", dependencies=protected)
    def pause() -> dict:
        context.agent.set_paused(True)
        return {"paused": True}

    @app.post("/api/resume", dependencies=protected)
    def resume() -> dict:
        context.agent.set_paused(False)
        return {"paused": False}

    @app.delete("/api/data", dependencies=protected)
    def delete_data(body: DeleteBody) -> dict:
        context.agent.delete_all_data()
        return {"deleted": True}


def create_app(context: ServerContext) -> FastAPI:
    """
    Build the FastAPI app.

    In:  the ServerContext.
    Out: the app (served by LocalServer, or by TestClient in tests).
    """
    # No automatic API docs pages: nothing here is meant for browsing.
    app = FastAPI(title="Commit local API", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    def require_token(x_commit_token: str | None = Header(default=None)) -> None:
        """Reject any request without the right pairing token."""
        expected = get_or_create_token(context.storage)
        if x_commit_token is None or not secrets.compare_digest(x_commit_token, expected):
            raise HTTPException(status_code=401, detail="Missing or wrong pairing token.")

    protected = [Depends(require_token)]
    add_extension_routes(app, context, protected)
    add_report_routes(app, context, protected)
    add_control_routes(app, context, protected)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        # no-store: the page contains the pairing token, so the browser should not cache it.
        return HTMLResponse(dashboard_page(context.storage), headers={"Cache-Control": "no-store"})

    if (DASHBOARD_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=DASHBOARD_DIST / "assets"), name="assets")
    return app


# ---------------------------------------------------------------- running it in the agent process

class LocalServer:
    """Runs the FastAPI app with uvicorn on a background thread."""

    def __init__(self, app: FastAPI, port: int):
        # access_log=False: request lines are never written to the logs (P12).
        settings = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False)
        self.server = uvicorn.Server(settings)
        self.thread: threading.Thread | None = None

    def start(self) -> bool:
        """
        Start serving. Out: True if the server is listening (False e.g. when the port is taken).
        """
        self.thread = threading.Thread(target=self.server.run, name="local-server", daemon=True)
        self.thread.start()
        deadline = time.time() + SERVER_START_WAIT_SECONDS
        while time.time() < deadline and not self.server.started and self.thread.is_alive():
            time.sleep(0.05)
        return bool(self.server.started)

    def stop(self) -> None:
        self.server.should_exit = True
