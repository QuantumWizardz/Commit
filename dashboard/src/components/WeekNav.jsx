// dashboard/src/components/WeekNav.jsx — choose which 7 days to show (previous / last 7 days / next).
import { addDays, DAYS_IN_WEEK, lastSevenDaysStart } from "../format.js";

/** "2026-11-16" -> "16 Nov" */
function shortDate(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString([], { day: "numeric", month: "short" });
}

export default function WeekNav({ start, onChange }) {
  const latest = lastSevenDaysStart();
  const end = addDays(start, DAYS_IN_WEEK - 1);
  return (
    <div className="row">
      <button className="button small secondary" onClick={() => onChange(addDays(start, -DAYS_IN_WEEK))}>← Previous</button>
      <strong>{shortDate(start)} – {shortDate(end)}</strong>
      <button className="button small secondary" disabled={start >= latest} onClick={() => onChange(addDays(start, DAYS_IN_WEEK))}>Next →</button>
      {start !== latest && <button className="button small secondary" onClick={() => onChange(latest)}>Last 7 days</button>}
    </div>
  );
}
