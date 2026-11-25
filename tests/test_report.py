"""
tests/test_report.py — weekly report numbers, highlights, PDF, and the automatic Monday report.
"""

import os
from datetime import date, datetime

from server import report

WEEK_START = date(2026, 11, 16)          # a Monday


def at(day_offset: int, hour: int, minute: int = 0) -> int:
    """Unix time of a local moment in the test week."""
    return int(datetime(2026, 11, 16 + day_offset, hour, minute).timestamp())


def fill_week(storage):
    """A small, hand-made week of data."""
    # Tuesday 14:00–14:09 interrupted, Wednesday 10:00–10:19 neutral, plus idle and passive minutes.
    for minute in range(10):
        storage.save_minute({"ts": at(1, 14, minute), "mode": "active", "condition": "interruptions", "load_score": 80.0})
    for minute in range(20):
        storage.save_minute({"ts": at(2, 10, minute), "mode": "active", "condition": "neutral", "load_score": 30.0})
    storage.save_minute({"ts": at(2, 11, 0), "mode": "passive"})
    storage.save_minute({"ts": at(2, 12, 0), "mode": "idle"})
    # Apps: 30 min Code, 10 min Chrome (split into websites below).
    storage.save_app_time(at(1, 14), {"Code": 1800, "Google Chrome": 600}, {"Code": "Work", "Google Chrome": "Other"})
    storage.save_web_time(at(1, 14), "youtube.com", "Learning", 300)
    storage.save_web_time(at(1, 14), None, "Private", 120)
    storage.save_web_time(at(1, 14), None, "Miscellaneous", 180)
    # Alerts: one DND accepted and rated up, one break dismissed and rated down.
    dnd = storage.add_alert(at(1, 14, 9), "dnd", "reason")
    storage.set_alert_action(dnd, "yes")
    storage.set_alert_feedback(dnd, "up")
    pause = storage.add_alert(at(2, 10, 19), "break", "reason")
    storage.set_alert_action(pause, "dismiss")
    storage.set_alert_feedback(pause, "down")
    # Outside the week: must be ignored.
    storage.save_minute({"ts": at(7, 10), "mode": "active", "condition": "time_pressure", "load_score": 99.0})


def test_week_report_numbers(storage, config):
    fill_week(storage)
    week = report.build_week_report(storage, config, WEEK_START)

    assert week["start"] == "2026-11-16" and week["end"] == "2026-11-22"
    assert week["totals"]["screen_minutes"] == 31          # 30 active + 1 passive (idle not counted)
    assert week["totals"]["active_minutes"] == 30
    assert week["totals"]["condition_minutes"] == {"neutral": 20, "interruptions": 10, "time_pressure": 0}
    tuesday, wednesday = week["daily"][1], week["daily"][2]
    assert tuesday["average_load"] == 80.0 and wednesday["average_load"] == 30.0
    assert week["hourly"][14]["condition_minutes"]["interruptions"] == 10

    # Browser time is replaced by its website categories.
    categories = {item["name"]: item["minutes"] for item in week["categories"]}
    assert categories == {"Work": 30, "Learning": 5, "Miscellaneous": 3, "Private": 2}
    assert week["top_apps"][0] == {"name": "Code", "minutes": 30}
    assert week["top_domains"] == [{"name": "youtube.com", "minutes": 5, "category": "Learning"}]
    assert week["private_minutes"] == 2

    assert week["alerts"]["dnd"] == {"shown": 1, "accepted": 1, "rated_up": 1, "rated": 1}
    assert week["alerts"]["break"] == {"shown": 1, "accepted": 0, "rated_up": 0, "rated": 1}
    assert week["highlights"] == [
        "Most interruptions happened on Tuesday afternoon.",
        "Your calmest day was Wednesday (20 min of focused work).",
    ]


def test_empty_week_and_pdf(storage, config):
    week = report.build_week_report(storage, config, WEEK_START)
    assert week["totals"]["average_load"] is None and week["highlights"] == []
    assert report.render_pdf(week).startswith(b"%PDF")


def test_pdf_has_no_titles(storage, config):
    fill_week(storage)
    pdf = report.render_pdf(report.build_week_report(storage, config, WEEK_START))
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


def test_format_minutes():
    assert report.format_minutes(40) == "40 min"
    assert report.format_minutes(125) == "2 h 5 min"


def test_weekly_report_generated_once_on_monday(storage, config, tmp_path):
    fill_week(storage)
    monday = date(2026, 11, 23)
    path = report.ensure_weekly_report(storage, config, monday, tmp_path)
    assert path is not None and path.name == "commit-week-2026-11-16.pdf"
    assert report.ensure_weekly_report(storage, config, monday, tmp_path) is None      # only once
    assert report.ensure_weekly_report(storage, config, date(2026, 11, 24), tmp_path) is None   # not on Tuesday


def test_old_report_files_are_deleted(storage, config, tmp_path):
    old = tmp_path / "commit-week-2026-01-05.pdf"
    old.write_bytes(b"%PDF")
    now = datetime(2026, 11, 24).timestamp()
    os.utime(old, (now - 40 * 86400, now - 40 * 86400))
    report.ensure_weekly_report(storage, config, date(2026, 11, 24), tmp_path, now=now)
    assert not old.exists()
