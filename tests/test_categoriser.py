"""
tests/test_categoriser.py — domain rules, modes, consent, cache, language-model calls (with a fake
HTTP function), safe parsing, rate limit, and the heartbeat processor.
"""

import pytest
import requests

from server.categoriser import (
    BROWSING, HeartbeatProcessor, RateLimiter, TitleCategoriser, is_private, normalise_domain, parse_answer,
)

CATEGORIES = ["Work", "Learning", "Communication", "Entertainment", "Social media", "Browsing", "Other"]


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


class FakeModel:
    """Stands in for requests.post: records every request and returns a fixed answer."""

    def __init__(self, answer="Learning", fail=False):
        self.answer = answer
        self.fail = fail
        self.requests = []

    def __call__(self, url, json, headers, timeout):
        self.requests.append({"url": url, "json": json, "headers": headers})
        if self.fail:
            raise requests.ConnectionError("model offline")
        return FakeResponse(self.answer)


def consent(storage, **choices):
    base = {"activity_counts": True, "website_tracking": True, "title_local": True, "title_api": False, "checkins": True}
    base.update(choices)
    storage.set_setting("consent", {"version": 1, "date": "2026-11-24", "choices": base})


def make(storage, config, model=None, api_key=None, mode="local"):
    config.set("categoriser.mode", mode)
    return TitleCategoriser(storage, config, lambda: api_key, post=model or FakeModel())


# ---------------------------------------------------------------- helpers

def test_normalise_and_private_match():
    assert normalise_domain("WWW.Example.COM:8080") == "example.com"
    assert is_private("online.bank.com", ["bank.com"])
    assert is_private("bank.com", ["bank.com"])
    assert not is_private("notbank.com", ["bank.com"])


@pytest.mark.parametrize("answer, expected", [
    ("Learning", "Learning"),
    ("learning.", "Learning"),
    ("<think>maybe work?</think>\nEntertainment", "Entertainment"),
    ("Category: Social media", "Social media"),
    ("Work or Learning", BROWSING),       # two categories: unclear
    ("Gaming", BROWSING),                 # not in the list
    ("", BROWSING),
])
def test_parse_answer(answer, expected):
    assert parse_answer(answer, CATEGORIES) == expected


def test_rate_limiter():
    limiter = RateLimiter(2)
    assert limiter.allow(0) and limiter.allow(1)
    assert not limiter.allow(2)
    assert limiter.allow(3600)            # the first call is now older than an hour


# ---------------------------------------------------------------- rules and modes

def test_built_in_rule_and_subdomain(storage, config):
    consent(storage)
    model = FakeModel()
    categoriser = make(storage, config, model)
    assert categoriser.categorise("netflix.com", "Some show") == "Entertainment"
    assert categoriser.categorise("help.netflix.com", "Help") == "Entertainment"
    assert model.requests == []           # rules never call the model


def test_user_rule_beats_built_in(storage, config):
    consent(storage)
    storage.set_domain_rule("netflix.com", "Learning")
    assert make(storage, config).categorise("netflix.com", "Documentary") == "Learning"


def test_ambiguous_domain_uses_title(storage, config):
    consent(storage)
    model = FakeModel("Learning")
    assert make(storage, config, model).categorise("youtube.com", "Contract Law Lecture 5") == "Learning"
    assert len(model.requests) == 1


def test_off_and_rules_modes_never_call_model(storage, config):
    consent(storage)
    for mode in ("off", "rules"):
        model = FakeModel()
        assert make(storage, config, model, mode=mode).categorise("unknown-site.com", "A title") == BROWSING
        assert model.requests == []


def test_local_mode_without_consent_falls_back_to_rules(storage, config):
    consent(storage, title_local=False)
    model = FakeModel()
    assert make(storage, config, model).categorise("youtube.com", "Lecture") == BROWSING
    assert model.requests == []


def test_api_mode_needs_consent_and_key(storage, config):
    consent(storage, title_api=True)
    model = FakeModel()
    assert make(storage, config, model, api_key=None, mode="api").categorise("youtube.com", "x") == BROWSING
    consent(storage, title_api=False)
    assert make(storage, config, model, api_key="sk-test", mode="api").categorise("youtube.com", "x") == BROWSING
    assert model.requests == []


# ---------------------------------------------------------------- cache, fallback, P7

def test_cache_stores_hash_only_and_avoids_second_call(storage, config):
    consent(storage)
    model = FakeModel("Entertainment")
    categoriser = make(storage, config, model)
    title = "Dune Part Two | Official Trailer"
    assert categoriser.categorise("youtube.com", title) == "Entertainment"
    assert categoriser.categorise("youtube.com", title) == "Entertainment"
    assert len(model.requests) == 1
    (row,) = storage.execute("SELECT hash, category FROM title_cache")
    assert len(row[0]) == 64 and "Dune" not in row[0]


def test_offline_model_gives_browsing_and_is_not_cached(storage, config):
    consent(storage)
    offline = make(storage, config, FakeModel(fail=True))
    assert offline.categorise("youtube.com", "Lecture 1") == BROWSING
    assert storage.execute("SELECT * FROM title_cache") == []
    online = make(storage, config, FakeModel("Learning"))
    assert online.categorise("youtube.com", "Lecture 1") == "Learning"     # tried again next time


def test_api_request_contains_only_redacted_title(storage, config):
    consent(storage, title_api=True)
    config.set("categoriser.api", {"base_url": "https://api.example.com/v1", "model": "small-model", "extra_body": {}})
    model = FakeModel("Work")
    categoriser = make(storage, config, model, api_key="sk-secret", mode="api")
    raw_title = "Invoice 99887766 for priya@example.com https://shop.example.com/order " + "x" * 200
    categoriser.categorise("shop.example.com", raw_title)

    (request,) = model.requests
    assert request["url"] == "https://api.example.com/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer sk-secret"
    body_text = str(request["json"])
    for secret in ("99887766", "priya@example.com", "https://", "shop.example.com"):
        assert secret not in body_text        # no long numbers, e-mails, links, and no domain in API mode
    user_message = request["json"]["messages"][1]["content"]
    assert user_message.startswith("Title: Invoice for")
    assert len(user_message) <= len("Title: ") + config.get("categoriser.title_max_chars")
    assert request["json"]["temperature"] == 0


def test_rate_limit_falls_back(storage, config):
    consent(storage)
    config.set("categoriser.max_llm_calls_per_hour", 1)
    model = FakeModel("Learning")
    categoriser = make(storage, config, model)
    assert categoriser.categorise("youtube.com", "Lecture 1") == "Learning"
    assert categoriser.categorise("youtube.com", "Lecture 2") == BROWSING
    assert len(model.requests) == 1


# ---------------------------------------------------------------- heartbeats

def make_processor(storage, config, model=None):
    return HeartbeatProcessor(storage, config, make(storage, config, model))


def test_heartbeat_saved_without_title(storage, config):
    consent(storage)
    processor = make_processor(storage, config, FakeModel("Learning"))
    assert processor.submit("www.youtube.com", "Contract Law Lecture 5", None, 30)
    processor.process_pending()
    assert storage.execute("SELECT domain, category, seconds FROM web_time") == [("youtube.com", "Learning", 30)]
    assert processor.take_received_seconds() == 30
    assert processor.take_received_seconds() == 0


def test_private_and_other_categories(storage, config):
    consent(storage)
    storage.add_private_domain("bank.com")
    processor = make_processor(storage, config)
    processor.submit(None, None, "Private", 10)
    processor.submit(None, None, "Other", 5)
    processor.submit("online.bank.com", "My account", None, 7)    # extension's list was out of date
    processor.process_pending()
    assert storage.execute("SELECT domain, category, seconds FROM web_time") == [
        (None, "Private", 10), (None, "Other", 5), (None, "Private", 7)]


def test_heartbeats_dropped_without_consent_or_when_paused(storage, config):
    consent(storage, website_tracking=False)
    processor = make_processor(storage, config)
    assert not processor.submit("example.com", "x", None, 10)
    consent(storage)
    storage.set_setting("paused", True)
    assert not processor.submit("example.com", "x", None, 10)
    processor.process_pending()
    assert storage.execute("SELECT * FROM web_time") == []


def test_heartbeat_seconds_are_capped(storage, config):
    consent(storage)
    processor = make_processor(storage, config)
    processor.submit(None, None, "Other", 99999)
    processor.process_pending()
    assert storage.execute("SELECT seconds FROM web_time") == [(config.get("categoriser.heartbeat_max_seconds"),)]


def test_current_domain_expires(storage, config):
    consent(storage)
    clock = {"now": 1000.0}
    processor = HeartbeatProcessor(storage, config, make(storage, config), clock=lambda: clock["now"])
    processor.submit("meet.google.com", "Meeting", None, 30)
    assert processor.current_domain(90) == "meet.google.com"
    clock["now"] += 91
    assert processor.current_domain(90) is None


def test_commit_dashboard_heartbeats_are_not_saved(storage, config):
    from server.categoriser import HeartbeatProcessor
    consent(storage)
    processor = HeartbeatProcessor(storage, config, make(storage, config))
    assert processor.submit(None, None, "Commit", 30)
    assert processor.submit("127.0.0.1", "Commit", None, 20)          # extension older than 0.3.0
    assert processor.submit("localhost", "My dev app", None, 10)      # another local page: a normal site
    processor.process_pending()
    assert storage.execute("SELECT domain, seconds FROM web_time") == [("localhost", 10)]
    assert processor.take_commit_seconds() == 50 and processor.take_commit_seconds() == 0
    assert processor.take_received_seconds() == 60
