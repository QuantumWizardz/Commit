"""
server/categoriser.py — turns (domain, title) into a category (README module M2.3).

Steps for each website heartbeat:
  1. Domain rules: the user's corrections, then the built-in table (config categoriser.domain_categories).
     Ambiguous domains (e.g. youtube.com) skip the built-in table: their TITLE decides.
  2. Mode check: Off → "Browsing" for everything; Rules only → "Browsing" when no rule matches.
  3. Cache: salted hash of domain + title → category (the title itself is never stored).
  4. Redaction: remove e-mails, links, long numbers; cut to 120 characters (server/redaction.py).
  5. Language model: local Ollama (default) or the user's own OpenAI-compatible API (only with consent, P7).
     At most 120 calls per hour. If the model is unavailable: "Browsing" now, try again next time.
  6. The heartbeat is saved as domain + category + seconds. The title is dropped.

HeartbeatProcessor runs steps on a background thread, so the extension's request never waits for
the language model ("never block"). It also tells the agent how much website time arrived each
minute (to detect incognito/no-extension time as "Miscellaneous") and the current domain (to
avoid interrupting Google Meet calls).
"""

from __future__ import annotations

import hashlib
import logging
import queue
import re
import secrets
import threading
import time
from collections import deque
from typing import Callable

import requests

from server.redaction import redact_title

log = logging.getLogger(__name__)

PRIVATE = "Private"
MISCELLANEOUS = "Miscellaneous"
OTHER = "Other"
BROWSING = "Browsing"
SPECIAL_CATEGORIES = (PRIVATE, OTHER)       # the extension may send these without a domain
COMMIT = "Commit"                           # Commit's own dashboard: never counted anywhere
LOCAL_HOSTS = ("127.0.0.1", "localhost")
COMMIT_PAGE_TITLE = "Commit"                # the dashboard's <title> (catches extensions older than 0.3.0)

MODE_OFF, MODE_RULES, MODE_LOCAL, MODE_API = "off", "rules", "local", "api"
SALT_KEY = "title_cache_salt"
CONSENT_KEY = "consent"
PAUSED_KEY = "paused"                       # set by the agent when the user pauses tracking (P10)
SECONDS_PER_HOUR = 3600
THINKING_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
HEARTBEAT_QUEUE_SIZE = 500                  # heartbeats waiting for categorisation; extra ones are dropped


# ---------------------------------------------------------------- small helpers

def normalise_domain(domain: str) -> str:
    """"WWW.Example.com:8080" -> "example.com" (lower case, no www., no port)."""
    domain = domain.strip().lower().split(":")[0].rstrip(".")
    return domain[4:] if domain.startswith("www.") else domain


def parent_domains(domain: str) -> list[str]:
    """"a.b.example.com" -> ["a.b.example.com", "b.example.com", "example.com"]."""
    parts = domain.split(".")
    return [".".join(parts[index:]) for index in range(len(parts) - 1)]


def is_private(domain: str, private_domains: list[str]) -> bool:
    """True if the domain or any parent domain is on the "Don't track" list (bank.com covers online.bank.com)."""
    return any(candidate in private_domains for candidate in parent_domains(domain))


def title_hash(salt: str, domain: str, title: str) -> str:
    """Salted SHA-256 of domain + title. The cache stores only this, never the title."""
    return hashlib.sha256(f"{salt}\n{domain}\n{title}".encode("utf-8")).hexdigest()


def parse_answer(answer: str, categories: list[str]) -> str:
    """
    Turn the model's reply into one category, safely.

    In:  the reply text (may contain a <think> block or extra words), the allowed categories.
    Out: the category if exactly one allowed category is named, otherwise "Browsing".
    """
    text = THINKING_BLOCK.sub("", answer).strip().strip(".\"'*` ").lower()
    for category in categories:
        if text == category.lower():
            return category
    mentioned = [c for c in categories if re.search(rf"\b{re.escape(c.lower())}\b", text)]
    return mentioned[0] if len(mentioned) == 1 else BROWSING


def build_messages(categories: list[str], title: str, domain: str | None) -> list[dict]:
    """
    The chat messages for the model: ask for exactly one category word.

    In:  categories, the REDACTED title, and the domain (only given in local mode; in API mode
         only the title leaves the computer, P7).
    """
    instruction = (
        "You sort web pages into categories. Reply with exactly one category from this list and nothing else: "
        + ", ".join(categories) + "."
    )
    page = f"Title: {title}" if domain is None else f"Website: {domain}\nTitle: {title}"
    return [{"role": "system", "content": instruction}, {"role": "user", "content": page}]


def is_commit_page(domain: str | None, title: str | None, category: str | None) -> bool:
    """
    True for a heartbeat from Commit's own dashboard: the extension sends category "Commit"
    (since 0.3.0); older versions sent domain 127.0.0.1/localhost with the page title "Commit".
    """
    if category == COMMIT:
        return True
    return domain is not None and normalise_domain(domain) in LOCAL_HOSTS and (title or "").strip() == COMMIT_PAGE_TITLE


class RateLimiter:
    """At most `limit` events per rolling hour."""

    def __init__(self, limit: int):
        self.limit = limit
        self.times: deque[float] = deque()

    def allow(self, now: float) -> bool:
        """True (and counts the event) if another call is allowed now."""
        while self.times and now - self.times[0] >= SECONDS_PER_HOUR:
            self.times.popleft()
        if len(self.times) >= self.limit:
            return False
        self.times.append(now)
        return True


# ---------------------------------------------------------------- the categoriser

class TitleCategoriser:
    """Rules → cache → language model."""

    def __init__(self, storage, config, get_api_key: Callable[[], str | None], post=requests.post, clock=time.time):
        """
        In:  storage, config, a function returning the API key from the keychain, the HTTP POST
             function (replaced in tests) and the clock.
        """
        self.storage = storage
        self.config = config
        self.get_api_key = get_api_key
        self.post = post
        self.clock = clock
        self.rate_limiter = RateLimiter(config.get("categoriser.max_llm_calls_per_hour"))

    def salt(self) -> str:
        """Random salt for the cache hashes, created once and kept in the settings."""
        salt = self.storage.get_setting(SALT_KEY)
        if salt is None:
            salt = secrets.token_hex(16)
            self.storage.set_setting(SALT_KEY, salt)
        return salt

    def effective_mode(self) -> str:
        """
        The configured mode, lowered when consent or the API key is missing:
        local needs consent switch 3; api needs switch 4 AND a saved key. Otherwise → rules.
        """
        mode = self.config.get("categoriser.mode")
        choices = (self.storage.get_setting(CONSENT_KEY) or {}).get("choices", {})
        if mode == MODE_LOCAL and not choices.get("title_local"):
            return MODE_RULES
        if mode == MODE_API and not (choices.get("title_api") and self.get_api_key()):
            return MODE_RULES
        return mode

    def rule_category(self, domain: str) -> str | None:
        """Step 1: the user's rule, else the built-in rule (not for ambiguous domains)."""
        user_rules = self.storage.domain_rules()
        built_in = self.config.get("categoriser.domain_categories")
        ambiguous = self.config.get("categoriser.ambiguous_domains")
        for candidate in parent_domains(domain):
            if candidate in user_rules:
                return user_rules[candidate]
        for candidate in parent_domains(domain):
            if candidate in ambiguous:
                return None
            if candidate in built_in:
                return built_in[candidate]
        return None

    def categorise(self, domain: str, title: str | None) -> str:
        """
        Category for one (domain, title). The title is only used inside this call.

        In:  normalised domain, the page title (may be None/empty).
        Out: a category name.
        """
        return self.categorise_with_source(domain, title)[0]

    def categorise_with_source(self, domain: str, title: str | None) -> tuple[str, str]:
        """
        Like categorise(), but also says how the category was chosen (shown in Developer mode).

        Out: (category, source) where source is one of "rule", "no title", "mode off", "mode rules",
             "cache", "local model", "api model", "rate limited", "model unavailable".
        """
        rule = self.rule_category(domain)
        if rule is not None:
            return rule, "rule"
        mode = self.effective_mode()
        if mode in (MODE_OFF, MODE_RULES):
            return BROWSING, f"mode {mode}"
        if not title:
            return BROWSING, "no title"

        key = title_hash(self.salt(), domain, title)
        cached = self.storage.cached_category(key)
        if cached is not None:
            return cached, "cache"

        redacted = redact_title(title, self.config.get("categoriser.title_max_chars"))
        if not redacted or not self.rate_limiter.allow(self.clock()):
            return BROWSING, "rate limited"  # not cached: try again next time

        try:
            answer = self.ask_model(mode, redacted, domain)
        except Exception as error:  # offline, timeout, bad key ... never block, never crash
            log.info("Language model unavailable (%s); using Browsing for now.", type(error).__name__)
            return BROWSING, "model unavailable"
        category = parse_answer(answer, self.config.get("categoriser.categories"))
        self.storage.cache_category(key, category, int(self.clock()))
        return category, f"{mode} model"

    def ask_model(self, mode: str, redacted_title: str, domain: str) -> str:
        """
        Send the redacted title to the local or API model (OpenAI-compatible /chat/completions).

        Out: the model's reply text. Raises on any network/HTTP error.
        """
        settings = self.config.get(f"categoriser.{mode}")
        headers = {"Content-Type": "application/json"}
        if mode == MODE_API:
            headers["Authorization"] = f"Bearer {self.get_api_key()}"
        body = {
            "model": settings["model"],
            "messages": build_messages(self.config.get("categoriser.categories"), redacted_title, domain if mode == MODE_LOCAL else None),
            "temperature": 0,
        }
        # Provider-specific extras from the config (e.g. turn off "thinking" for local models).
        body.update(settings.get("extra_body") or {})
        response = self.post(
            settings["base_url"].rstrip("/") + "/chat/completions",
            json=body, headers=headers, timeout=self.config.get("categoriser.llm_timeout_seconds"),
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or ""

    def test_connection(self) -> tuple[bool, str]:
        """
        "Test connection" button: one short request with a made-up title.

        Out: (worked?, message for the user).
        """
        mode = self.config.get("categoriser.mode")
        if mode not in (MODE_LOCAL, MODE_API):
            return False, "Choose Local LLM or API key mode first."
        if mode == MODE_API and not self.get_api_key():
            return False, "No API key saved yet."
        try:
            answer = self.ask_model(mode, "Introduction to linear algebra, lecture 1", "youtube.com")
        except Exception as error:
            return False, f"Could not reach the model ({type(error).__name__}). Is it running, and are the URL and model name right?"
        return True, f"Connected. Test answer: {parse_answer(answer, self.config.get('categoriser.categories'))}"


# ---------------------------------------------------------------- heartbeats

class HeartbeatProcessor:
    """Queues heartbeats from the extension and saves them on a background thread."""

    def __init__(self, storage, config, categoriser: TitleCategoriser, clock=time.time, dev_log=None):
        """dev_log: the Developer mode DevLog (agent/devlog.py) or None. It never receives titles."""
        self.dev_log = dev_log
        self.storage = storage
        self.config = config
        self.categoriser = categoriser
        self.clock = clock
        self.pending: queue.Queue = queue.Queue(maxsize=HEARTBEAT_QUEUE_SIZE)
        self.lock = threading.Lock()
        self.received_seconds = 0          # website seconds received since the agent last asked
        self.commit_seconds = 0            # of those, seconds on the Commit dashboard (not counted anywhere)
        self.last_domain: str | None = None
        self.last_domain_time = 0.0
        self.stop_event = threading.Event()

    def submit(self, domain: str | None, title: str | None, category: str | None, seconds: int) -> bool:
        """
        Accept one heartbeat (called by the API route). Returns immediately.

        Out: False if it was dropped (website tracking not consented, tracking paused, or queue full).
        """
        choices = (self.storage.get_setting(CONSENT_KEY) or {}).get("choices", {})
        if not choices.get("website_tracking") or self.storage.get_setting(PAUSED_KEY, False):
            return False
        seconds = min(int(seconds), self.config.get("categoriser.heartbeat_max_seconds"))
        now = self.clock()
        if is_commit_page(domain, title, category):
            # The browser was on Commit's own dashboard: tell the agent (so it removes that time from the
            # browser's app time and does not record "Miscellaneous"), but save nothing.
            with self.lock:
                self.received_seconds += seconds
                self.commit_seconds += seconds
                self.last_domain = None
            self.dev(f"Commit dashboard · {seconds} s (not counted)", category=COMMIT, seconds=seconds)
            return True
        with self.lock:
            self.received_seconds += seconds
            self.last_domain = normalise_domain(domain) if domain else None
            self.last_domain_time = now
        try:
            self.pending.put_nowait((int(now) - seconds, domain, title, category, seconds))
        except queue.Full:
            log.warning("Too many website heartbeats waiting; one was dropped.")
            return False
        return True

    def save(self, ts: int, domain: str | None, title: str | None, category: str | None, seconds: int) -> None:
        """Categorise one heartbeat and save domain + category + seconds. The title goes out of scope here."""
        if category in SPECIAL_CATEGORIES or not domain:
            saved = category if category in SPECIAL_CATEGORIES else OTHER
            self.storage.save_web_time(ts, None, saved, seconds)
            self.dev(f"{saved} page · {seconds} s (no site name kept)", category=saved, seconds=seconds, source="extension")
            return
        domain = normalise_domain(domain)
        if is_private(domain, self.storage.private_domains()):
            # Safety net: the extension should already have hidden it (P4).
            self.storage.save_web_time(ts, None, PRIVATE, seconds)
            self.dev(f"Private site · {seconds} s (no site name kept)", category=PRIVATE, seconds=seconds, source="private list")
            return
        chosen, source = self.categoriser.categorise_with_source(domain, title)
        self.storage.save_web_time(ts, domain, chosen, seconds)
        self.dev(f"{domain} → {chosen} · {seconds} s (by {source})", domain=domain, category=chosen, seconds=seconds, source=source)

    def dev(self, message: str, /, **data) -> None:
        """Add a "website" event to the Developer mode log, if there is one. Never pass the title here (P3)."""
        if self.dev_log is not None:
            self.dev_log.add("website", message, **data)

    def process_pending(self) -> None:
        """Save every queued heartbeat now (also used by tests)."""
        while True:
            try:
                item = self.pending.get_nowait()
            except queue.Empty:
                return
            try:
                self.save(*item)
            except Exception:
                log.exception("Saving a website heartbeat failed; continuing.")

    def run(self) -> None:
        """Background loop: wait for heartbeats and save them."""
        while not self.stop_event.is_set():
            try:
                item = self.pending.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.save(*item)
            except Exception:
                log.exception("Saving a website heartbeat failed; continuing.")

    def start(self) -> None:
        threading.Thread(target=self.run, name="heartbeats", daemon=True).start()

    def stop(self) -> None:
        self.stop_event.set()

    # ------------------------------------------------------------ for the agent

    def take_received_seconds(self) -> int:
        """Website seconds received since the last call (the agent calls this once a minute)."""
        with self.lock:
            seconds = self.received_seconds
            self.received_seconds = 0
            return seconds

    def take_commit_seconds(self) -> int:
        """Seconds on the Commit dashboard since the last call (the agent calls this once a minute)."""
        with self.lock:
            seconds = self.commit_seconds
            self.commit_seconds = 0
            return seconds

    def current_domain(self, max_age_seconds: float) -> str | None:
        """The domain of the latest heartbeat if it is recent enough (for "don't interrupt calls")."""
        with self.lock:
            if self.last_domain is None or self.clock() - self.last_domain_time > max_age_seconds:
                return None
            return self.last_domain
