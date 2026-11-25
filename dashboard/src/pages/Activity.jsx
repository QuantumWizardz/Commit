// dashboard/src/pages/Activity.jsx — where time went: categories, apps, websites, day by day (README 10.2).
// Also lets the user change a website's category; the change becomes a rule for the future.
import { useState } from "react";
import { api } from "../api.js";
import { BarList, DayColumns } from "../components/Charts.jsx";
import { useLoad } from "../components/useLoad.js";
import WeekNav from "../components/WeekNav.jsx";
import { formatMinutes, lastSevenDaysStart } from "../format.js";

/** One website row with a category picker. */
function DomainRow({ domain, categories, onChanged }) {
  const [message, setMessage] = useState("");

  async function change(event) {
    try {
      await api("PUT", "/api/domain-rules", { domain: domain.name, category: event.target.value });
      setMessage("Saved — used from now on.");
      onChanged();
    } catch (problem) {
      setMessage(problem.message);
    }
  }

  return (
    <tr>
      <td>{domain.name}</td>
      <td>{formatMinutes(domain.minutes)}</td>
      <td>
        <select value={domain.category} onChange={change} aria-label={`Category for ${domain.name}`}>
          {categories.map((category) => <option key={category}>{category}</option>)}
        </select>
        {message && <div className="label">{message}</div>}
      </td>
    </tr>
  );
}

export default function Activity() {
  const [start, setStart] = useState(lastSevenDaysStart());
  const { data, error, reload } = useLoad(`/api/activity?start=${start}`);
  if (error) return <div className="banner">{error}</div>;
  if (!data) return <p className="empty">Loading…</p>;

  const days = data.daily.map((day) => ({ label: day.weekday.slice(0, 3), value: day.active_minutes }));

  return (
    <>
      <WeekNav start={start} onChange={setStart} />

      <div className="grid two">
        <div className="card">
          <h2>Time by category</h2>
          <BarList items={data.categories} />
        </div>
        <div className="card">
          <h2>Active time per day</h2>
          <DayColumns days={days} />
        </div>
      </div>

      <div className="grid two">
        <div className="card">
          <h2>Top apps</h2>
          <BarList items={data.top_apps} />
        </div>
        <div className="card">
          <h2>Top websites</h2>
          {data.top_domains.length === 0 ? (
            <p className="empty">No website time yet. Is the Chrome extension paired?</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Website</th><th>Time</th><th>Category (change to correct it)</th></tr></thead>
                <tbody>
                  {data.top_domains.map((domain) => (
                    <DomainRow key={domain.name} domain={domain} categories={data.categories_available} onChanged={reload} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.private_minutes > 0 && <p className="label" style={{ marginTop: 10 }}>Private websites: {formatMinutes(data.private_minutes)} (no names shown)</p>}
        </div>
      </div>
    </>
  );
}
