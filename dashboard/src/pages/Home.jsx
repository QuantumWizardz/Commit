// dashboard/src/pages/Home.jsx — today at a glance: stat cards, today's timeline, recent alerts (README 10.2).
import AlertList from "../components/AlertList.jsx";
import { ConditionLegend, Timeline } from "../components/Charts.jsx";
import StatCard from "../components/StatCard.jsx";
import { useLoad } from "../components/useLoad.js";
import { formatMinutes } from "../format.js";

const REFRESH_SECONDS = 30;

/** Banner while Commit is still learning the user's normal pattern. */
function CalibrationBanner({ calibration }) {
  if (!calibration || calibration.complete) return null;
  return (
    <div className="banner">
      <strong>Learning your normal pattern…</strong> {calibration.collected} of {calibration.needed} active minutes so far.
      Predictions and suggestions start after that.
    </div>
  );
}

export default function Home() {
  const { data, error } = useLoad("/api/today", REFRESH_SECONDS);
  if (error) return <div className="banner">{error}</div>;
  if (!data) return <p className="empty">Loading…</p>;

  const today = data.today;
  const yesterday = data.yesterday;
  const change = (key) => today[key] - yesterday[key];

  return (
    <>
      <CalibrationBanner calibration={data.status.calibration} />

      <section className="stats" aria-label="Today">
        <StatCard label="Active time today" value={formatMinutes(today.active_minutes)} change={change("active_minutes")} formatChange={formatMinutes} />
        <StatCard label="Focus (Neutral)" value={formatMinutes(today.neutral_minutes)} change={change("neutral_minutes")} formatChange={formatMinutes} />
        <StatCard label="Interrupted" value={formatMinutes(today.interrupted_minutes)} change={change("interrupted_minutes")} formatChange={formatMinutes} />
        <StatCard label="Pressured" value={formatMinutes(today.pressured_minutes)} change={change("pressured_minutes")} formatChange={formatMinutes} />
        <StatCard label="Breaks taken" value={today.breaks_taken} change={change("breaks_taken")} />
        <StatCard label="Current load score" value={data.load_score === null ? "–" : Math.round(data.load_score)} highlight />
      </section>

      <div className="grid two">
        <div className="card">
          <div className="row spread">
            <h2>Today's timeline</h2>
            <ConditionLegend />
          </div>
          {data.timeline.length === 0 && <p className="empty">No active minutes with a prediction yet today.</p>}
          <Timeline bands={data.timeline} dayStart={data.day_start} now={Date.now() / 1000} />
        </div>

        <div className="card">
          <h2>Recent alerts</h2>
          <AlertList alerts={data.recent_alerts} emptyText="No suggestions yet. That's fine!" />
        </div>
      </div>
    </>
  );
}
