"""tests/test_redaction.py — titles are cleaned before any language model sees them (P7)."""

from server.redaction import redact_title

MAX = 120


def test_removes_emails():
    assert redact_title("Inbox (3) - priya.sharma+work@gmail.com - Gmail", MAX) == "Inbox (3) - - Gmail"


def test_removes_links():
    assert redact_title("Read https://example.com/a?b=1 and www.site.org/page now", MAX) == "Read and now"


def test_removes_long_numbers_keeps_short_ones():
    assert redact_title("Order 123456 for Lecture 5", MAX) == "Order for Lecture 5"
    assert redact_title("Call +91 98765 43210 today", MAX) == "Call + today"
    assert redact_title("Card 4111-1111-1111-1111", MAX) == "Card"
    assert redact_title("Episode 12 of 300", MAX) == "Episode 12 of 300"


def test_cuts_to_max_length():
    assert len(redact_title("word " * 100, MAX)) <= MAX


def test_empty_after_redaction():
    assert redact_title("someone@example.com", MAX) == ""
