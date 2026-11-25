// dashboard/src/components/AlertList.jsx — alerts with time, reason, what the user did, and 👍/👎 buttons.
import { useState } from "react";
import { api } from "../api.js";
import { actionLabel, alertKindLabel, formatDateTime } from "../format.js";

/** 👍/👎 buttons for one alert. The chosen one is shown pressed. */
function FeedbackButtons({ alert, onSaved }) {
  const [feedback, setFeedback] = useState(alert.feedback);
  const [error, setError] = useState(null);

  async function save(value) {
    try {
      await api("POST", `/api/alerts/${alert.id}/feedback`, { feedback: value });
      setFeedback(value);
      setError(null);
      if (onSaved) onSaved();
    } catch (problem) {
      setError(problem.message);
    }
  }

  return (
    <div className="row feedback">
      <button className="button small secondary" aria-pressed={feedback === "up"} aria-label="This alert was right" onClick={() => save("up")}>👍</button>
      <button className="button small secondary" aria-pressed={feedback === "down"} aria-label="This alert was wrong" onClick={() => save("down")}>👎</button>
      {error && <span className="label">{error}</span>}
    </div>
  );
}

export default function AlertList({ alerts, emptyText = "No alerts yet." }) {
  if (!alerts || alerts.length === 0) return <p className="empty">{emptyText}</p>;
  return (
    <ul className="list">
      {alerts.map((alert) => (
        <li key={alert.id} style={{ alignItems: "flex-start" }}>
          <div className="stack" style={{ gap: 4 }}>
            <div className="row">
              <span className={`chip${alert.kind === "dnd" ? " tag" : ""}`}>{alertKindLabel(alert.kind)}</span>
              <span className="label">{formatDateTime(alert.ts)} · {actionLabel(alert.action)}</span>
            </div>
            <span>{alert.reason}</span>
          </div>
          <FeedbackButtons alert={alert} />
        </li>
      ))}
    </ul>
  );
}
