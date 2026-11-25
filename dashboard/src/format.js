// dashboard/src/format.js — small helpers to turn numbers into friendly text.

export const MINUTES_PER_HOUR = 60;
export const DAYS_IN_WEEK = 7;
const MORNING_ENDS_HOUR = 12;
const AFTERNOON_ENDS_HOUR = 17;

/** 125 -> "2 h 5 min", 40 -> "40 min" */
export function formatMinutes(minutes) {
  const total = Math.round(minutes || 0);
  const hours = Math.floor(total / MINUTES_PER_HOUR);
  const rest = total % MINUTES_PER_HOUR;
  return hours ? `${hours} h ${rest} min` : `${rest} min`;
}

/** unix seconds -> "14:05" */
export function formatTime(unixSeconds) {
  return new Date(unixSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** unix seconds -> "Tue 24 Nov, 14:05" */
export function formatDateTime(unixSeconds) {
  return new Date(unixSeconds * 1000).toLocaleString([], {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

/** "Good morning" / "Good afternoon" / "Good evening" for the current hour. */
export function greeting(date = new Date()) {
  const hour = date.getHours();
  if (hour < MORNING_ENDS_HOUR) return "Good morning";
  if (hour < AFTERNOON_ENDS_HOUR) return "Good afternoon";
  return "Good evening";
}

/** Date -> "2026-11-24" (local date, not UTC). */
export function isoDate(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** "2026-11-24" + days -> "2026-12-01" */
export function addDays(iso, days) {
  const [year, month, day] = iso.split("-").map(Number);
  return isoDate(new Date(year, month - 1, day + days));
}

/** The first day of "the last 7 days including today". */
export function lastSevenDaysStart() {
  return addDays(isoDate(new Date()), -(DAYS_IN_WEEK - 1));
}

export const CONDITION_LABELS = { neutral: "Neutral", interruptions: "Interrupted", time_pressure: "Pressured" };
export const STATE_DOT = { Calm: "neutral", Interrupted: "interruptions", Pressured: "time_pressure" };

const ACTION_LABELS = {
  yes: "Accepted",
  auto: "Turned on automatically",
  not_now: "Not now",
  snooze_30: "Snoozed 30 min",
  snooze_60: "Snoozed 60 min",
  dismiss: "Dismissed",
  no_answer: "No answer",
};

/** Stored alert action -> readable text. */
export function actionLabel(action) {
  return ACTION_LABELS[action] || "—";
}

/** "dnd" -> "Do Not Disturb", "break" -> "Break" */
export function alertKindLabel(kind) {
  return kind === "dnd" ? "Do Not Disturb" : "Break";
}
