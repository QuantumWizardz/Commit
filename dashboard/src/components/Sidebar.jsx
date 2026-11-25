// dashboard/src/components/Sidebar.jsx — logo, navigation, and the current-state card with a pause switch.
import { STATE_DOT } from "../format.js";

export const PAGES = [
  { id: "home", label: "Home" },
  { id: "activity", label: "Activity" },
  { id: "report", label: "Weekly report" },
  { id: "alerts", label: "Alerts" },
  { id: "settings", label: "Settings" },
];

/** Text for the state card, e.g. "Commit is on · Calm". */
function stateText(status) {
  if (!status) return "Connecting…";
  if (status.paused) return "Commit is paused";
  return `Commit is on · ${status.state}`;
}

export default function Sidebar({ page, status, onTogglePause }) {
  return (
    <aside className="sidebar">
      <div className="logo">
        <span className="logo-mark" aria-hidden="true" />
        Commit
      </div>

      <nav className="nav" aria-label="Main">
        {PAGES.map((item) => (
          <a key={item.id} href={`#/${item.id}`} aria-current={page === item.id ? "page" : undefined}>
            {item.label}
          </a>
        ))}
      </nav>

      <div className="state-card">
        <div className="row">
          <span className={`dot ${status && !status.paused ? STATE_DOT[status.state] || "" : ""}`} aria-hidden="true" style={{ position: "relative", top: -1 }} />
          <strong>{stateText(status)}</strong>
        </div>
        {status && (
          <label className="switch" style={{ marginTop: 10 }}>
            <input type="checkbox" checked={!status.paused} onChange={onTogglePause} />
            <span>{status.paused ? "Resume tracking" : "Tracking on"}</span>
          </label>
        )}
      </div>
    </aside>
  );
}
