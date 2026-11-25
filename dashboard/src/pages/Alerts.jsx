// dashboard/src/pages/Alerts.jsx — every DND and break suggestion: when, why, what the user did, feedback.
import AlertList from "../components/AlertList.jsx";
import StatCard from "../components/StatCard.jsx";
import { useLoad } from "../components/useLoad.js";

export default function Alerts() {
  const { data, error } = useLoad("/api/alerts");
  if (error) return <div className="banner">{error}</div>;
  if (!data) return <p className="empty">Loading…</p>;

  const alerts = data.alerts;
  const rated = alerts.filter((alert) => alert.feedback !== null);
  const helpful = rated.filter((alert) => alert.feedback === "up");
  const accepted = alerts.filter((alert) => alert.action === "yes" || alert.action === "auto");

  return (
    <>
      <section className="stats">
        <StatCard label="Suggestions shown" value={alerts.length} />
        <StatCard label="Accepted" value={accepted.length} />
        <StatCard label="Rated helpful" value={rated.length ? `${helpful.length} of ${rated.length}` : "–"} highlight />
      </section>
      <div className="card">
        <h2>All suggestions</h2>
        <p className="label">Your 👍/👎 answers help Commit learn when a suggestion is useful.</p>
        <AlertList alerts={alerts} emptyText="No suggestions yet." />
      </div>
    </>
  );
}
