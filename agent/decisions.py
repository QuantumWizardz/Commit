"""
agent/decisions.py — when to suggest Do Not Disturb or a break (README modules M1.7 and M1.8).

Pure logic: no dialogs, no OS calls, no clock. Everything comes in as arguments, which makes
the rules easy to read and to test (tests/test_decisions.py).

Rules
-----
DND:   Interruptions or Time-pressure in MOST (> dnd.sustained_fraction) of the last
       dnd.sustained_minutes active minutes, DND not already on, not within the "ask again"
       cooldown (after "Not now", or after a DND session ended).
Break: load score above breaks.load_threshold in at least breaks.high_fraction of the last
       breaks.window_minutes active minutes, and not within the break cooldown / snooze.
Both:  never shown at once. If the pattern looks like interruptions (condition mostly
       "interruptions", or lots of Communication apps) → DND; otherwise (sustained time
       pressure) → break.
Never: during a video call (call app in front) or during the user's quiet hours.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time as clock_time

DND = "dnd"
BREAK = "break"
PRESSURE_CONDITIONS = ("interruptions", "time_pressure")
SECONDS_PER_MINUTE = 60


@dataclass
class DecisionState:
    """
    What has happened before (saved in the database between app restarts).
    All values are unix times; 0 means "not set".
    """
    dnd_on_until: float = 0.0          # DND is on (turned on by us) until this time
    dnd_ask_blocked_until: float = 0.0  # do not ask about DND before this time
    break_blocked_until: float = 0.0    # no break suggestion before this time (cooldown or snooze)

    def to_dict(self) -> dict:
        """For saving as JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict | None) -> "DecisionState":
        """Rebuild from saved JSON (or start fresh)."""
        return cls(**values) if values else cls()


# ---------------------------------------------------------------- building blocks

def last_n(minutes: list[dict], count: int) -> list[dict] | None:
    """The last `count` items, or None if there are fewer (not enough history yet)."""
    if len(minutes) < count:
        return None
    return minutes[-count:]


def pressure_is_sustained(recent: list[dict], sustained_minutes: int, sustained_fraction: float) -> bool:
    """
    True if most of the last N active minutes were Interruptions or Time pressure.

    In:  recent active minutes (oldest first, each with "condition"), N, the "most" fraction.
    """
    window = last_n(recent, sustained_minutes)
    if window is None:
        return False
    pressured = sum(1 for minute in window if minute["condition"] in PRESSURE_CONDITIONS)
    return pressured / len(window) > sustained_fraction


def load_is_sustained_high(recent: list[dict], window_minutes: int, load_threshold: float, high_fraction: float) -> bool:
    """
    True if the load score was above the threshold in at least `high_fraction` of the last N active minutes.
    """
    window = last_n(recent, window_minutes)
    if window is None:
        return False
    high = sum(1 for minute in window if minute["load_score"] is not None and minute["load_score"] > load_threshold)
    return high / len(window) >= high_fraction


def looks_like_interruptions(recent: list[dict], window_minutes: int, communication_category: str, communication_share: float) -> bool:
    """
    True if recent pressure looks like interruptions rather than time pressure.

    In:  recent active minutes (each with "condition" and "app_category"), how many to look at,
         the Communication category name and the share that counts as "lots".
    Out: True when interruptions were at least as common as time pressure, or when
         Communication apps were in front for at least `communication_share` of the minutes.
    """
    window = recent[-window_minutes:]
    if not window:
        return False
    interruptions = sum(1 for minute in window if minute["condition"] == "interruptions")
    time_pressure = sum(1 for minute in window if minute["condition"] == "time_pressure")
    communication = sum(1 for minute in window if minute.get("app_category") == communication_category)
    return interruptions >= time_pressure or communication / len(window) >= communication_share


def parse_clock(text: str) -> clock_time:
    """Turn "22:30" into a time object."""
    hours, minutes = text.split(":")
    return clock_time(int(hours), int(minutes))


def in_quiet_hours(now_local: datetime, quiet_hours: list[str]) -> bool:
    """
    True if the local time falls inside any "HH:MM-HH:MM" range. Ranges may cross midnight
    (e.g. "22:00-08:00").
    """
    current = now_local.time()
    for period in quiet_hours:
        start_text, end_text = period.split("-")
        start, end = parse_clock(start_text), parse_clock(end_text)
        if start <= end:
            inside = start <= current < end
        else:  # crosses midnight
            inside = current >= start or current < end
        if inside:
            return True
    return False


def in_call(frontmost_app: str | None, call_apps: list[str], current_domain: str | None = None, call_domains: list[str] | None = None) -> bool:
    """True if a video-call app (or call website, from Phase 2) is in front."""
    if frontmost_app is not None and frontmost_app in call_apps:
        return True
    return current_domain is not None and current_domain in (call_domains or [])


# ---------------------------------------------------------------- the decision

def decide(recent: list[dict], now: float, now_local: datetime, state: DecisionState, config, frontmost_app: str | None, current_domain: str | None = None) -> str | None:
    """
    Decide whether to suggest DND, a break, or nothing this minute.

    In:  recent active minutes (oldest first; "condition", "load_score", "app_category"),
         current unix time and local datetime, the DecisionState, the Config,
         the frontmost app (and website domain once the extension exists).
    Out: "dnd", "break" or None.
    """
    # Never interrupt calls or quiet hours.
    if in_call(frontmost_app, config.get("quiet.call_apps"), current_domain, config.get("quiet.call_domains")):
        return None
    if in_quiet_hours(now_local, config.get("quiet.quiet_hours")):
        return None

    sustained_minutes = config.get("dnd.sustained_minutes")
    want_dnd = (
        pressure_is_sustained(recent, sustained_minutes, config.get("dnd.sustained_fraction"))
        and now >= state.dnd_on_until
        and now >= state.dnd_ask_blocked_until
    )
    want_break = (
        load_is_sustained_high(recent, config.get("breaks.window_minutes"), config.get("breaks.load_threshold"), config.get("breaks.high_fraction"))
        and now >= state.break_blocked_until
    )

    if want_dnd and want_break:
        interrupted = looks_like_interruptions(
            recent, sustained_minutes, config.get("intervention.communication_category"), config.get("intervention.communication_share")
        )
        return DND if interrupted else BREAK
    if want_dnd:
        return DND
    if want_break:
        return BREAK
    return None


def explain(recent: list[dict], now: float, now_local: datetime, state: DecisionState, config, frontmost_app: str | None, current_domain: str | None = None) -> dict:
    """
    Every check that decide() looks at, for the Developer page (same inputs as decide()).

    Out: {"in_call", "quiet_hours", "pressure_sustained", "pressured_minutes", "load_high", "high_load_minutes",
          "window_minutes", "dnd_on", "dnd_blocked_seconds", "break_blocked_seconds", "reason"}
         where "reason" is a short sentence on why an alert was or was not suggested.
    """
    sustained_minutes = config.get("dnd.sustained_minutes")
    window = config.get("breaks.window_minutes")
    threshold = config.get("breaks.load_threshold")
    checks = {
        "in_call": in_call(frontmost_app, config.get("quiet.call_apps"), current_domain, config.get("quiet.call_domains")),
        "quiet_hours": in_quiet_hours(now_local, config.get("quiet.quiet_hours")),
        "pressure_sustained": pressure_is_sustained(recent, sustained_minutes, config.get("dnd.sustained_fraction")),
        "pressured_minutes": f"{sum(1 for m in recent[-sustained_minutes:] if m['condition'] in PRESSURE_CONDITIONS)}/{sustained_minutes}",
        "load_high": load_is_sustained_high(recent, window, threshold, config.get("breaks.high_fraction")),
        "high_load_minutes": f"{sum(1 for m in recent[-window:] if m['load_score'] is not None and m['load_score'] > threshold)}/{window}",
        "window_minutes": len(recent),
        "dnd_on": now < state.dnd_on_until,
        "dnd_blocked_seconds": max(0, round(state.dnd_ask_blocked_until - now)),
        "break_blocked_seconds": max(0, round(state.break_blocked_until - now)),
    }
    if checks["in_call"]:
        reason = "never interrupt: a call is in front"
    elif checks["quiet_hours"]:
        reason = "never interrupt: quiet hours"
    elif checks["pressure_sustained"] and checks["dnd_on"]:
        reason = "pressure is sustained but DND is already on"
    elif checks["pressure_sustained"] and checks["dnd_blocked_seconds"]:
        reason = f"pressure is sustained but DND is in cooldown for {checks['dnd_blocked_seconds']} s"
    elif checks["load_high"] and checks["break_blocked_seconds"]:
        reason = f"load is high but breaks are in cooldown/snooze for {checks['break_blocked_seconds']} s"
    elif checks["pressure_sustained"] or checks["load_high"]:
        reason = "rules met"
    elif len(recent) < min(sustained_minutes, window):
        reason = f"not enough history yet ({len(recent)} active minutes)"
    else:
        reason = "no sustained pressure or high load"
    checks["reason"] = reason
    return checks


# ---------------------------------------------------------------- updating the state after an alert

def after_dnd_answer(state: DecisionState, action: str, now: float, config) -> DecisionState:
    """
    Update the state after the DND question was answered.

    In:  state, the action ("yes", "auto", "not_now" or "no_answer"), current time, config.
    Out: the new state. "yes"/"auto" turn DND on for dnd.duration_minutes; after it ends we
         wait dnd.ask_cooldown_minutes before asking again. Otherwise we wait the cooldown from now.
    """
    cooldown = config.get("dnd.ask_cooldown_minutes") * SECONDS_PER_MINUTE
    if action in ("yes", "auto"):
        state.dnd_on_until = now + config.get("dnd.duration_minutes") * SECONDS_PER_MINUTE
        state.dnd_ask_blocked_until = state.dnd_on_until + cooldown
    else:
        state.dnd_ask_blocked_until = now + cooldown
    return state


def after_break_answer(state: DecisionState, action: str, now: float, config) -> DecisionState:
    """
    Update the state after a break suggestion.

    In:  state, the action ("yes", "snooze_30", "snooze_60", "dismiss", "no_answer"), time, config.
    Out: the new state. A snooze asks again after exactly the snooze time (the user asked for it);
         every other answer waits the normal cooldown (breaks.cooldown_minutes).
    """
    snooze_minutes = {"snooze_30": 30, "snooze_60": 60}
    if action in snooze_minutes:
        state.break_blocked_until = now + snooze_minutes[action] * SECONDS_PER_MINUTE
    else:
        state.break_blocked_until = now + config.get("breaks.cooldown_minutes") * SECONDS_PER_MINUTE
    return state
