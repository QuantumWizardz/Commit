"""
agent/engine.py — the once-a-minute loop that ties everything together.

Every minute:
  1. take the minute's counts from the input logger and the app tracker;
  2. decide the activity mode (paused / idle / passive / active);
  3. build features with shared/features.py;
  4. during calibration: collect the minute; afterwards: predict the condition, compute the
     load score, and save everything (counts and predictions only, never key content);
  5. decide whether to suggest DND or a break, or whether a check-in is due;
  6. once a day: delete data older than the retention period (P11).

`process_minute` holds the logic and takes all inputs as arguments, so tests can feed it
made-up minutes without a keyboard, a mouse or a clock.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime

from agent import decisions, devlog
from server import report
from server.categoriser import MISCELLANEOUS
from agent.feature_builder import (
    MODE_ACTIVE,
    MODE_COMMIT,
    MODE_IDLE,
    MODE_PAUSED,
    RecentMinutes,
    activity_mode,
    normalised_model_input,
)

log = logging.getLogger(__name__)

SECONDS_PER_MINUTE = 60
DECISION_STATE_KEY = "decision_state"
PAUSED_KEY = "paused"
CONSENT_KEY = "consent"

# Text shown in the menu bar for each state (README 8.10).
STATE_LEARNING = "Learning"
STATE_PAUSED = "Paused"
STATE_LABELS = {"neutral": "Calm", "interruptions": "Interrupted", "time_pressure": "Pressured"}


def next_minute_boundary(now: float) -> int:
    """The next full minute after `now`, in unix seconds (e.g. 10:04:37 -> 10:05:00)."""
    return (int(now) // SECONDS_PER_MINUTE + 1) * SECONDS_PER_MINUTE


class Engine:
    """The minute loop. Created and started by agent/main.py."""

    def __init__(self, config, storage, counter, app_tracker, calibration, detector, load_scorer, worker, flows, feature_spec,
                 system=None, heartbeats=None, reports_folder=None, dev_log=None):
        """
        In:  config, storage, InputCounter, AppTracker, Calibration, ConditionDetector (or None
             if the model files are missing), LoadScorer (or None), AlertWorker, AlertFlows,
             the features.json contents, the platform module (for notifications),
             the server's HeartbeatProcessor (or None), the weekly-report folder (None = default)
             and the Developer mode DevLog (or None).
        """
        self.dev_log = dev_log
        self.heartbeats = heartbeats
        self.reports_folder = reports_folder
        self.config = config
        self.storage = storage
        self.counter = counter
        self.app_tracker = app_tracker
        self.calibration = calibration
        self.detector = detector
        self.load_scorer = load_scorer
        self.worker = worker
        self.flows = flows
        self.system = system
        self.feature_names = feature_spec["feature_names"]
        self.history = RecentMinutes(tuple(feature_spec["rolling_windows_minutes"]))

        # Recent ACTIVE minutes with predictions, for the DND/break rules.
        longest_rule = max(config.get("dnd.sustained_minutes"), config.get("breaks.window_minutes"))
        self.recent_active: deque[dict] = deque(maxlen=longest_rule)

        self.state_lock = threading.Lock()
        self.decision_state = decisions.DecisionState.from_dict(storage.get_setting(DECISION_STATE_KEY))
        self.paused = bool(storage.get_setting(PAUSED_KEY, False))
        self.counter.set_paused(self.paused)
        self.active_minutes_since_checkin = 0
        self.last_cleanup_day: str | None = None
        self.status = {"state": STATE_PAUSED if self.paused else STATE_LEARNING, "load_score": None}
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def dev(self, kind: str, message: str, /, **data) -> None:
        """Add an event to the Developer mode log (if there is one; it ignores events while developer mode is off)."""
        if self.dev_log is not None:
            self.dev_log.add(kind, message, **data)

    # ------------------------------------------------------------------ the minute

    def process_minute(self, minute_ts: int, counts: dict, apps: dict, now: float | None = None, now_local: datetime | None = None) -> dict:
        """
        Handle one finished minute.

        In:  start of the minute (unix seconds), counts from InputCounter.snapshot_and_reset(),
             app summary from AppTracker.snapshot_and_reset(), and (for tests) the current time.
        Out: the minute record that was saved to the database.
        """
        now = time.time() if now is None else now
        now_local = datetime.fromtimestamp(now) if now_local is None else now_local
        self.cleanup_once_a_day(now_local, now)

        record = {"ts": minute_ts, "mode": MODE_PAUSED, "app_category": apps.get("main_category"), "features": None,
                  "condition": None, "condition_probs": None, "load_score": None}
        if self.paused:
            self.storage.save_minute(record)
            self.dev(devlog.ACTIVITY, "Paused: nothing counted this minute", minute_ts=minute_ts, mode=MODE_PAUSED)
            return record

        # The lock screen is not real use, and Commit's own dashboard and dialogs are never counted:
        # take them out first.
        apps = self.remove_ignored_apps(apps)
        apps, commit_seconds, commit_share = self.remove_commit_time(apps)
        record["app_category"] = apps["main_category"]
        if commit_share >= self.config.get("activity.commit_minute_share"):
            record["mode"] = MODE_COMMIT
            record["app_category"] = None
            if self.heartbeats is not None:
                self.heartbeats.take_received_seconds()   # reset; this minute records nothing
            self.storage.save_minute(record)
            self.dev(devlog.ACTIVITY, f"Commit minute: {commit_seconds} s in Commit's dashboard or dialogs, not counted",
                     minute_ts=minute_ts, mode=MODE_COMMIT, commit_seconds=commit_seconds)
            return record

        # Time per app (names only) and the activity mode.
        self.storage.save_app_time(minute_ts, apps["app_seconds"], apps["app_categories"])
        record["mode"] = activity_mode(
            counts["active_seconds"], apps["main_category"],
            self.config.get("activity.idle_active_seconds"), self.config.get("activity.passive_active_seconds"),
            self.config.get("activity.passive_categories"),
        )
        self.dev(devlog.ACTIVITY,
                 f"{record['mode'].capitalize()} minute · {counts['active_seconds']} s active · {counts['keystrokes']} keys · "
                 f"{counts['clicks']} clicks · {apps['app_switches']} app switches · main app {apps.get('main_app') or '–'} "
                 f"({apps['main_category'] or '–'})" + (f" · {commit_seconds} s of Commit removed" if commit_seconds else ""),
                 minute_ts=minute_ts, mode=record["mode"], counts=counts, app_switches=apps["app_switches"], commit_seconds=commit_seconds,
                 app_seconds=apps["app_seconds"], app_categories=apps["app_categories"])
        self.record_browser_without_extension(minute_ts, apps, record["mode"])

        # Features use the same shared code as training. Idle/passive minutes still count for rolling windows.
        self.history.add(minute_ts, {**counts, "app_switches": apps["app_switches"]})
        features = self.history.latest_features()
        if record["mode"] != MODE_ACTIVE:
            self.storage.save_minute(record)
            return record

        # Calibration: collect, no predictions or alerts.
        if not self.calibration.is_complete():
            calibration_finished = self.calibration.add_minute(features)
            if calibration_finished:
                self.dev(devlog.CALIBRATION, "Calibration complete: baseline saved, predictions start next minute",
                         baseline=self.calibration.baseline())
            else:
                collected, needed = self.calibration.progress()
                self.dev(devlog.CALIBRATION, f"Calibration minute {collected} of {needed} collected", features=features)
            if calibration_finished and self.system is not None:
                self.system.notify("Commit", "Commit has learned your normal pattern and is now active.")
            self.status = {"state": STATE_LEARNING, "load_score": None}
            self.storage.save_minute(record)
            return record

        self.predict(record, features)
        self.storage.save_minute(record)
        if record["condition"] is not None:
            self.recent_active.append({"ts": minute_ts, "condition": record["condition"], "load_score": record["load_score"],
                                       "app_category": record["app_category"], "app_switches": apps["app_switches"]})
            self.active_minutes_since_checkin += 1
            self.maybe_alert(now, now_local)
        if self.load_scorer is not None:
            self.load_scorer.maybe_refit(now)
        return record

    def predict(self, record: dict, features: dict) -> None:
        """
        Fill in the condition, probabilities and load score of an active minute (in place).
        Does nothing if the model files are missing.
        """
        if self.detector is None or self.load_scorer is None:
            self.dev(devlog.PREDICTION, "No prediction: the model files are not loaded")
            return
        model_input = normalised_model_input(features, self.calibration.baseline(), self.feature_names)
        raw, smoothed, probabilities = self.detector.predict(model_input)
        record["features"] = {name: round(float(model_input.iloc[0][name]), 4) for name in self.feature_names}
        record["condition"] = smoothed
        record["condition_probs"] = probabilities
        record["load_score"] = self.load_scorer.score(model_input, smoothed)
        self.status = {"state": STATE_LABELS[smoothed], "load_score": record["load_score"]}
        self.dev(devlog.PREDICTION,
                 f"Raw {raw} ({probabilities.get(raw, 0):.0%}) → smoothed {smoothed} · load score {record['load_score']:.0f}",
                 minute_ts=record["ts"], raw_condition=raw, condition=smoothed, probabilities=probabilities,
                 load_score=record["load_score"], features=record["features"])

    def remove_ignored_apps(self, apps: dict) -> dict:
        """
        Drop apps that are not real use (activity.ignored_apps: the lock screen, the screen saver),
        so their time is saved nowhere and they never become the minute's main app.
        """
        ignored = set(self.config.get("activity.ignored_apps"))
        if not ignored & set(apps["app_seconds"]):
            return apps
        app_seconds = {name: seconds for name, seconds in apps["app_seconds"].items() if name not in ignored}
        categories = {name: category for name, category in apps["app_categories"].items() if name in app_seconds}
        main_app = max(app_seconds, key=app_seconds.get) if app_seconds else None
        return {**apps, "app_seconds": app_seconds, "app_categories": categories, "main_app": main_app,
                "main_category": categories.get(main_app) if main_app else None}

    def remove_commit_time(self, apps: dict) -> tuple[dict, int, float]:
        """
        Take Commit's own time out of one minute's app summary, so it is counted nowhere:
        its helper processes (activity.commit_apps: dialogs, notifications, menu bar) and the
        browser seconds the extension reported on the Commit dashboard.

        In:  the app summary from AppTracker.snapshot_and_reset().
        Out: (summary without Commit, seconds removed, share of the minute's app time that was Commit).
        """
        dashboard_seconds = self.heartbeats.take_commit_seconds() if self.heartbeats is not None else 0
        commit_apps = set(self.config.get("activity.commit_apps"))
        browser_apps = self.config.get("categoriser.browser_apps")
        total = sum(apps["app_seconds"].values())
        app_seconds = {name: seconds for name, seconds in apps["app_seconds"].items() if name not in commit_apps}
        for name in sorted((n for n in app_seconds if n in browser_apps), key=app_seconds.get, reverse=True):
            taken = min(app_seconds[name], dashboard_seconds)
            app_seconds[name] -= taken
            dashboard_seconds -= taken
        app_seconds = {name: seconds for name, seconds in app_seconds.items() if seconds > 0}
        removed = total - sum(app_seconds.values())
        if removed == 0:
            return apps, 0, 0.0
        main_app = max(app_seconds, key=app_seconds.get) if app_seconds else None
        categories = {name: category for name, category in apps["app_categories"].items() if name in app_seconds}
        cleaned = {**apps, "app_seconds": app_seconds, "app_categories": categories, "main_app": main_app,
                   "main_category": categories.get(main_app, apps["main_category"]) if main_app else None}
        return cleaned, removed, removed / total

    # ------------------------------------------------------------------ websites (Phase 2)

    def record_browser_without_extension(self, minute_ts: int, apps: dict, mode: str) -> None:
        """
        If Chrome was in front but the extension sent nothing this minute (e.g. an incognito window,
        or the extension is not installed), record that time as "Miscellaneous" with no detail (P5).
        """
        if self.heartbeats is None:
            return
        received_seconds = self.heartbeats.take_received_seconds()   # read every minute, so it resets
        browser_seconds = sum(apps["app_seconds"].get(name, 0) for name in self.config.get("categoriser.browser_apps"))
        if browser_seconds > 0 and received_seconds == 0 and mode != MODE_IDLE:
            self.storage.save_web_time(minute_ts, None, MISCELLANEOUS, browser_seconds)
            self.dev(devlog.WEBSITE, f"Browser in front but no extension data: {browser_seconds} s saved as {MISCELLANEOUS}",
                     category=MISCELLANEOUS, seconds=browser_seconds)

    def current_domain(self) -> str | None:
        """The website in front right now, if the extension told us recently (for "never interrupt calls")."""
        if self.heartbeats is None:
            return None
        return self.heartbeats.current_domain(self.config.get("categoriser.call_domain_max_age_seconds"))

    # ------------------------------------------------------------------ alerts and check-ins

    def maybe_alert(self, now: float, now_local: datetime) -> None:
        """Start a DND/break flow if the rules say so; otherwise a check-in if one is due."""
        recent = list(self.recent_active)
        frontmost = self.app_tracker.frontmost_app()
        domain = self.current_domain()
        with self.state_lock:
            choice = decisions.decide(recent, now, now_local, self.decision_state, self.config, frontmost, domain)
            checks = decisions.explain(recent, now, now_local, self.decision_state, self.config, frontmost, domain) if self.dev_log else {}
        if choice == decisions.DND:
            reason = self.dnd_reason(recent)
            self.dev(devlog.DECISION, f"Suggest Do Not Disturb: {reason}", choice=choice, frontmost_app=frontmost, domain=domain, checks=checks)
            self.worker.submit(lambda: self.flows.dnd_flow(reason))
        elif choice == decisions.BREAK:
            reason = self.break_reason(recent)
            self.dev(devlog.DECISION, f"Suggest a break: {reason}", choice=choice, frontmost_app=frontmost, domain=domain, checks=checks)
            self.worker.submit(lambda: self.flows.break_flow(reason))
        elif self.checkin_due(frontmost, domain, now_local) and self.worker.submit(self.flows.checkin_flow):
            self.active_minutes_since_checkin = 0
            self.dev(devlog.DECISION, "No alert; load check-in is due and was shown", choice="checkin", frontmost_app=frontmost, domain=domain, checks=checks)
        else:
            self.dev(devlog.DECISION, f"No alert: {checks.get('reason', '')}", choice=None, frontmost_app=frontmost, domain=domain,
                     checks=checks, active_minutes_since_checkin=self.active_minutes_since_checkin)

    def checkin_due(self, frontmost: str | None, domain: str | None, now_local: datetime) -> bool:
        """True if check-ins are on and consented, enough active minutes passed, and it is not a call/quiet time."""
        consent = self.storage.get_setting(CONSENT_KEY, {})
        if not (self.config.get("checkins.enabled") and consent.get("choices", {}).get("checkins")):
            return False
        if self.active_minutes_since_checkin < self.config.get("checkins.every_active_minutes"):
            return False
        if decisions.in_call(frontmost, self.config.get("quiet.call_apps"), domain, self.config.get("quiet.call_domains")):
            return False
        return not decisions.in_quiet_hours(now_local, self.config.get("quiet.quiet_hours"))

    def dnd_reason(self, recent: list[dict]) -> str:
        """Short explanation for the DND question, e.g. "Interruptions or time pressure in 12 of your last 15 active minutes; app switches 2.5× your normal"."""
        window = recent[-self.config.get("dnd.sustained_minutes"):]
        pressured = sum(1 for m in window if m["condition"] in decisions.PRESSURE_CONDITIONS)
        reason = f"Interruptions or time pressure in {pressured} of your last {len(window)} active minutes"
        normal_switches = (self.calibration.baseline() or {}).get("app_switches", {}).get("mean", 0)
        if normal_switches > 0:
            recent_switches = sum(m["app_switches"] for m in window) / len(window)
            reason += f"; app switches {recent_switches / normal_switches:.1f}× your normal"
        return reason

    def break_reason(self, recent: list[dict]) -> str:
        """Short explanation for the break suggestion."""
        window = recent[-self.config.get("breaks.window_minutes"):]
        threshold = self.config.get("breaks.load_threshold")
        high = sum(1 for m in window if m["load_score"] is not None and m["load_score"] > threshold)
        return f"Load score above {threshold} in {high} of your last {len(window)} active minutes"

    def record_answer(self, kind: str, action: str, now: float) -> None:
        """Callback from AlertFlows: update and save the decision state after an alert."""
        with self.state_lock:
            if kind == decisions.DND:
                decisions.after_dnd_answer(self.decision_state, action, now, self.config)
            else:
                decisions.after_break_answer(self.decision_state, action, now, self.config)
            self.storage.set_setting(DECISION_STATE_KEY, self.decision_state.to_dict())
        label = "Do Not Disturb" if kind == decisions.DND else "Break"
        self.dev(devlog.ALERT, f"{label} suggestion answered: {action}", kind=kind, action=action,
                 decision_state=self.decision_state.to_dict())

    # ------------------------------------------------------------------ pause, calibration, cleanup

    def set_paused(self, paused: bool) -> None:
        """Pause or resume tracking (P10). Nothing is counted while paused."""
        self.paused = paused
        self.counter.set_paused(paused)
        self.history.clear()
        if self.detector is not None:
            self.detector.reset()
        self.storage.set_setting(PAUSED_KEY, paused)
        self.status = {"state": STATE_PAUSED if paused else self.current_state_label(), "load_score": None}
        self.dev(devlog.SYSTEM, "Tracking paused" if paused else "Tracking resumed", paused=paused)

    def current_state_label(self) -> str:
        """State label when not paused: Learning during calibration, else the last condition (Calm by default)."""
        if not self.calibration.is_complete():
            return STATE_LEARNING
        last = self.recent_active[-1]["condition"] if self.recent_active else "neutral"
        return STATE_LABELS[last]

    def restart_calibration(self) -> None:
        """Settings → Re-run calibration."""
        self.calibration.restart()
        self.recent_active.clear()
        if self.detector is not None:
            self.detector.reset()
        self.status = {"state": STATE_LEARNING, "load_score": None}
        self.dev(devlog.SYSTEM, "Calibration restarted: learning from the next active minutes")

    def cleanup_once_a_day(self, now_local: datetime, now: float) -> None:
        """
        Once per day: delete data older than data.retention_days (P11), and on the report
        weekday save last week's PDF report (README 9.4).
        """
        today = now_local.date().isoformat()
        if today == self.last_cleanup_day:
            return
        self.last_cleanup_day = today
        self.storage.delete_older_than(self.config.get("data.retention_days"), now)
        self.dev(devlog.SYSTEM, f"Daily cleanup: deleted data older than {self.config.get('data.retention_days')} days")
        try:
            new_report = report.ensure_weekly_report(self.storage, self.config, now_local.date(), self.reports_folder, now)
        except Exception:
            log.exception("Could not create the weekly report; will try again tomorrow.")
            return
        if new_report is not None and self.system is not None:
            self.system.notify("Commit", "Your weekly report is ready (menu bar → Weekly report).")

    # ------------------------------------------------------------------ the loop

    def run(self) -> None:
        """
        Wake up at every minute boundary and process the minute that just ended.

        The boundary is fixed BEFORE waiting, because a timer can wake a few milliseconds
        early (it uses a different clock than the wall time); we then wait the rest.
        After the computer slept, missed minutes are skipped instead of replayed.
        """
        next_boundary = next_minute_boundary(time.time())
        while not self.stop_event.is_set():
            if self.stop_event.wait(max(next_boundary - time.time(), 0)):
                break
            if time.time() < next_boundary:
                continue  # woke slightly early: wait the remaining milliseconds
            minute_ts = next_boundary - SECONDS_PER_MINUTE
            try:
                counts = self.counter.snapshot_and_reset()
                apps = self.app_tracker.snapshot_and_reset()
                self.process_minute(minute_ts, counts, apps)
            except Exception:
                log.exception("Processing a minute failed; continuing with the next one.")
            next_boundary = next_minute_boundary(time.time())

    def start(self) -> None:
        """Start the loop on a background thread."""
        self.thread = threading.Thread(target=self.run, name="minute-loop", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the loop."""
        self.stop_event.set()
