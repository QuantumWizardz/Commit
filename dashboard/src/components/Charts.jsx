// dashboard/src/components/Charts.jsx — simple flat charts made with plain HTML/CSS (no chart library).
import { formatMinutes, formatTime, CONDITION_LABELS } from "../format.js";

const SECONDS_PER_HOUR = 3600;
const DEFAULT_DAY_START_HOUR = 8;     // the timeline starts at 08:00 unless work started earlier
const AXIS_LABELS = 5;

/** Horizontal hatched bars, e.g. time per category. items: [{ name, minutes }] */
export function BarList({ items, emptyText = "No data yet." }) {
  if (!items || items.length === 0) return <p className="empty">{emptyText}</p>;
  const largest = Math.max(...items.map((item) => item.minutes), 1);
  return (
    <div className="bars">
      {items.map((item) => (
        <div className="bar-row" key={item.name}>
          <span>{item.name}</span>
          <div className="bar-track" role="img" aria-label={`${item.name}: ${formatMinutes(item.minutes)}`}>
            <div className="bar-fill" style={{ width: `${(item.minutes / largest) * 100}%` }} />
          </div>
          <span className="bar-value">{formatMinutes(item.minutes)}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Vertical bars per day.
 * days: [{ label, value }]; format turns a value into its label text (default: minutes);
 * maximum = the value of a full-height bar (default: the largest value, e.g. 100 for load scores).
 */
export function DayColumns({ days, format = formatMinutes, maximum }) {
  const largest = maximum || Math.max(...days.map((day) => day.value), 1);
  return (
    <div className="columns">
      {days.map((day) => (
        <div className="column" key={day.label} title={`${day.label}: ${format(day.value)}`}>
          <span>{day.value ? format(day.value) : ""}</span>
          <div className="column-fill" style={{ height: `${(day.value / largest) * 80}%` }} />
          <span>{day.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Legend chips for the three conditions. */
export function ConditionLegend() {
  return (
    <div className="row">
      {Object.entries(CONDITION_LABELS).map(([key, label]) => (
        <span className="chip" key={key}><span className={`dot ${key}`} />{label}</span>
      ))}
    </div>
  );
}

/**
 * Today's timeline: coloured bands for Neutral / Interrupted / Pressured.
 * In: bands [{ start, end, condition }] (unix seconds), the start of today, the current time.
 */
export function Timeline({ bands, dayStart, now }) {
  const defaultStart = dayStart + DEFAULT_DAY_START_HOUR * SECONDS_PER_HOUR;
  const firstStart = bands.length ? Math.min(bands[0].start, defaultStart) : defaultStart;
  const start = Math.floor(firstStart / SECONDS_PER_HOUR) * SECONDS_PER_HOUR;
  const end = Math.max(now, start + SECONDS_PER_HOUR);
  const span = end - start;
  const ticks = Array.from({ length: AXIS_LABELS }, (_, index) => start + (span * index) / (AXIS_LABELS - 1));

  return (
    <div>
      <div className="timeline" role="img" aria-label="Today's working conditions over time">
        {bands.map((band) => (
          <div
            key={band.start}
            className={`band ${band.condition}`}
            title={`${CONDITION_LABELS[band.condition]} ${formatTime(band.start)}–${formatTime(band.end)}`}
            style={{ left: `${((band.start - start) / span) * 100}%`, width: `${((band.end - band.start) / span) * 100}%` }}
          />
        ))}
      </div>
      <div className="timeline-axis">
        {ticks.map((tick) => <span key={tick}>{formatTime(tick)}</span>)}
      </div>
    </div>
  );
}
