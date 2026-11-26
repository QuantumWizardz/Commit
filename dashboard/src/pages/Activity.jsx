// dashboard/src/pages/Activity.jsx — where time went: categories, apps, websites, day by day (README 10.2).
// Also lets the user change an app's or a website's category (used from the next minute, and its
// past time is re-labelled too), here and inside "Time by category".
import { useState } from "react";
import { api } from "../api.js";
import { BarList, DayColumns } from "../components/Charts.jsx";
import CategoryBreakdown from "../components/CategoryBreakdown.jsx";
import { useLoad } from "../components/useLoad.js";
import WeekNav from "../components/WeekNav.jsx";
import { formatMinutes, lastSevenDaysStart } from "../format.js";

/** One website row with a category picker. */
function DomainRow({ domain, categories, onChanged }) {
  const [message, setMessage] = useState("");

  async function change(event) {
    try {
      await api("PUT", "/api/domain-rules", { domain: domain.name, category: event.target.value });
      setMessage("Saved — past and future time.");
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

/** One app row with a category picker. */
function AppRow({ app, categories, onChanged }) {
  const [message, setMessage] = useState("");

  async function change(event) {
    try {
      await api("PUT", "/api/app-rules", { app: app.name, category: event.target.value });
      setMessage("Saved — past and future time.");
      onChanged();
    } catch (problem) {
      setMessage(problem.message);
    }
  }

  return (
    <tr>
      <td>{app.name}</td>
      <td>{formatMinutes(app.minutes)}</td>
      <td>
        <select value={app.category} onChange={change} aria-label={`Category for ${app.name}`}>
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
          <CategoryBreakdown items={data.categories} itemsByCategory={data.category_items}
                             categories={data.categories_available} onChanged={reload} />
          <p className="label" style={{ marginTop: 10 }}>Click a category to see and change what is in it.</p>
        </div>
        <div className="card">
          <h2>Active time per day</h2>
          <DayColumns days={days} />
        </div>
      </div>

      <div className="grid two">
        <div className="card">
          <h2>Top apps</h2>
          {data.top_apps.length === 0 ? (
            <p className="empty">No app time yet.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>App</th><th>Time</th><th>Category (change to correct it)</th></tr></thead>
                <tbody>
                  {data.top_apps.map((app) => (
                    <AppRow key={app.name} app={app} categories={data.categories_available} onChanged={reload} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="label" style={{ marginTop: 10 }}>All apps: Settings → App categories.</p>
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
