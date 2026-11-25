"""
agent/main.py — starts Commit:  python -m agent.main

What it does:
  1. sets up the log file (never contains typed text, titles or URLs — P12);
  2. opens the database and the configuration;
  3. runs the first-launch consent/setup flow if needed;
  4. starts the input logger, app tracker, minute loop, and the local server for the
     Chrome extension (all on background threads);
  5. shows the menu-bar icon (this must run on the main thread and keeps the app alive).

The CommitAgent class also implements the menu actions: pause, resume, delete all data, quit.
"""

from __future__ import annotations

import logging
import shutil
import sys
import threading
from datetime import date, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs

from agent import consent, keychain
from agent.actions import AlertFlows, AlertWorker, DndController
from agent.app_tracker import AppTracker
from agent.calibration import Calibration
from agent.config import Config
from agent.detector import ConditionDetector
from agent.engine import Engine
from agent.feature_builder import MODELS_DIR, load_feature_spec
from agent.load_scorer import LoadScorer
from agent.logger import InputCounter, InputLogger
from agent.platform import system
from agent.storage import APP_NAME, Storage
from server import report
from server.app import LocalServer, ServerContext, create_app
from server.categoriser import HeartbeatProcessor, TitleCategoriser

log = logging.getLogger("agent")

LOG_FILE_MAX_BYTES = 1_000_000   # rotate the debug log at about 1 MB
LOG_FILE_BACKUPS = 2             # keep two old log files
DELETE_DELAY_SECONDS = 0.5       # lets the dashboard receive its answer before the data is deleted


def log_folder() -> Path:
    """Folder for the debug log, e.g. ~/Library/Logs/Commit."""
    return Path(platformdirs.user_log_dir(APP_NAME))


def setup_logging() -> None:
    """Write INFO messages to a small rotating log file and to the terminal."""
    folder = log_folder()
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "commit.log", maxBytes=LOG_FILE_MAX_BYTES, backupCount=LOG_FILE_BACKUPS)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )


class CommitAgent:
    """Owns every part of the running app."""

    def __init__(self):
        self.storage = Storage()
        self.config = Config(self.storage)
        self.engine: Engine | None = None
        self.input_logger: InputLogger | None = None
        self.app_tracker: AppTracker | None = None
        self.dnd: DndController | None = None
        self.categoriser: TitleCategoriser | None = None
        self.heartbeats: HeartbeatProcessor | None = None
        self.server: LocalServer | None = None
        self.request_quit = None   # set by the menu bar: quits the app from any thread

    # ------------------------------------------------------------ start

    def load_models(self, feature_spec: dict) -> tuple[ConditionDetector | None, LoadScorer | None]:
        """
        Load the two models from shared/models/. If they are missing or broken, keep running
        without predictions and tell the user (README rule 7).
        """
        try:
            detector = ConditionDetector(MODELS_DIR / feature_spec["condition_model"]["file"], self.config.get("detection.smoothing_minutes"))
            scorer = LoadScorer(MODELS_DIR / feature_spec["load_model"]["file"], feature_spec["feature_names"], self.storage, self.config)
            return detector, scorer
        except Exception:
            log.exception("Could not load the models.")
            system.notify("Commit", "Model files could not be loaded. Commit will only log activity. Run the Phase 0 notebooks.")
            return None, None

    def start_server(self) -> None:
        """Start the categoriser, the heartbeat worker and the local server for the extension."""
        self.categoriser = TitleCategoriser(self.storage, self.config, keychain.get_api_key)
        self.heartbeats = HeartbeatProcessor(self.storage, self.config, self.categoriser)
        self.heartbeats.start()
        context = ServerContext(self.storage, self.config, self.categoriser, self.heartbeats, agent=self, keychain=keychain)
        self.server = LocalServer(create_app(context), self.config.get("server.port"))
        if not self.server.start():
            log.warning("The local server could not start (port %s in use?).", self.config.get("server.port"))
            system.notify("Commit", f"Website tracking is off: port {self.config.get('server.port')} is already in use.")

    # ------------------------------------------------------------ controls used by the local API (dashboard)

    def status(self) -> dict:
        """Current state for the API: state, load score, paused, calibration progress."""
        if self.engine is None:
            return {"state": "Starting", "load_score": None, "paused": False, "calibration": None}
        collected, needed = self.engine.calibration.progress()
        calibration = {"complete": self.engine.calibration.is_complete(), "collected": collected, "needed": needed}
        return {**self.engine.status, "paused": self.engine.paused, "calibration": calibration}

    def set_paused(self, paused: bool) -> None:
        self.engine.set_paused(paused)

    def restart_calibration(self) -> None:
        self.engine.restart_calibration()

    def delete_all_data(self) -> None:
        """
        Dashboard "Delete all my data" (the dashboard already asked for confirmation).
        Runs a moment later on another thread, so the API can still answer, then quits the app.
        """
        threading.Timer(DELETE_DELAY_SECONDS, self.delete_now_and_quit).start()

    def delete_now_and_quit(self) -> None:
        self.stop_background_parts()
        delete_everything(self.storage)
        system.notify("Commit", "All Commit data was deleted.")
        if self.request_quit is not None:
            self.request_quit()

    def dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self.config.get('server.port')}/"

    def start(self) -> bool:
        """
        Run setup if needed and start all background parts.

        Out: False if the user did not consent (the app should exit).
        """
        if not consent.has_valid_consent(self.storage):
            if not consent.run_onboarding(system, self.storage, self.config):
                return False

        feature_spec = load_feature_spec()
        detector, scorer = self.load_models(feature_spec)
        counter = InputCounter(self.config.get("logging.pause_threshold_seconds"), self.config.get("logging.pause_max_seconds"))
        self.app_tracker = AppTracker(system.get_frontmost_app, self.config.get("logging.app_sample_seconds"), self.config.get("app_categories"))
        calibration = Calibration(self.storage, self.config.get("calibration.active_minutes"), feature_spec["feature_names"])
        self.start_server()

        self.dnd = DndController(system, self.storage, self.config)
        worker = AlertWorker()
        flows = AlertFlows(system, self.storage, self.config, self.dnd, record_answer=lambda *args: self.engine.record_answer(*args))
        self.engine = Engine(self.config, self.storage, counter, self.app_tracker, calibration, detector, scorer, worker, flows,
                             feature_spec, system, heartbeats=self.heartbeats)

        self.dnd.restore_after_restart()
        self.input_logger = InputLogger(counter)
        self.input_logger.start()
        if not self.input_logger.has_permission():
            system.notify("Commit", "Commit cannot see keyboard/mouse activity yet. Allow it in System Settings → "
                                    "Privacy & Security → Accessibility and Input Monitoring, then restart Commit.")
        self.app_tracker.start()
        self.engine.start()
        log.info("Commit started.")
        return True

    # ------------------------------------------------------------ menu actions

    def pause(self) -> None:
        self.engine.set_paused(True)

    def resume(self) -> None:
        self.engine.set_paused(False)

    def open_weekly_report(self) -> None:
        """Make a PDF of the last 7 days and open it (on demand, README 9.4)."""
        folder = report.reports_folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "commit-last-7-days.pdf"
        start = date.today() - timedelta(days=report.DAYS_IN_WEEK - 1)
        path.write_bytes(report.render_pdf(report.build_week_report(self.storage, self.config, start)))
        system.open_url(path.as_uri())

    def stop_background_parts(self) -> None:
        """Stop the threads and switch DND off if Commit had turned it on."""
        for part in (self.engine, self.app_tracker, self.input_logger, self.heartbeats, self.server):
            if part is not None:
                part.stop()
        if self.dnd is not None:
            self.dnd.turn_off(announce=False)

    def confirm_and_delete_all_data(self) -> bool:
        """
        Menu bar "Delete all my data" (P9): database (incl. title cache, consent record, settings),
        API key in the keychain, saved reports and the log files. Asks for confirmation first.

        Out: True if the data was deleted (the app then quits).
        """
        answer = system.ask(
            "Delete all Commit data? This removes the database, cache, consent record, API key, reports and logs. "
            "It cannot be undone, and Commit will quit.",
            ["Cancel", "Delete everything"], default_button="Cancel",
            timeout_seconds=self.config.get("dialogs.timeout_seconds"),
        )
        if answer != "Delete everything":
            return False
        self.stop_background_parts()
        delete_everything(self.storage)
        system.notify("Commit", "All Commit data was deleted.")
        return True

    def quit(self) -> None:
        """Stop everything before the menu-bar app exits."""
        self.stop_background_parts()
        log.info("Commit stopped.")


def delete_everything(storage: Storage, reports_folder: Path | None = None) -> None:
    """
    Remove every piece of stored data (P9). Separate function so tests can call it.

    In:  the open Storage (it is closed and its file deleted); the reports folder (None = default).
    """
    storage.delete_database_file()
    keychain.delete_api_key()
    shutil.rmtree(reports_folder or report.reports_folder(), ignore_errors=True)
    logging.shutdown()
    shutil.rmtree(log_folder(), ignore_errors=True)


def main() -> None:
    """Entry point."""
    setup_logging()
    agent = CommitAgent()
    if not agent.start():
        log.info("Setup not completed; exiting.")
        sys.exit(0)
    from agent.menubar import CommitMenuBar  # imported late: needs the macOS GUI libraries

    CommitMenuBar(agent).run()


if __name__ == "__main__":
    main()
