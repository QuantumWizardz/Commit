"""
tests/test_consent_actions.py — first-launch consent flow, DND controller and alert flows,
using FakeSystem instead of real dialogs and Shortcuts.
"""

import time

from agent import consent
from agent.actions import DND_UNTIL_KEY, AlertFlows, DndController
from tests.conftest import FakeSystem


def test_onboarding_saves_separate_choices(storage, config):
    system = FakeSystem(answers=[
        "Continue",                                   # welcome
        "I agree", "Yes", "Yes", "No", "Yes",         # five consent switches
        "Continue",                                   # permissions
        "Test Focus On", "OK", "Continue",            # shortcuts (with one test)
        "OK",                                         # allowlist explanation
    ])
    assert consent.run_onboarding(system, storage, config)
    saved = storage.get_setting("consent")
    assert saved["version"] == consent.CONSENT_VERSION
    assert saved["choices"] == {"activity_counts": True, "website_tracking": True, "title_local": True,
                                "title_api": False, "checkins": True}
    assert "date" in saved
    assert system.shortcuts_run == ["Commit Focus On"]
    assert consent.has_valid_consent(storage)


def test_refusing_activity_counts_stops_setup(storage, config):
    system = FakeSystem(answers=["Continue", "Quit Commit"])
    assert not consent.run_onboarding(system, storage, config)
    assert storage.get_setting("consent") is None
    assert not consent.has_valid_consent(storage)


def test_consent_timeout_returns_none():
    assert consent.ask_consent_choices(FakeSystem(answers=[]), 1) is None


def test_dnd_turn_on_and_off(storage, config):
    system = FakeSystem()
    dnd = DndController(system, storage, config)
    assert dnd.turn_on()
    assert storage.get_setting(DND_UNTIL_KEY) > time.time()
    dnd.turn_off()
    assert system.shortcuts_run == ["Commit Focus On", "Commit Focus Off"]
    assert "Do Not Disturb is off again." in system.notifications
    assert storage.get_setting(DND_UNTIL_KEY) is None


def test_dnd_missing_shortcut_shows_help_and_does_not_crash(storage, config):
    system = FakeSystem(answers=["Open setup guide"], shortcuts_work=False)
    dnd = DndController(system, storage, config)
    assert not dnd.turn_on()
    assert system.opened and system.opened[0].endswith("SHORTCUTS_SETUP.md")


def test_dnd_restore_turns_off_expired_session(storage, config):
    storage.set_setting(DND_UNTIL_KEY, time.time() - 5)
    system = FakeSystem()
    DndController(system, storage, config).restore_after_restart()
    assert system.shortcuts_run == ["Commit Focus Off"]


def test_always_automatic_switches_mode(storage, config):
    system = FakeSystem(answers=["Always do this automatically", "👎"])
    answers = []
    flows = AlertFlows(system, storage, config, DndController(system, storage, config), record_answer=lambda *a: answers.append(a[:2]))
    flows.dnd_flow("test reason")
    assert config.get("dnd.mode") == "auto"
    assert answers == [("dnd", "auto")]
    assert storage.execute("SELECT action, feedback FROM alerts")[0] == ("auto", "down")


def test_break_flow_snooze_and_no_answer(storage, config):
    system = FakeSystem(answers=["Snooze 30 min", "👍"])
    answers = []
    flows = AlertFlows(system, storage, config, DndController(system, storage, config), record_answer=lambda *a: answers.append(a[:2]))
    flows.break_flow("test reason")
    flows.break_flow("test reason")          # no answers left -> dialog "timed out"
    assert answers == [("break", "snooze_30"), ("break", "no_answer")]
    rows = storage.execute("SELECT action, feedback FROM alerts ORDER BY id")
    assert rows == [("snooze_30", "up"), ("no_answer", None)]


def test_checkin_saved(storage, config):
    system = FakeSystem(answers=["4"])
    flows = AlertFlows(system, storage, config, DndController(system, storage, config), record_answer=lambda *a: None)
    flows.checkin_flow()
    assert [rating for _, rating in storage.all_checkins()] == [4]
