"""
agent/logger.py — counts keyboard and mouse activity per minute (README module M1.2).

PRIVACY (rule P1): we never store which key was pressed. Each key event is looked at in
memory only to decide its TYPE (normal / error / shortcut / modifier) and is then dropped.
Only counts leave this file. Nothing here is ever written to the log file.

Counts per minute:
    keystrokes            key presses (modifier keys pressed alone are not counted)
    error_keys            backspace + delete presses
    shortcut_keys         key presses while Cmd/Ctrl/Alt is held
    pause_count           gaps between input events longer than 2 s (and shorter than 60 s)
    pause_total_seconds   total length of those gaps
    active_seconds        number of seconds in the minute with any input
    clicks                mouse button presses
    scrolls               scroll events
    mouse_distance        pointer distance in pixels

Two classes:
    InputCounter — pure counting logic (no OS access, easy to test)
    InputLogger  — connects InputCounter to the real keyboard/mouse with pynput
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable

from pynput import keyboard, mouse

log = logging.getLogger(__name__)

# Key types.
KEY_NORMAL = "normal"
KEY_ERROR = "error"
KEY_SHORTCUT = "shortcut"
KEY_MODIFIER = "modifier"


def keys_named(*names: str) -> set:
    """
    Collect pynput special keys by name, skipping names this OS does not have (e.g. alt_gr).

    In:  attribute names of pynput.keyboard.Key.
    Out: a set of Key members.
    """
    return {getattr(keyboard.Key, name) for name in names if hasattr(keyboard.Key, name)}


# Modifiers that turn a key press into a shortcut.
SHORTCUT_MODIFIERS = keys_named("cmd", "cmd_l", "cmd_r", "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr")

# All modifier keys (pressed alone they are not counted as key presses).
MODIFIER_KEYS = SHORTCUT_MODIFIERS | keys_named("shift", "shift_l", "shift_r", "caps_lock", "fn")

# Keys that count as error corrections.
ERROR_KEYS = keys_named("backspace", "delete")


def classify_key(key, shortcut_modifier_held: bool) -> str:
    """
    Decide the TYPE of a key press. The key itself is not kept anywhere.

    In:  a pynput key object; whether Cmd/Ctrl/Alt is currently held.
    Out: KEY_MODIFIER, KEY_SHORTCUT, KEY_ERROR or KEY_NORMAL.
    """
    if key in MODIFIER_KEYS:
        return KEY_MODIFIER
    if shortcut_modifier_held:
        return KEY_SHORTCUT
    if key in ERROR_KEYS:
        return KEY_ERROR
    return KEY_NORMAL


class InputCounter:
    """Counts input events for the current minute. Thread-safe."""

    def __init__(self, pause_threshold_seconds: float, pause_max_seconds: float, clock: Callable[[], float] = time.time):
        """
        In:  pause thresholds from the config (logging.pause_threshold_seconds / pause_max_seconds);
             clock — function returning the current time (replaced in tests).
        """
        self.pause_threshold_seconds = pause_threshold_seconds
        self.pause_max_seconds = pause_max_seconds
        self.clock = clock
        self.lock = threading.Lock()
        self.paused = False
        self.held_shortcut_modifiers: set = set()
        self.last_event_time: float | None = None
        self.last_mouse_position: tuple[float, float] | None = None
        self.reset_counts()

    def reset_counts(self) -> None:
        """Start a new, empty minute."""
        self.keystrokes = 0
        self.error_keys = 0
        self.shortcut_keys = 0
        self.pause_count = 0
        self.pause_total_seconds = 0.0
        self.clicks = 0
        self.scrolls = 0
        self.mouse_distance = 0.0
        self.active_second_marks: set[int] = set()

    # ------------------------------------------------------------ shared step for every event

    def record_activity(self) -> None:
        """
        Note that some input happened now: mark this second as active and detect pauses.
        Must be called with the lock held.
        """
        now = self.clock()
        if self.last_event_time is not None:
            gap = now - self.last_event_time
            if self.pause_threshold_seconds < gap < self.pause_max_seconds:
                self.pause_count += 1
                self.pause_total_seconds += gap
        self.last_event_time = now
        self.active_second_marks.add(int(now))

    # ------------------------------------------------------------ keyboard events

    def on_key_press(self, key) -> None:
        """pynput callback: a key went down. Only its type is used (P1)."""
        with self.lock:
            if self.paused:
                return
            key_type = classify_key(key, bool(self.held_shortcut_modifiers))
            if key in SHORTCUT_MODIFIERS:
                self.held_shortcut_modifiers.add(key)
            self.record_activity()
            if key_type == KEY_MODIFIER:
                return
            self.keystrokes += 1
            if key_type == KEY_ERROR:
                self.error_keys += 1
            elif key_type == KEY_SHORTCUT:
                self.shortcut_keys += 1

    def on_key_release(self, key) -> None:
        """pynput callback: a key went up (only used to know when a modifier is released)."""
        with self.lock:
            self.held_shortcut_modifiers.discard(key)

    # ------------------------------------------------------------ mouse events

    def on_move(self, x: float, y: float) -> None:
        """pynput callback: the pointer moved to (x, y)."""
        with self.lock:
            if self.paused:
                return
            if self.last_mouse_position is not None:
                last_x, last_y = self.last_mouse_position
                self.mouse_distance += math.hypot(x - last_x, y - last_y)
            self.last_mouse_position = (x, y)
            self.record_activity()

    def on_click(self, x: float, y: float, button, pressed: bool) -> None:
        """pynput callback: a mouse button went down or up. Only presses are counted."""
        with self.lock:
            if self.paused or not pressed:
                return
            self.clicks += 1
            self.record_activity()

    def on_scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        """pynput callback: one scroll event."""
        with self.lock:
            if self.paused:
                return
            self.scrolls += 1
            self.record_activity()

    # ------------------------------------------------------------ reading the minute

    def snapshot_and_reset(self) -> dict:
        """
        Return this minute's counts and start a new minute.

        Out: dict with the nine counts listed at the top of this file.
        """
        with self.lock:
            counts = {
                "keystrokes": self.keystrokes,
                "error_keys": self.error_keys,
                "shortcut_keys": self.shortcut_keys,
                "pause_count": self.pause_count,
                "pause_total_seconds": round(self.pause_total_seconds, 1),
                "active_seconds": len(self.active_second_marks),
                "clicks": self.clicks,
                "scrolls": self.scrolls,
                "mouse_distance": round(self.mouse_distance, 1),
            }
            self.reset_counts()
            return counts

    def set_paused(self, paused: bool) -> None:
        """Pause (P10) or resume counting. While paused, events are ignored."""
        with self.lock:
            self.paused = paused
            self.held_shortcut_modifiers.clear()
            self.last_event_time = None
            self.last_mouse_position = None
            self.reset_counts()


class InputLogger:
    """Connects an InputCounter to the real keyboard and mouse (pynput)."""

    def __init__(self, counter: InputCounter):
        self.counter = counter
        self.keyboard_listener: keyboard.Listener | None = None
        self.mouse_listener: mouse.Listener | None = None

    def start(self) -> None:
        """Start listening. macOS needs Accessibility + Input Monitoring permission for this."""
        self.keyboard_listener = keyboard.Listener(
            on_press=self.counter.on_key_press, on_release=self.counter.on_key_release
        )
        self.mouse_listener = mouse.Listener(
            on_move=self.counter.on_move, on_click=self.counter.on_click, on_scroll=self.counter.on_scroll
        )
        self.keyboard_listener.start()
        self.mouse_listener.start()

    def has_permission(self) -> bool:
        """
        True if macOS allows us to see input events.

        pynput sets IS_TRUSTED on macOS once the listener is running; other systems have no flag.
        """
        if self.keyboard_listener is None:
            return False
        self.keyboard_listener.wait()
        return bool(getattr(self.keyboard_listener, "IS_TRUSTED", True))

    def stop(self) -> None:
        """Stop listening."""
        for listener in (self.keyboard_listener, self.mouse_listener):
            if listener is not None:
                listener.stop()
