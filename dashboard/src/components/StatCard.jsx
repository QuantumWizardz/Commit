// dashboard/src/components/StatCard.jsx — one number with a small grey label and an optional trend.
//
// trend: { change, unit } compares with yesterday, e.g. change = +12 -> "↗ 12 min vs yesterday".

function trendText(change, formatChange) {
  if (change === null || change === undefined) return null;
  if (change === 0) return "Same as yesterday";
  const arrow = change > 0 ? "↗" : "↘";
  return `${arrow} ${formatChange(Math.abs(change))} vs yesterday`;
}

export default function StatCard({ label, value, change, formatChange = String, highlight = false }) {
  const trend = trendText(change, formatChange);
  return (
    <div className={`card${highlight ? " highlight" : ""}`}>
      <div className="label">{label}</div>
      <div className="big">{value}</div>
      {trend && <div className="trend">{trend}</div>}
    </div>
  );
}
