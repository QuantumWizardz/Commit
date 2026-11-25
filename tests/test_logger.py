"""
tests/test_logger.py — the input counter (agent/logger.py) and app tracker (agent/app_tracker.py).

Key events are simulated with pynput key objects; no real keyboard is needed.
"""

from pynput.keyboard import Key, KeyCode

from agent.app_tracker import AppTracker, category_for_app
from agent.logger import KEY_ERROR, KEY_MODIFIER, KEY_NORMAL, KEY_SHORTCUT, InputCounter, classify_key


class FakeClock:
    """A clock we move by hand."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


def make_counter(clock=None):
    return InputCounter(pause_threshold_seconds=2, pause_max_seconds=60, clock=clock or FakeClock())


def test_classify_key():
    assert classify_key(KeyCode.from_char("a"), False) == KEY_NORMAL
    assert classify_key(Key.backspace, False) == KEY_ERROR
    assert classify_key(Key.delete, False) == KEY_ERROR
    assert classify_key(KeyCode.from_char("c"), True) == KEY_SHORTCUT
    assert classify_key(Key.cmd, False) == KEY_MODIFIER
    assert classify_key(Key.shift, False) == KEY_MODIFIER


def test_counts_keys_errors_and_shortcuts():
    counter = make_counter()
    for character in "hi":
        counter.on_key_press(KeyCode.from_char(character))
    counter.on_key_press(Key.backspace)
    counter.on_key_press(Key.cmd)                 # modifier alone: not a keystroke
    counter.on_key_press(KeyCode.from_char("s"))  # Cmd+S: shortcut
    counter.on_key_release(Key.cmd)
    counter.on_key_press(KeyCode.from_char("x"))  # Cmd released: normal again
    counts = counter.snapshot_and_reset()
    assert counts["keystrokes"] == 5
    assert counts["error_keys"] == 1
    assert counts["shortcut_keys"] == 1


def test_mouse_counts_and_distance():
    counter = make_counter()
    counter.on_move(0, 0)
    counter.on_move(3, 4)          # 5 pixels
    counter.on_click(3, 4, None, True)
    counter.on_click(3, 4, None, False)   # release is not counted
    counter.on_scroll(3, 4, 0, -1)
    counts = counter.snapshot_and_reset()
    assert counts["mouse_distance"] == 5.0
    assert counts["clicks"] == 1
    assert counts["scrolls"] == 1


def test_pauses_and_active_seconds():
    clock = FakeClock(1000.0)
    counter = make_counter(clock)
    counter.on_key_press(KeyCode.from_char("a"))   # t = 1000
    clock.now = 1001.0
    counter.on_key_press(KeyCode.from_char("a"))   # gap 1 s: not a pause
    clock.now = 1006.0
    counter.on_key_press(KeyCode.from_char("a"))   # gap 5 s: pause
    clock.now = 1080.0
    counter.on_key_press(KeyCode.from_char("a"))   # gap 74 s: too long to be a pause
    counts = counter.snapshot_and_reset()
    assert counts["pause_count"] == 1
    assert counts["pause_total_seconds"] == 5.0
    assert counts["active_seconds"] == 4


def test_snapshot_resets_counts():
    counter = make_counter()
    counter.on_key_press(KeyCode.from_char("a"))
    counter.snapshot_and_reset()
    assert counter.snapshot_and_reset()["keystrokes"] == 0


def test_paused_counter_ignores_everything():
    counter = make_counter()
    counter.set_paused(True)
    counter.on_key_press(KeyCode.from_char("a"))
    counter.on_move(0, 0)
    counter.on_move(10, 0)
    counter.on_click(0, 0, None, True)
    counts = counter.snapshot_and_reset()
    assert counts["keystrokes"] == 0 and counts["clicks"] == 0 and counts["mouse_distance"] == 0


def test_app_tracker_switches_and_seconds():
    apps = iter(["Code", "Code", "Slack", "Code"])
    tracker = AppTracker(lambda: next(apps), sample_seconds=5, app_categories={"Code": "Work", "Slack": "Communication"})
    for _ in range(4):
        tracker.take_sample()
    summary = tracker.snapshot_and_reset()
    assert summary["app_switches"] == 2
    assert summary["app_seconds"] == {"Code": 15, "Slack": 5}
    assert summary["main_app"] == "Code"
    assert summary["main_category"] == "Work"
    assert tracker.snapshot_and_reset()["app_switches"] == 0


def test_unknown_app_category():
    assert category_for_app("Some App", {"Code": "Work"}) == "Other"
    assert category_for_app(None, {}) == "Other"
