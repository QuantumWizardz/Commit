"""
tests/conftest.py — shared test helpers.

FakeSystem replaces agent.platform.macos in tests: no real dialogs, notifications or Shortcuts.
"""

import pytest

from agent.config import Config
from agent.storage import Storage


class FakeSystem:
    """Records what the agent asked the OS to do and returns scripted answers."""

    def __init__(self, answers=None, shortcuts_work=True):
        self.answers = list(answers or [])    # answers returned by ask()/choose(), in order
        self.shortcuts_work = shortcuts_work
        self.notifications = []
        self.questions = []
        self.shortcuts_run = []
        self.opened = []

    def next_answer(self, prompt):
        self.questions.append(prompt)
        return self.answers.pop(0) if self.answers else None

    def ask(self, prompt, buttons, default_button=None, timeout_seconds=30):
        return self.next_answer(prompt)

    def choose(self, prompt, items, timeout_seconds=30):
        return self.next_answer(prompt)

    def notify(self, title, message):
        self.notifications.append(message)

    def run_shortcut(self, name):
        self.shortcuts_run.append(name)
        return self.shortcuts_work

    def shortcut_exists(self, name):
        return self.shortcuts_work

    def open_url(self, url):
        self.opened.append(url)

    def open_privacy_settings(self, pane):
        self.opened.append(pane)

    def get_frontmost_app(self):
        return "Code"


@pytest.fixture
def storage(tmp_path):
    """A fresh database in a temporary folder."""
    store = Storage(tmp_path / "test.db")
    yield store
    try:
        store.close()
    except Exception:
        pass


@pytest.fixture
def config(storage):
    """Configuration with the real defaults, overrides saved in the test database."""
    return Config(storage)


@pytest.fixture
def fake_system():
    return FakeSystem()
