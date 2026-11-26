// dashboard/src/pages/Developer.jsx — Developer mode: everything Commit is tracking and predicting, live.
//
// Two sources (both refused by the server unless Settings → Developer mode is on):
//   GET /api/dev/events?after=…  the agent's in-memory event log (activity, calibration, predictions,
//                                alert decisions with every rule check, website heartbeats, alerts, system)
//   GET /api/dev/snapshot        live state + the latest rows of every table in the database
// The event log lives only in the Commit app's memory; "Download log" saves a JSON copy on request.
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import StatCard from "../components/StatCard.jsx";
import { useLoad } from "../components/useLoad.js";
import { CONDITION_LABELS, formatDateTime } from "../format.js";

const EVENT_POLL_SECONDS = 2;
const SNAPSHOT_REFRESH_SECONDS = 10;
const MAX_EVENTS_KEPT = 2000;           // in this page; the app itself keeps the last 1000
const KINDS = ["activity", "calibration", "prediction", "decision", "website", "alert", "system"];
const KIND_LABELS = {
  activity: "Activity", calibration: "Calibration", prediction: "Prediction", decision: "Decision",
  website: "Website", alert: "Alert", system: "System",
};
const TABLES = [
  { id: "minutes", label: "Minutes & predictions" },
  { id: "app_time", label: "App time" },
  { id: "web_time", label: "Website time" },
  { id: "alerts", label: "Alerts" },
  { id: "checkins", label: "Check-ins" },
  { id: "rules", label: "Rules & baseline" },
];

/** unix seconds -> "14:05:09" */
function clock(unixSeconds) {
  return new Date(unixSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** seconds -> "4 min 10 s" / "–" */
function duration(seconds) {
  if (!seconds || seconds <= 0) return "–";
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes} min ${Math.round(seconds % 60)} s` : `${Math.round(seconds)} s`;
}

/** {neutral: 0.81, …} -> "Neutral 81% · Interrupted 12% · …" */
function probabilities(probs) {
  if (!probs) return "–";
  return Object.entries(probs)
    .sort((a, b) => b[1] - a[1])
    .map(([name, p]) => `${CONDITION_LABELS[name] || name} ${Math.round(p * 100)}%`)
    .join(" · ");
}

/** Save `data` as a pretty-printed JSON file. */
function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

// ------------------------------------------------------------------ live event log

/** Polls /api/dev/events and keeps the events in order. Out: {events, error, live, setLive, clear}. */
function useEventLog() {
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [live, setLive] = useState(true);
  const lastId = useRef(0);

  const poll = useCallback(async () => {
    try {
      const result = await api("GET", `/api/dev/events?after=${lastId.current}`);
      if (result.last_id < lastId.current) {
        // The Commit app restarted: its ids start again from 1.
        lastId.current = 0;
        setEvents([]);
        return;
      }
      if (result.events.length) {
        lastId.current = result.events[result.events.length - 1].id;
        setEvents((old) => old.concat(result.events).slice(-MAX_EVENTS_KEPT));
      }
      setError(null);
    } catch (problem) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => {
    if (!live) return undefined;
    poll();
    const timer = setInterval(poll, EVENT_POLL_SECONDS * 1000);
    return () => clearInterval(timer);
  }, [live, poll]);

  async function clear() {
    await api("DELETE", "/api/dev/events");
    setEvents([]);
  }

  return { events, error, live, setLive, clear };
}

function EventRow({ event, open, onToggle }) {
  const hasData = event.data && Object.keys(event.data).length > 0;
  return (
    <li className={`log-row${open ? " open" : ""}`}>
      <button className="log-line" onClick={onToggle} disabled={!hasData} aria-expanded={hasData ? open : undefined}>
        <span className="log-time">{clock(event.ts)}</span>
        <span className={`chip kind-${event.kind}`}>{KIND_LABELS[event.kind] || event.kind}</span>
        <span className="log-message">{event.message}</span>
        {hasData && <span className="log-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>}
      </button>
      {open && <pre className="log-data">{JSON.stringify(event.data, null, 2)}</pre>}
    </li>
  );
}

function EventLog({ log, snapshot }) {
  const [kind, setKind] = useState("all");
  const [search, setSearch] = useState("");
  const [openIds, setOpenIds] = useState(() => new Set());

  const counts = Object.fromEntries(KINDS.map((name) => [name, log.events.filter((e) => e.kind === name).length]));
  const needle = search.trim().toLowerCase();
  const shown = log.events
    .filter((e) => kind === "all" || e.kind === kind)
    .filter((e) => !needle || e.message.toLowerCase().includes(needle) || JSON.stringify(e.data).toLowerCase().includes(needle))
    .slice()
    .reverse();

  function toggle(id) {
    setOpenIds((old) => {
      const next = new Set(old);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function download() {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    downloadJson(`commit-devlog-${stamp}.json`, { saved_at: new Date().toISOString(), events: log.events, snapshot });
  }

  return (
    <section className="card">
      <div className="row spread">
        <h2 style={{ margin: 0 }}>Live event log</h2>
        <div className="row">
          <span className="chip"><span className={`dot${log.live ? " neutral" : ""}`} />{log.live ? "Live" : "Paused"}</span>
          <button className="button small secondary" onClick={() => log.setLive(!log.live)}>{log.live ? "Pause" : "Resume"}</button>
          <button className="button small secondary" onClick={log.clear}>Clear</button>
          <button className="button small" onClick={download}>Download log</button>
        </div>
      </div>
      <p className="label" style={{ marginTop: 8 }}>
        Every minute, website heartbeat and alert decision, newest first. Click a line for its full details.
        Kept only in Commit's memory; never titles, URLs or what you type.
      </p>
      <div className="row" style={{ margin: "8px 0 12px" }}>
        <div className="pills" role="group" aria-label="Event kind">
          <button aria-pressed={kind === "all"} onClick={() => setKind("all")}>All {log.events.length}</button>
          {KINDS.map((name) => (
            <button key={name} aria-pressed={kind === name} onClick={() => setKind(name)}>{KIND_LABELS[name]} {counts[name]}</button>
          ))}
        </div>
        <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search events" aria-label="Search events" style={{ flex: 1, minWidth: 160 }} />
      </div>
      {log.error && <div className="banner">{log.error}</div>}
      <ul className="log">
        {shown.length === 0 && (
          <li className="empty">{log.events.length ? "No events match." : "Waiting for events… The first ones appear at the next full minute."}</li>
        )}
        {shown.map((event) => (
          <EventRow key={event.id} event={event} open={openIds.has(event.id)} onToggle={() => toggle(event.id)} />
        ))}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------------ live state

function DecisionState({ snapshot }) {
  const state = snapshot.decision_state || {};
  const left = (until) => duration((until || 0) - snapshot.now);
  const latest = snapshot.minutes.find((m) => m.condition_probs);
  return (
    <section className="card">
      <h2>Alert rules state</h2>
      <table>
        <tbody>
          <tr><td>Do Not Disturb on for</td><td>{left(state.dnd_on_until)}</td></tr>
          <tr><td>DND question blocked for</td><td>{left(state.dnd_ask_blocked_until)}</td></tr>
          <tr><td>Break suggestion blocked for</td><td>{left(state.break_blocked_until)}</td></tr>
          <tr><td>Website categoriser</td><td>{snapshot.categoriser_mode}</td></tr>
          <tr><td>Latest prediction</td><td>{latest ? `${clock(latest.ts)} · ${probabilities(latest.condition_probs)}` : "–"}</td></tr>
        </tbody>
      </table>
    </section>
  );
}

function RowCounts({ counts }) {
  return (
    <section className="card">
      <h2>Rows in the database</h2>
      <table>
        <tbody>
          {Object.entries(counts).map(([table, count]) => (
            <tr key={table}><td><code>{table}</code></td><td>{count}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ------------------------------------------------------------------ tracked tables

function MinutesTable({ rows }) {
  const [openTs, setOpenTs] = useState(null);
  return (
    <table>
      <thead><tr><th>Minute</th><th>Mode</th><th>App category</th><th>Condition</th><th>Probabilities</th><th>Load</th><th /></tr></thead>
      <tbody>
        {rows.map((row) => (
          <Fragment key={row.ts}>
            <tr>
              <td>{formatDateTime(row.ts)}</td>
              <td>{row.mode}</td>
              <td>{row.app_category || "–"}</td>
              <td>{row.condition ? <span className="row" style={{ gap: 6 }}><span className={`dot ${row.condition}`} />{CONDITION_LABELS[row.condition]}</span> : "–"}</td>
              <td className="label">{probabilities(row.condition_probs)}</td>
              <td>{row.load_score === null ? "–" : Math.round(row.load_score)}</td>
              <td>{row.features && (
                <button className="button small secondary" onClick={() => setOpenTs(openTs === row.ts ? null : row.ts)}>
                  {openTs === row.ts ? "Hide" : "Features"}
                </button>
              )}</td>
            </tr>
            {openTs === row.ts && (
              <tr><td colSpan={7}><pre className="log-data">{JSON.stringify(row.features, null, 2)}</pre></td></tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function SimpleTable({ rows, columns }) {
  return (
    <table>
      <thead><tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>{columns.map((c) => <td key={c.key}>{c.format ? c.format(row[c.key]) : (row[c.key] ?? "–")}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

const TIME_COLUMN = { key: "ts", label: "Time", format: formatDateTime };
const COLUMNS = {
  app_time: [TIME_COLUMN, { key: "app_name", label: "App" }, { key: "category", label: "Category" }, { key: "seconds", label: "Seconds" }],
  web_time: [TIME_COLUMN, { key: "domain", label: "Domain", format: (d) => d ?? "(no name kept)" }, { key: "category", label: "Category" }, { key: "seconds", label: "Seconds" }],
  alerts: [TIME_COLUMN, { key: "kind", label: "Kind" }, { key: "reason", label: "Reason" }, { key: "action", label: "Action" }, { key: "feedback", label: "Feedback" }],
  checkins: [TIME_COLUMN, { key: "rating", label: "Rating (1–5)" }],
};

function TrackedData({ snapshot }) {
  const [table, setTable] = useState("minutes");
  let body;
  if (table === "rules") {
    body = <pre className="log-data">{JSON.stringify({ rules: snapshot.rules, baseline: snapshot.baseline }, null, 2)}</pre>;
  } else if (snapshot[table].length === 0) {
    body = <p className="empty">Nothing recorded yet.</p>;
  } else if (table === "minutes") {
    body = <MinutesTable rows={snapshot.minutes} />;
  } else {
    body = <SimpleTable rows={snapshot[table]} columns={COLUMNS[table]} />;
  }
  return (
    <section className="card">
      <div className="row spread">
        <h2 style={{ margin: 0 }}>Tracked data</h2>
        <span className="label">Latest 60 rows per table · refreshes every {SNAPSHOT_REFRESH_SECONDS} s</span>
      </div>
      <div className="pills" role="group" aria-label="Table" style={{ margin: "12px 0" }}>
        {TABLES.map((t) => <button key={t.id} aria-pressed={table === t.id} onClick={() => setTable(t.id)}>{t.label}</button>)}
      </div>
      <div className="table-scroll">{body}</div>
    </section>
  );
}

// ------------------------------------------------------------------ the page

export default function Developer() {
  const { data: snapshot, error } = useLoad("/api/dev/snapshot", SNAPSHOT_REFRESH_SECONDS);
  const log = useEventLog();

  if (error) return <div className="banner">{error}</div>;
  if (!snapshot) return <p className="empty">Loading…</p>;

  const status = snapshot.status;
  const calibration = status.calibration;
  return (
    <>
      <section className="stats">
        <StatCard label="State" value={status.paused ? "Paused" : status.state} highlight />
        <StatCard label="Load score" value={status.load_score === null || status.load_score === undefined ? "–" : Math.round(status.load_score)} />
        <StatCard label="Calibration" value={!calibration ? "–" : calibration.complete ? "Done" : `${calibration.collected}/${calibration.needed}`} />
        <StatCard label="Events in this view" value={log.events.length} />
      </section>
      <EventLog log={log} snapshot={snapshot} />
      <div className="grid two">
        <DecisionState snapshot={snapshot} />
        <RowCounts counts={snapshot.row_counts} />
      </div>
      <TrackedData snapshot={snapshot} />
    </>
  );
}
