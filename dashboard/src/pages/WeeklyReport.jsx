// dashboard/src/pages/WeeklyReport.jsx — the weekly report as cards, plus PDF download (README 9.4 and 10.2).
// Domains and categories only, never titles.
import { useState } from "react";
import { downloadWeeklyPdf } from "../api.js";
import { BarList, DayColumns } from "../components/Charts.jsx";
import StatCard from "../components/StatCard.jsx";
import CategoryBreakdown from "../components/CategoryBreakdown.jsx";
import { useLoad } from "../components/useLoad.js";
import WeekNav from "../components/WeekNav.jsx";
import { CONDITION_LABELS, formatMinutes, lastSevenDaysStart } from "../format.js";

/** Day-by-day table: screen time, active time, conditions, average load. */
function DayTable({ daily }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr><th>Day</th><th>Screen</th><th>Active</th><th>Neutral</th><th>Interrupted</th><th>Pressured</th><th>Avg load</th></tr>
        </thead>
        <tbody>
          {daily.map((day) => (
            <tr key={day.date}>
              <td>{day.weekday}</td>
              <td>{formatMinutes(day.screen_minutes)}</td>
              <td>{formatMinutes(day.active_minutes)}</td>
              <td>{formatMinutes(day.condition_minutes.neutral)}</td>
              <td>{formatMinutes(day.condition_minutes.interruptions)}</td>
              <td>{formatMinutes(day.condition_minutes.time_pressure)}</td>
              <td>{day.average_load === null ? "–" : Math.round(day.average_load)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Suggestions shown / accepted / rated helpful, per kind. */
function AlertSummary({ alerts }) {
  const rows = [["Do Not Disturb", alerts.dnd], ["Break", alerts.break]];
  return (
    <table>
      <thead><tr><th>Suggestion</th><th>Shown</th><th>Accepted</th><th>Rated 👍</th></tr></thead>
      <tbody>
        {rows.map(([label, counts]) => (
          <tr key={label}><td>{label}</td><td>{counts.shown}</td><td>{counts.accepted}</td><td>{counts.rated_up} of {counts.rated}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export default function WeeklyReport() {
  const [start, setStart] = useState(lastSevenDaysStart());
  const [downloadError, setDownloadError] = useState(null);
  const { data, error, reload } = useLoad(`/api/week?start=${start}`);
  if (error) return <div className="banner">{error}</div>;
  if (!data) return <p className="empty">Loading…</p>;

  const totals = data.totals;
  const shown = data.alerts.dnd.shown + data.alerts.break.shown;
  const loadDays = data.daily.map((day) => ({ label: day.weekday.slice(0, 3), value: day.average_load || 0 }));

  async function download() {
    try {
      await downloadWeeklyPdf(start);
      setDownloadError(null);
    } catch (problem) {
      setDownloadError(problem.message);
    }
  }

  return (
    <>
      <div className="row spread">
        <WeekNav start={start} onChange={setStart} />
        <button className="button" onClick={download}>Download PDF</button>
      </div>
      {downloadError && <div className="banner">{downloadError}</div>}

      <section className="stats">
        <StatCard label="Screen time" value={formatMinutes(totals.screen_minutes)} />
        <StatCard label="Active time" value={formatMinutes(totals.active_minutes)} />
        <StatCard label="Average load" value={totals.average_load === null ? "–" : Math.round(totals.average_load)} highlight />
        <StatCard label="Suggestions" value={shown} />
      </section>

      {data.highlights.length > 0 && (
        <div className="card">
          <h2>Highlights</h2>
          {data.highlights.map((text) => <p key={text}>{text}</p>)}
        </div>
      )}

      <div className="grid three">
        {Object.entries(CONDITION_LABELS).map(([key, label]) => (
          <div className="card" key={key}>
            <div className="row"><span className={`dot ${key}`} /><span className="label">{label}</span></div>
            <div className="big">{formatMinutes(totals.condition_minutes[key])}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <h2>Day by day</h2>
        <DayTable daily={data.daily} />
      </div>

      <div className="grid two">
        <div className="card">
          <h2>Time by category</h2>
          <CategoryBreakdown items={data.categories} itemsByCategory={data.category_items}
                             categories={data.categories_available} onChanged={reload} />
          <p className="label" style={{ marginTop: 10 }}>Click a category to see and change what is in it.</p>
        </div>
        <div className="card">
          <h2>Average load by day</h2>
          <DayColumns days={loadDays} format={(score) => String(Math.round(score))} maximum={100} />
          <p className="label">Load score from 0 to 100.</p>
        </div>
      </div>

      <div className="grid three">
        <div className="card"><h2>Top apps</h2><BarList items={data.top_apps} /></div>
        <div className="card">
          <h2>Top websites</h2>
          <BarList items={data.top_domains} emptyText="No website time." />
          {data.private_minutes > 0 && <p className="label" style={{ marginTop: 10 }}>Private: {formatMinutes(data.private_minutes)}</p>}
        </div>
        <div className="card"><h2>Suggestions</h2><AlertSummary alerts={data.alerts} /></div>
      </div>
    </>
  );
}
