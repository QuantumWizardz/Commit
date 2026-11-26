// dashboard/src/components/CategoryBreakdown.jsx — "Time by category" where each category opens to
// show the apps and websites inside it, each with a category picker. Changing one moves its past
// time too and is used from the next minute on, so the bars update straight away.
import { useState } from "react";
import { api } from "../api.js";
import { formatMinutes } from "../format.js";

const UNNAMED_LABELS = {
  Private: "Private websites (no names kept)",
  Miscellaneous: "Browser pages without detail",
};

/** One app or website with a category picker. Unnamed (private) time has no picker. */
function ItemRow({ item, category, categories, onChanged }) {
  const [message, setMessage] = useState("");

  async function change(event) {
    const chosen = event.target.value;
    try {
      if (item.kind === "app") await api("PUT", "/api/app-rules", { app: item.name, category: chosen });
      else await api("PUT", "/api/domain-rules", { domain: item.name, category: chosen });
      setMessage("");
      onChanged();
    } catch (problem) {
      setMessage(problem.message);
    }
  }

  if (item.kind === "unnamed") {
    return (
      <tr>
        <td colSpan={2} className="label">{UNNAMED_LABELS[item.name] || "Pages without a name"}</td>
        <td>{formatMinutes(item.minutes)}</td>
        <td />
      </tr>
    );
  }
  return (
    <tr>
      <td><span className="chip">{item.kind === "app" ? "App" : "Website"}</span></td>
      <td>{item.name}</td>
      <td>{formatMinutes(item.minutes)}</td>
      <td>
        <select value={category} onChange={change} aria-label={`Category for ${item.name}`}>
          {categories.includes(category) ? null : <option>{category}</option>}
          {categories.map((name) => <option key={name}>{name}</option>)}
        </select>
        {message && <div className="label">{message}</div>}
      </td>
    </tr>
  );
}

/**
 * In:  items [{ name, minutes }] (one per category), itemsByCategory { category: [{ kind, name, minutes }] },
 *      categories the user can pick, and onChanged (reload the page data after a change).
 */
export default function CategoryBreakdown({ items, itemsByCategory = {}, categories = [], onChanged }) {
  const [open, setOpen] = useState(null);
  if (!items || items.length === 0) return <p className="empty">No data yet.</p>;
  const largest = Math.max(...items.map((item) => item.minutes), 1);

  return (
    <div className="bars">
      {items.map((item) => {
        const parts = itemsByCategory[item.name] || [];
        const isOpen = open === item.name;
        return (
          <div key={item.name}>
            <button
              className={`bar-row bar-button${isOpen ? " open" : ""}`}
              onClick={() => setOpen(isOpen ? null : item.name)}
              aria-expanded={isOpen}
              disabled={parts.length === 0}
              title={parts.length ? "Show what is in this category" : undefined}
            >
              <span>{parts.length > 0 && <span className="caret">{isOpen ? "▾" : "▸"}</span>}{item.name}</span>
              <div className="bar-track" role="img" aria-label={`${item.name}: ${formatMinutes(item.minutes)}`}>
                <div className="bar-fill" style={{ width: `${(item.minutes / largest) * 100}%` }} />
              </div>
              <span className="bar-value">{formatMinutes(item.minutes)}</span>
            </button>
            {isOpen && (
              <div className="breakdown table-scroll">
                <table>
                  <thead><tr><th /><th>Name</th><th>Time</th><th>Category</th></tr></thead>
                  <tbody>
                    {parts.map((part) => (
                      <ItemRow key={`${part.kind}:${part.name}`} item={part} category={item.name}
                               categories={categories} onChanged={onChanged} />
                    ))}
                  </tbody>
                </table>
                <p className="label">Changing a category also moves its past time.</p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
