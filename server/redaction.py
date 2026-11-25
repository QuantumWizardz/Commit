"""
server/redaction.py — cleans a page/video title before it is given to any language model
(README module M2.3 step 4, privacy rule P7).

Removes:
  * e-mail addresses
  * links (http://…, https://…, www.…)
  * numbers with 4 or more digits (phone numbers, order numbers, account numbers, years too)
and then shortens the title to at most 120 characters (config categoriser.title_max_chars).
"""

from __future__ import annotations

import re

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
LINK_PATTERN = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
LONG_NUMBER_PATTERN = re.compile(r"\d[\d\s\-.]{2,}\d")  # 4+ digits, possibly split by spaces/dashes/dots
MIN_DIGITS_TO_REMOVE = 4
MULTIPLE_SPACES = re.compile(r"\s{2,}")


def remove_long_numbers(text: str) -> str:
    """
    Remove numbers that contain 4 or more digits (also when written as "98 76 54 32" or "1234-5678").

    In:  text.  Out: text with those numbers removed. Short numbers like "Lecture 5" stay.
    """
    def replace(match: re.Match) -> str:
        digits = sum(character.isdigit() for character in match.group(0))
        return "" if digits >= MIN_DIGITS_TO_REMOVE else match.group(0)

    text = LONG_NUMBER_PATTERN.sub(replace, text)
    return re.sub(r"\d{4,}", "", text)


def redact_title(title: str, max_chars: int) -> str:
    """
    Make a title safe to send to a language model.

    In:  the raw title, the maximum length.
    Out: the title without e-mails, links and long numbers, tidied and cut to max_chars.
    """
    text = EMAIL_PATTERN.sub("", title)
    text = LINK_PATTERN.sub("", text)
    text = remove_long_numbers(text)
    text = MULTIPLE_SPACES.sub(" ", text).strip()
    return text[:max_chars].strip()
