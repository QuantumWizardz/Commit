"""
tests/test_privacy.py — automated checks of the privacy rules (README section 16.3).

P1   typed text is never stored in the database or the log file
P9   "Delete all my data" removes the database, consent record, API key and logs
P11  data older than the retention period is deleted
P12  the log file never contains typed text
P3   titles are never stored or logged
P4   private domain names never appear in website time, the cache or logs
P8   the API key lives only in the keychain
P7   (only the redacted, shortened title is sent in API mode) is tested in test_categoriser.py
P5   (incognito = Miscellaneous) is tested in test_engine.py
"""

import logging
from pathlib import Path

import pytest
from pynput.keyboard import KeyCode

import agent.main as agent_main
from agent import config as agent_config
from agent import keychain
from agent.storage import Storage
from agent.logger import InputCounter

SECRET_TEXT = "MySecretPassw0rd"


def type_text(counter, text):
    """Send each character of `text` to the counter, like pynput would."""
    for character in text:
        counter.on_key_press(KeyCode.from_char(character))
        counter.on_key_release(KeyCode.from_char(character))


def test_typed_text_never_reaches_database_or_logs(storage, tmp_path):
    # Capture everything the agent logs during the test into a file.
    log_file = tmp_path / "commit.log"
    handler = logging.FileHandler(log_file)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    try:
        counter = InputCounter(2, 60)
        type_text(counter, SECRET_TEXT)
        counts = counter.snapshot_and_reset()
        logging.getLogger("agent").info("Minute counts: %s", counts)
        storage.save_minute({"ts": 1, "mode": "active", "app_category": "Work", "features": counts,
                             "condition": None, "condition_probs": None, "load_score": None})
        storage.close()
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    assert counts["keystrokes"] == len(SECRET_TEXT)
    for file in (storage.path, log_file):
        content = file.read_bytes()
        assert SECRET_TEXT.encode() not in content
        assert b"Secret" not in content


def test_counter_keeps_no_key_identity():
    # After typing, no attribute of the counter may hold the typed characters.
    counter = InputCounter(2, 60)
    type_text(counter, SECRET_TEXT)
    state = repr(vars(counter))
    assert "Secret" not in state
    assert "'M'" not in state and "'y'" not in state   # not even single characters are kept


def test_delete_all_my_data(storage, tmp_path, monkeypatch):
    storage.set_setting("consent", {"version": 1, "choices": {"activity_counts": True}})
    storage.add_checkin(1, 3)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "commit.log").write_text("x")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "commit-week-2026-11-16.pdf").write_bytes(b"%PDF")

    deleted_keys = []
    monkeypatch.setattr(agent_main, "log_folder", lambda: logs)
    monkeypatch.setattr(keychain.keyring, "delete_password", lambda service, user: deleted_keys.append((service, user)))

    agent_main.delete_everything(storage, reports_folder=reports)

    assert not storage.path.exists()
    assert not logs.exists()
    assert not reports.exists()
    assert deleted_keys == [(keychain.SERVICE, keychain.USERNAME)]


def test_retention_deletes_old_rows(storage):
    day = 24 * 60 * 60
    now = 100 * day
    storage.save_minute({"ts": now - 31 * day, "mode": "active"})
    storage.save_minute({"ts": now - 1 * day, "mode": "active"})
    storage.add_checkin(now - 40 * day, 3)
    storage.delete_older_than(30, now)
    assert [row[0] for row in storage.execute("SELECT ts FROM minutes")] == [now - day]
    assert storage.all_checkins() == []


def test_database_is_a_local_file(storage):
    # P6: a plain SQLite file on this computer.
    assert storage.path.exists()
    assert storage.path.read_bytes()[:16] == b"SQLite format 3\x00"


@pytest.mark.parametrize("column", ["minutes", "app_time"])
def test_no_text_columns_for_typed_content(storage, column):
    # The schema has no column that could hold typed text or window titles.
    names = [row[1] for row in storage.execute(f"PRAGMA table_info({column})")]
    assert not any(word in name for name in names for word in ("text", "title", "key", "url"))


# ---------------------------------------------------------------- Phase 2: titles, private sites, API key

def run_heartbeats_and_capture_log(storage, config, tmp_path, heartbeats, model_answer="Learning"):
    """Process heartbeats through the real server code while capturing all log output to a file."""
    from tests.test_categoriser import FakeModel, consent, make_processor

    consent(storage)
    log_file = tmp_path / "phase2.log"
    handler = logging.FileHandler(log_file)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    try:
        processor = make_processor(storage, config, FakeModel(model_answer))
        for domain, title, category, seconds in heartbeats:
            processor.submit(domain, title, category, seconds)
        processor.process_pending()
        storage.close()
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    return log_file


def test_titles_never_stored_or_logged(storage, config, tmp_path):
    # P3: the title is used for the category, then discarded.
    title = "Secret Project Falcon Kickoff"
    log_file = run_heartbeats_and_capture_log(storage, config, tmp_path, [("youtube.com", title, None, 30)])
    for file in (storage.path, log_file):
        assert b"Falcon" not in file.read_bytes()


def test_private_domain_name_not_in_time_cache_or_logs(storage, config, tmp_path):
    # P4: the private list itself holds the name (the user typed it there); nothing else may.
    storage.add_private_domain("mysecretbank.com")
    log_file = run_heartbeats_and_capture_log(storage, config, tmp_path, [
        ("online.mysecretbank.com", "Account overview", None, 20),   # caught by the server's safety net
        (None, None, "Private", 15),                                  # normal case: extension already hid it
    ])
    reopened = Storage(storage.path)
    assert reopened.execute("SELECT domain, category FROM web_time") == [(None, "Private"), (None, "Private")]
    assert reopened.execute("SELECT * FROM title_cache") == []
    reopened.close()
    assert b"mysecretbank" not in log_file.read_bytes()


def test_api_key_only_in_keychain(storage, config, tmp_path, monkeypatch):
    # P8: setting and using the API key never writes it to the database, config or logs.
    from tests.test_categoriser import FakeModel, consent
    from server.categoriser import TitleCategoriser

    saved = {}
    monkeypatch.setattr(keychain.keyring, "set_password", lambda service, user, value: saved.update({(service, user): value}))
    monkeypatch.setattr(keychain.keyring, "get_password", lambda service, user: saved.get((service, user)))
    api_key = "sk-test-DO-NOT-STORE-123"
    keychain.set_api_key(api_key)

    consent(storage, title_api=True)
    config.set("categoriser.mode", "api")
    log_file = tmp_path / "key.log"
    handler = logging.FileHandler(log_file)
    logging.getLogger().addHandler(handler)
    try:
        TitleCategoriser(storage, config, keychain.get_api_key, post=FakeModel("Work")).categorise("example.com", "Quarterly plan")
        storage.close()
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    assert saved == {(keychain.SERVICE, keychain.USERNAME): api_key}
    config_file = Path(agent_config.DEFAULT_CONFIG_FILE)
    for file in (storage.path, log_file, config_file):
        assert b"DO-NOT-STORE" not in file.read_bytes()
