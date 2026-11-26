"""
server/report.py — the weekly report (README module M2.4): data + PDF.

Only domains and categories are used — never titles (P3). Private time is one "Private" total.

Contents:
  1. screen time and active time per day      (screen time = active + passive minutes)
  2. time by category                         (apps; for the browser, its website categories)
  3. top apps and top domains
  4. condition summary by day and by hour of day
  5. average load score by day
  6. alerts: how many, how many accepted, how many rated 👍
  7. one or two plain-language highlights

Generated every Monday for the previous 7 days (ensure_weekly_report, called by the agent
once a day) and on demand (API: /api/week and /api/report/pdf).
"""

from __future__ import annotations

import io
import logging
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import platformdirs
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

log = logging.getLogger(__name__)

DAYS_IN_WEEK = 7
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
CONDITIONS = ["neutral", "interruptions", "time_pressure"]
CONDITION_NAMES = {"neutral": "Neutral", "interruptions": "Interrupted", "time_pressure": "Pressured"}
ACCEPTED_ACTIONS = ("yes", "auto")
SCREEN_MODES = ("active", "passive")

# Design reference (README 10.3): black, greys, one yellow accent.
BLACK = colors.HexColor("#111111")
GREY = colors.HexColor("#6B6B6B")
LIGHT = colors.HexColor("#E8E6E1")
YELLOW = colors.HexColor("#F3F06A")


# ---------------------------------------------------------------- helpers

def format_minutes(minutes: float) -> str:
    """125 -> "2 h 5 min"; 40 -> "40 min"."""
    minutes = int(round(minutes))
    hours, rest = divmod(minutes, MINUTES_PER_HOUR)
    return f"{hours} h {rest} min" if hours else f"{rest} min"


def week_bounds(start: date) -> tuple[int, int]:
    """Unix times of local midnight at the start and 7 days later."""
    begin = datetime.combine(start, datetime.min.time())
    return int(begin.timestamp()), int((begin + timedelta(days=DAYS_IN_WEEK)).timestamp())


def part_of_day(hour: int, config) -> str:
    """"morning", "afternoon" or "evening" for an hour of the day."""
    if hour < config.get("report.afternoon_starts_hour"):
        return "morning"
    if hour < config.get("report.evening_starts_hour"):
        return "afternoon"
    return "evening"


# ---------------------------------------------------------------- report data

def minutes_summary(storage, begin: int, end: int, days: list[date]) -> dict:
    """Items 1, 4 and 5: screen/active time, conditions and load per day; conditions per hour."""
    per_day = {day: {"screen_minutes": 0, "active_minutes": 0, "conditions": Counter(), "load_scores": []} for day in days}
    per_hour = {hour: Counter() for hour in range(24)}
    rows = storage.execute("SELECT ts, mode, condition, load_score FROM minutes WHERE ts >= ? AND ts < ?", (begin, end))
    for ts, mode, condition, load_score in rows:
        moment = datetime.fromtimestamp(ts)
        day = per_day[moment.date()]
        if mode in SCREEN_MODES:
            day["screen_minutes"] += 1
        if mode == "active":
            day["active_minutes"] += 1
        if condition is not None:
            day["conditions"][condition] += 1
            per_hour[moment.hour][condition] += 1
        if load_score is not None:
            day["load_scores"].append(load_score)

    daily = []
    for day in days:
        values = per_day[day]
        scores = values["load_scores"]
        daily.append({
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "screen_minutes": values["screen_minutes"],
            "active_minutes": values["active_minutes"],
            "condition_minutes": {c: values["conditions"][c] for c in CONDITIONS},
            "average_load": round(sum(scores) / len(scores), 1) if scores else None,
        })
    hourly = [{"hour": hour, "condition_minutes": {c: per_hour[hour][c] for c in CONDITIONS}} for hour in range(24)]
    return {"daily": daily, "hourly": hourly}


def time_summary(storage, config, begin: int, end: int, top_items: int | None = None) -> dict:
    """
    Items 2 and 3: time by category, top apps, top domains (private time as one total).

    In:  storage, config, the time range, how many top apps/domains to list (None = report.top_items).
    Out: dict; each top domain also has its main category (for "edit a domain's category").
         "category_items" = {category: [{"kind": "app"|"website"|"unnamed", "name", "minutes"}]},
         what makes up each category (the dashboard lets the user re-categorise from there).
    """
    browser_apps = config.get("categoriser.browser_apps")
    # Never counted, also in rows saved before these lists existed: Commit's own dialogs and the lock screen.
    skipped_apps = set(config.get("activity.commit_apps")) | set(config.get("activity.ignored_apps"))
    top_items = top_items or config.get("report.top_items")
    by_category: Counter = Counter()
    by_app: Counter = Counter()
    by_domain: Counter = Counter()
    domain_categories: dict[str, Counter] = defaultdict(Counter)
    parts: dict[str, Counter] = defaultdict(Counter)     # category -> {(kind, name): seconds}

    for app_name, category, seconds in storage.execute(
        "SELECT app_name, category, seconds FROM app_time WHERE ts >= ? AND ts < ?", (begin, end)
    ):
        if app_name in skipped_apps:
            continue
        by_app[app_name] += seconds
        if app_name not in browser_apps:      # browser time is split by website below
            by_category[category or "Other"] += seconds
            parts[category or "Other"][("app", app_name)] += seconds

    private_seconds = 0
    for domain, category, seconds in storage.execute(
        "SELECT domain, category, seconds FROM web_time WHERE ts >= ? AND ts < ?", (begin, end)
    ):
        by_category[category] += seconds
        if domain is not None:
            by_domain[domain] += seconds
            domain_categories[domain][category] += seconds
            parts[category][("website", domain)] += seconds
        else:
            parts[category][("unnamed", category)] += seconds   # private / no-detail time: never a name
            if category == "Private":
                private_seconds += seconds

    def as_minutes(counter: Counter, limit: int | None = None) -> list[dict]:
        return [{"name": name, "minutes": round(seconds / SECONDS_PER_MINUTE)} for name, seconds in counter.most_common(limit)]

    top_domains = as_minutes(by_domain, top_items)
    for item in top_domains:
        item["category"] = domain_categories[item["name"]].most_common(1)[0][0]

    category_items = {
        category: [{"kind": kind, "name": name, "minutes": round(seconds / SECONDS_PER_MINUTE)}
                   for (kind, name), seconds in counter.most_common()]
        for category, counter in parts.items()
    }

    return {
        "categories": as_minutes(by_category),
        "category_items": category_items,
        "top_apps": as_minutes(by_app, top_items),
        "top_domains": top_domains,
        "private_minutes": round(private_seconds / SECONDS_PER_MINUTE),
    }


def alert_summary(storage, begin: int, end: int) -> dict:
    """Item 6: suggestions shown, accepted, and rated 👍, per kind."""
    summary = {kind: {"shown": 0, "accepted": 0, "rated_up": 0, "rated": 0} for kind in ("dnd", "break")}
    for kind, action, feedback in storage.execute(
        "SELECT kind, action, feedback FROM alerts WHERE ts >= ? AND ts < ?", (begin, end)
    ):
        counts = summary[kind]
        counts["shown"] += 1
        if action in ACCEPTED_ACTIONS:
            counts["accepted"] += 1
        if feedback is not None:
            counts["rated"] += 1
        if feedback == "up":
            counts["rated_up"] += 1
    return summary


def highlights(storage, config, begin: int, end: int, daily: list[dict], categories: list[dict]) -> list[str]:
    """Item 7: up to two plain-language sentences."""
    sentences = []

    # When did most interruptions happen?
    interrupted = Counter()
    for (ts,) in storage.execute(
        "SELECT ts FROM minutes WHERE ts >= ? AND ts < ? AND condition = 'interruptions'", (begin, end)
    ):
        moment = datetime.fromtimestamp(ts)
        interrupted[(moment.strftime("%A"), part_of_day(moment.hour, config))] += 1
    if interrupted:
        (weekday, part), _ = interrupted.most_common(1)[0]
        sentences.append(f"Most interruptions happened on {weekday} {part}.")

    # Calmest day, else where the time went.
    calm_days = [d for d in daily if d["condition_minutes"]["neutral"] > 0]
    if calm_days:
        calmest = max(calm_days, key=lambda d: d["condition_minutes"]["neutral"])
        sentences.append(f"Your calmest day was {calmest['weekday']} ({format_minutes(calmest['condition_minutes']['neutral'])} of focused work).")
    elif categories:
        sentences.append(f"Most of your time went to {categories[0]['name']} ({format_minutes(categories[0]['minutes'])}).")
    return sentences[:2]


def build_week_report(storage, config, start: date) -> dict:
    """
    All report data for the 7 days starting at `start` (local time).

    Out: a JSON-friendly dict (used by the API, the dashboard and the PDF).
    """
    begin, end = week_bounds(start)
    days = [start + timedelta(days=offset) for offset in range(DAYS_IN_WEEK)]
    minutes = minutes_summary(storage, begin, end, days)
    times = time_summary(storage, config, begin, end)
    report = {
        "start": start.isoformat(),
        "end": (start + timedelta(days=DAYS_IN_WEEK - 1)).isoformat(),
        **minutes,
        **times,
        "alerts": alert_summary(storage, begin, end),
    }
    report["totals"] = {
        "screen_minutes": sum(d["screen_minutes"] for d in report["daily"]),
        "active_minutes": sum(d["active_minutes"] for d in report["daily"]),
        "condition_minutes": {c: sum(d["condition_minutes"][c] for d in report["daily"]) for c in CONDITIONS},
    }
    scores = [d["average_load"] for d in report["daily"] if d["average_load"] is not None]
    report["totals"]["average_load"] = round(sum(scores) / len(scores), 1) if scores else None
    report["highlights"] = highlights(storage, config, begin, end, report["daily"], report["categories"])
    return report


# ---------------------------------------------------------------- today (dashboard Home screen)

def day_stats(storage, begin: int, end: int) -> dict:
    """Active, neutral, interrupted and pressured minutes, and breaks taken, in a time range."""
    stats = {"active_minutes": 0, "neutral_minutes": 0, "interrupted_minutes": 0, "pressured_minutes": 0, "breaks_taken": 0}
    names = {"neutral": "neutral_minutes", "interruptions": "interrupted_minutes", "time_pressure": "pressured_minutes"}
    for mode, condition in storage.execute("SELECT mode, condition FROM minutes WHERE ts >= ? AND ts < ?", (begin, end)):
        if mode == "active":
            stats["active_minutes"] += 1
        if condition in names:
            stats[names[condition]] += 1
    (breaks,) = storage.execute(
        "SELECT COUNT(*) FROM alerts WHERE kind = 'break' AND action = 'yes' AND ts >= ? AND ts < ?", (begin, end)
    )[0]
    stats["breaks_taken"] = breaks
    return stats


def condition_timeline(storage, begin: int, end: int) -> list[dict]:
    """
    Today's condition bands: consecutive active minutes with the same condition merged into one band.

    Out: [{"start": unix, "end": unix, "condition": "neutral"}, ...], oldest first.
    """
    bands: list[dict] = []
    rows = storage.execute(
        "SELECT ts, condition FROM minutes WHERE ts >= ? AND ts < ? AND condition IS NOT NULL ORDER BY ts", (begin, end)
    )
    for ts, condition in rows:
        last = bands[-1] if bands else None
        if last is not None and last["condition"] == condition and ts == last["end"]:
            last["end"] = ts + SECONDS_PER_MINUTE
        else:
            bands.append({"start": ts, "end": ts + SECONDS_PER_MINUTE, "condition": condition})
    return bands


def recent_alerts(storage, limit: int) -> list[dict]:
    """The latest alerts, newest first."""
    rows = storage.execute("SELECT id, ts, kind, reason, action, feedback FROM alerts ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
    return [{"id": i, "ts": ts, "kind": kind, "reason": reason, "action": action, "feedback": feedback}
            for i, ts, kind, reason, action, feedback in rows]


def build_today(storage, now: float, current_load: float | None, alert_count: int) -> dict:
    """
    Data for the dashboard Home screen.

    In:  storage, current time, the agent's current load score (None if unknown), how many recent alerts.
    Out: {"date", "today": stats, "yesterday": stats, "load_score", "day_start", "timeline", "recent_alerts"}.
    """
    today = datetime.fromtimestamp(now).date()
    today_begin, _ = week_bounds(today)
    yesterday_begin, _ = week_bounds(today - timedelta(days=1))
    load = current_load
    if load is None:
        latest = storage.execute(
            "SELECT load_score FROM minutes WHERE ts >= ? AND load_score IS NOT NULL ORDER BY ts DESC LIMIT 1", (today_begin,)
        )
        load = latest[0][0] if latest else None
    return {
        "date": today.isoformat(),
        "day_start": today_begin,
        "today": day_stats(storage, today_begin, int(now) + SECONDS_PER_MINUTE),
        "yesterday": day_stats(storage, yesterday_begin, today_begin),
        "load_score": load,
        "timeline": condition_timeline(storage, today_begin, int(now) + SECONDS_PER_MINUTE),
        "recent_alerts": recent_alerts(storage, alert_count),
    }


# ---------------------------------------------------------------- PDF

def styled_table(rows: list[list], column_widths: list[float], highlight_column: int | None = None) -> Table:
    """A flat table: bold header, thin grey lines, optional yellow column (the one key number)."""
    table = Table(rows, colWidths=column_widths)
    table.hAlign = "LEFT"   # line up with the headings
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), GREY),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LIGHT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]
    if highlight_column is not None:
        style.append(("BACKGROUND", (highlight_column, 0), (highlight_column, -1), YELLOW))
    table.setStyle(TableStyle(style))
    return table


def category_chart(categories: list[dict]) -> Drawing:
    """Flat horizontal bars of minutes per category."""
    names = [item["name"] for item in categories][::-1]
    values = [item["minutes"] for item in categories][::-1]
    height = max(len(names), 1) * 7 * mm + 10 * mm
    drawing = Drawing(170 * mm, height)
    chart = HorizontalBarChart()
    chart.x, chart.y = 30 * mm, 5 * mm
    chart.width, chart.height = 130 * mm, height - 10 * mm
    chart.data = [values or [0]]
    chart.categoryAxis.categoryNames = names or ["No data"]
    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = BLACK
    chart.bars[0].strokeColor = None
    drawing.add(chart)
    return drawing


def render_pdf(report: dict) -> bytes:
    """
    Turn the report data into a simple PDF in the dashboard style.

    Out: the PDF file contents.
    """
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                                 title=f"Commit weekly report {report['start']}")
    title_style = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=BLACK)
    heading_style = ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=BLACK, spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=BLACK)
    grey_style = ParagraphStyle("grey", parent=body_style, textColor=GREY)

    totals = report["totals"]
    load_text = f"{totals['average_load']:.0f}" if totals["average_load"] is not None else "–"
    shown = report["alerts"]["dnd"]["shown"] + report["alerts"]["break"]["shown"]
    story = [
        Paragraph("Commit — Weekly report", title_style),
        Paragraph(f"{report['start']} to {report['end']} · domains and categories only, no titles", grey_style),
        Spacer(1, 6 * mm),
        styled_table(
            [["Screen time", "Active time", "Average load", "Suggestions"],
             [format_minutes(totals["screen_minutes"]), format_minutes(totals["active_minutes"]), load_text, str(shown)]],
            [42 * mm] * 4, highlight_column=2,
        ),
    ]
    if report["highlights"]:
        story += [Paragraph("Highlights", heading_style)] + [Paragraph("• " + text, body_style) for text in report["highlights"]]

    story += [KeepTogether([Paragraph("Time by category (minutes)", heading_style), category_chart(report["categories"])])]

    day_rows = [["Day", "Screen", "Active", "Neutral", "Interrupted", "Pressured", "Avg load"]]
    for day in report["daily"]:
        minutes = day["condition_minutes"]
        day_rows.append([day["weekday"][:3] + " " + day["date"][5:], format_minutes(day["screen_minutes"]), format_minutes(day["active_minutes"]),
                         format_minutes(minutes["neutral"]), format_minutes(minutes["interruptions"]), format_minutes(minutes["time_pressure"]),
                         f"{day['average_load']:.0f}" if day["average_load"] is not None else "–"])
    story += [Paragraph("Day by day", heading_style), styled_table(day_rows, [26 * mm, 23 * mm, 23 * mm, 23 * mm, 25 * mm, 23 * mm, 20 * mm])]

    app_rows = [["Top apps", "Time"]] + [[item["name"], format_minutes(item["minutes"])] for item in report["top_apps"]]
    domain_rows = [["Top domains", "Time"]] + [[item["name"], format_minutes(item["minutes"])] for item in report["top_domains"]]
    if report["private_minutes"]:
        domain_rows.append(["Private", format_minutes(report["private_minutes"])])
    side_by_side = Table([[styled_table(app_rows, [52 * mm, 25 * mm]), styled_table(domain_rows, [52 * mm, 25 * mm])]])
    side_by_side.hAlign = "LEFT"
    story += [Spacer(1, 4 * mm), side_by_side]

    alert_rows = [["Suggestion", "Shown", "Accepted", "Rated helpful / rated"]]   # PDF fonts cannot draw emoji
    for kind, label in (("dnd", "Do Not Disturb"), ("break", "Break")):
        counts = report["alerts"][kind]
        alert_rows.append([label, str(counts["shown"]), str(counts["accepted"]), f"{counts['rated_up']} / {counts['rated']}"])
    # KeepTogether: a heading is never left alone at the bottom of a page.
    story += [KeepTogether([Paragraph("Suggestions", heading_style), styled_table(alert_rows, [45 * mm, 25 * mm, 25 * mm, 35 * mm])])]

    document.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------- automatic weekly PDF

def reports_folder() -> Path:
    """Where automatic weekly PDFs are saved (inside the app-data folder)."""
    return Path(platformdirs.user_data_dir("Commit")) / "reports"


def ensure_weekly_report(storage, config, today: date, folder: Path | None = None, now: float | None = None) -> Path | None:
    """
    On the report weekday, save last week's PDF once. Also delete PDFs older than the retention period (P11).

    In:  storage, config, today's date, (for tests) the folder and current time.
    Out: the path of a newly written PDF, or None.
    """
    folder = reports_folder() if folder is None else folder
    folder.mkdir(parents=True, exist_ok=True)
    now = time.time() if now is None else now
    retention_seconds = config.get("data.retention_days") * 24 * 60 * 60
    for old_file in folder.glob("commit-week-*.pdf"):
        if now - old_file.stat().st_mtime > retention_seconds:
            old_file.unlink()

    if today.weekday() != config.get("report.weekday"):
        return None
    start = today - timedelta(days=DAYS_IN_WEEK)
    path = folder / f"commit-week-{start.isoformat()}.pdf"
    if path.exists():
        return None
    path.write_bytes(render_pdf(build_week_report(storage, config, start)))
    log.info("Weekly report saved.")
    return path
