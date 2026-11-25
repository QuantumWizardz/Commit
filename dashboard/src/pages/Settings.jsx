// dashboard/src/pages/Settings.jsx — every setting in one place (README 10.2).
//
// Each card saves only its own fields with PUT /api/settings; the server checks every value and
// answers with the full, updated settings. The API key is sent once and kept only in the macOS Keychain.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useLoad } from "../components/useLoad.js";

const CATEGORISER_MODES = [
  { id: "off", label: "Off" },
  { id: "rules", label: "Rules only" },
  { id: "local", label: "Local AI" },
  { id: "api", label: "My API key" },
];
const MODE_CONSENT = { local: "title_local", api: "title_api" };

const CONSENT_TEXT = {
  activity_counts: "Activity counts (required): keyboard/mouse counts and app names. Never what you type.",
  website_tracking: "Website tracking: domain, category and time from the Chrome extension.",
  title_local: "Title categorisation on this computer (local AI). Nothing leaves your computer.",
  title_api: "Title categorisation with my own API key. Shortened titles, without e-mails, links or long numbers, are sent to that provider.",
  checkins: "Load check-in pop-ups (about every 45 active minutes).",
};

/** Small helper: a card with a title. */
function Section({ title, children }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      <div className="stack">{children}</div>
    </section>
  );
}

/** Shows "Saved." or an error under a form. */
function Status({ message }) {
  if (!message) return null;
  return <p className="label" role="status">{message}</p>;
}

// ------------------------------------------------------------------ profile, DND, check-ins

function ProfileSection({ settings, save }) {
  const [name, setName] = useState(settings.name);
  return (
    <Section title="Your name">
      <div className="row">
        <input type="text" value={name} onChange={(event) => setName(event.target.value)} aria-label="Your name" placeholder="Used in the greeting" />
        <button className="button" onClick={() => save({ name })}>Save</button>
      </div>
    </Section>
  );
}

function DndSection({ settings, save }) {
  return (
    <Section title="Do Not Disturb">
      <p className="label">When you seem to be under pressure for a while, Commit can turn on Do Not Disturb for 25 minutes.
        Who can still reach you is set in System Settings → Focus → Do Not Disturb.</p>
      <div className="pills" role="group" aria-label="Do Not Disturb mode">
        <button aria-pressed={settings.dnd_mode === "ask"} onClick={() => save({ dnd_mode: "ask" })}>Ask first</button>
        <button aria-pressed={settings.dnd_mode === "auto"} onClick={() => save({ dnd_mode: "auto" })}>Always automatic</button>
      </div>
    </Section>
  );
}

function CheckinSection({ settings, save }) {
  const [minutes, setMinutes] = useState(settings.checkin_every_active_minutes);
  const enabled = Boolean(settings.consent?.choices?.checkins);
  return (
    <Section title="Load check-ins">
      <label className="switch">
        <input type="checkbox" checked={enabled} onChange={() => save({ consent: { checkins: !enabled } })} />
        <span>Ask "How mentally loaded do you feel right now?" (1–5). Your answers personalise the load score.</span>
      </label>
      <div className="row">
        <label className="label" htmlFor="checkin-minutes">Every</label>
        <input id="checkin-minutes" type="number" min="15" max="240" value={minutes} onChange={(event) => setMinutes(Number(event.target.value))} style={{ width: 100 }} />
        <span className="label">active minutes</span>
        <button className="button secondary" onClick={() => save({ checkin_every_active_minutes: minutes })}>Save</button>
      </div>
    </Section>
  );
}

// ------------------------------------------------------------------ website categories (LLM)

function ModelFields({ mode, settings, save }) {
  const current = settings.categoriser[mode];
  const [baseUrl, setBaseUrl] = useState(current.base_url);
  const [model, setModel] = useState(current.model);
  const [apiKey, setApiKey] = useState("");
  const [noThinking, setNoThinking] = useState(mode === "api" ? current.disable_thinking : true);

  function saveModel() {
    const prefix = mode === "local" ? "local" : "api";
    const changes = { [`${prefix}_base_url`]: baseUrl, [`${prefix}_model`]: model };
    if (mode === "api") {
      changes.api_disable_thinking = noThinking;
      if (apiKey) changes.api_key = apiKey;
    }
    save(changes).then(() => setApiKey(""));
  }

  return (
    <div className="stack">
      <div className="row">
        <div className="field">
          <label className="label" htmlFor="model-url">{mode === "local" ? "Ollama address" : "API address (OpenAI-compatible)"}</label>
          <input id="model-url" type="text" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)}
            placeholder={mode === "local" ? "http://127.0.0.1:11434/v1" : "e.g. https://api.groq.com/openai/v1"} />
        </div>
        <div className="field">
          <label className="label" htmlFor="model-name">Model name</label>
          <input id="model-name" type="text" value={model} onChange={(event) => setModel(event.target.value)}
            placeholder={mode === "local" ? "e.g. llama3.2:3b" : "exact model id from your provider"} />
        </div>
      </div>
      {mode === "api" && (
        <>
          <div className="field">
            <label className="label" htmlFor="api-key">API key {current.key_saved ? "(a key is saved — type a new one to replace it)" : ""}</label>
            <div className="row">
              <input id="api-key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)}
                placeholder={current.key_saved ? "••••••••" : "Paste your key"} style={{ flex: 1 }} />
              {current.key_saved && <button className="button secondary" onClick={() => save({ api_key: "" })}>Remove key</button>}
            </div>
            <span className="label">Stored only in the macOS Keychain, never in Commit's files.</span>
          </div>
          <label className="switch">
            <input type="checkbox" checked={noThinking} onChange={() => setNoThinking(!noThinking)} />
            <span>Turn off model "thinking" (recommended for reasoning models such as Qwen 3 — much faster)</span>
          </label>
        </>
      )}
      <div className="row"><button className="button" onClick={saveModel}>Save model settings</button></div>
    </div>
  );
}

function CategoriserSection({ settings, save }) {
  const [pendingMode, setPendingMode] = useState(null);   // mode waiting for consent
  const [testResult, setTestResult] = useState("");
  const categoriser = settings.categoriser;
  const choices = settings.consent?.choices || {};

  function choose(mode) {
    const consentKey = MODE_CONSENT[mode];
    if (consentKey && !choices[consentKey]) {
      setPendingMode(mode);                             // ask for consent first
      return;
    }
    setPendingMode(null);
    save({ categoriser_mode: mode });
  }

  async function test() {
    setTestResult("Testing…");
    try {
      const result = await api("POST", "/api/llm/test");
      setTestResult(result.message);
    } catch (problem) {
      setTestResult(problem.message);
    }
  }

  const showFields = categoriser.mode === "local" || categoriser.mode === "api";
  return (
    <Section title="Website categories">
      <p className="label">Commit sorts websites into categories using domain rules, then (optionally) an AI model that reads the page or video title. Titles are never stored.</p>
      <div className="pills" role="group" aria-label="Categoriser mode">
        {CATEGORISER_MODES.map((mode) => (
          <button key={mode.id} aria-pressed={categoriser.mode === mode.id} onClick={() => choose(mode.id)}>{mode.label}</button>
        ))}
      </div>
      {pendingMode && (
        <div className="banner">
          <p>{CONSENT_TEXT[MODE_CONSENT[pendingMode]]}</p>
          <div className="row">
            <button className="button" onClick={() => { save({ consent: { [MODE_CONSENT[pendingMode]]: true }, categoriser_mode: pendingMode }); setPendingMode(null); }}>Allow and switch</button>
            <button className="button secondary" onClick={() => setPendingMode(null)}>Cancel</button>
          </div>
        </div>
      )}
      {categoriser.effective_mode !== categoriser.mode && (
        <p className="label">Currently using "{categoriser.effective_mode}" because consent or the API key is missing.</p>
      )}
      {showFields && <ModelFields key={categoriser.mode} mode={categoriser.mode} settings={settings} save={save} />}
      {showFields && (
        <div className="row">
          <button className="button secondary" onClick={test}>Test connection</button>
          <span className="label" role="status">{testResult}</span>
        </div>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------ quiet hours, private websites, pairing

function QuietHoursSection({ settings, save }) {
  const [from, setFrom] = useState("22:00");
  const [to, setTo] = useState("08:00");
  const periods = settings.quiet_hours;
  return (
    <Section title="Quiet hours">
      <p className="label">No suggestions or check-ins during these times (calls in Zoom, Teams, FaceTime or Google Meet are always quiet).</p>
      <ul className="list">
        {periods.length === 0 && <li className="empty">No quiet hours.</li>}
        {periods.map((period) => (
          <li key={period}>
            <span>{period.replace("-", " – ")}</span>
            <button className="button small secondary" onClick={() => save({ quiet_hours: periods.filter((p) => p !== period) })}>Remove</button>
          </li>
        ))}
      </ul>
      <div className="row">
        <input type="time" value={from} onChange={(event) => setFrom(event.target.value)} aria-label="Quiet from" />
        <span>to</span>
        <input type="time" value={to} onChange={(event) => setTo(event.target.value)} aria-label="Quiet until" />
        <button className="button secondary" onClick={() => save({ quiet_hours: [...periods, `${from}-${to}`] })}>Add</button>
      </div>
    </Section>
  );
}

function PrivateSitesSection() {
  const [domains, setDomains] = useState([]);
  const [input, setInput] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    api("GET", "/api/private-domains").then((result) => setDomains(result.domains)).catch((problem) => setMessage(problem.message));
  }, []);

  async function change(method, domain) {
    try {
      const result = await api(method, "/api/private-domains", { domain });
      setDomains(result.domains);
      setMessage("");
      setInput("");
    } catch (problem) {
      setMessage(problem.message);
    }
  }

  return (
    <Section title="Private websites (don't track)">
      <p className="label">Time on these sites (and their subdomains) appears only as "Private", with no site name.</p>
      <ul className="list">
        {domains.length === 0 && <li className="empty">No private sites.</li>}
        {domains.map((domain) => (
          <li key={domain}>
            <span>{domain}</span>
            <button className="button small secondary" onClick={() => change("DELETE", domain)}>Remove</button>
          </li>
        ))}
      </ul>
      <div className="row">
        <input type="text" value={input} onChange={(event) => setInput(event.target.value)} placeholder="e.g. bank.com" aria-label="Domain to stop tracking" style={{ flex: 1 }} />
        <button className="button" onClick={() => change("POST", input)} disabled={!input.trim()}>Add</button>
      </div>
      <Status message={message} />
    </Section>
  );
}

function PairingSection({ settings }) {
  const [visible, setVisible] = useState(false);
  const [message, setMessage] = useState("");

  async function copy() {
    try {
      await navigator.clipboard.writeText(settings.pairing_token);
      setMessage("Copied. Paste it in the extension: click the Commit icon in Chrome → Pairing → Save.");
    } catch {
      setMessage("Could not copy automatically; press Show and copy it by hand.");
    }
  }

  return (
    <Section title="Chrome extension pairing">
      <div className="row">
        <code style={{ flex: 1, wordBreak: "break-all" }}>{visible ? settings.pairing_token : "•".repeat(24)}</code>
        <button className="button secondary" onClick={() => setVisible(!visible)}>{visible ? "Hide" : "Show"}</button>
        <button className="button" onClick={copy}>Copy</button>
      </div>
      <Status message={message} />
    </Section>
  );
}

// ------------------------------------------------------------------ calibration, data, consent

function CalibrationSection({ settings, reload }) {
  const calibration = settings.calibration;
  const [message, setMessage] = useState("");

  async function restart() {
    await api("POST", "/api/calibration/restart");
    setMessage("Calibration restarted: Commit will learn from your next 15 active minutes.");
    reload();
  }

  return (
    <Section title="Calibration">
      <p>{!calibration ? "Starting…" : calibration.complete
        ? "Commit knows your normal pattern."
        : `Learning your normal pattern: ${calibration.collected} of ${calibration.needed} active minutes.`}</p>
      <div className="row"><button className="button secondary" onClick={restart}>Re-run calibration</button></div>
      <Status message={message} />
    </Section>
  );
}

function DataSection({ settings, save, reload }) {
  const [days, setDays] = useState(settings.retention_days);
  const [confirmText, setConfirmText] = useState("");
  const [deleted, setDeleted] = useState(false);

  async function togglePause() {
    await api("POST", settings.paused ? "/api/resume" : "/api/pause");
    reload();
  }

  async function deleteEverything() {
    await api("DELETE", "/api/data", { confirm: "DELETE" });
    setDeleted(true);
  }

  if (deleted) {
    return <Section title="Your data"><div className="banner ok">All Commit data was deleted and Commit has quit. You can close this page.</div></Section>;
  }

  return (
    <Section title="Your data">
      <label className="switch">
        <input type="checkbox" checked={settings.paused} onChange={togglePause} />
        <span>Pause tracking (nothing is counted while paused)</span>
      </label>
      <div className="row">
        <label className="label" htmlFor="retention">Keep data for</label>
        <input id="retention" type="number" min="1" max="365" value={days} onChange={(event) => setDays(Number(event.target.value))} style={{ width: 100 }} />
        <span className="label">days</span>
        <button className="button secondary" onClick={() => save({ retention_days: days })}>Save</button>
      </div>
      <div className="banner">
        <strong>Delete all my data</strong>
        <p className="label">Removes the database, cache, consent record, API key, reports and logs. Commit then quits. This cannot be undone.</p>
        <div className="row">
          <input type="text" value={confirmText} onChange={(event) => setConfirmText(event.target.value)} placeholder='Type DELETE to confirm' aria-label="Type DELETE to confirm" />
          <button className="button danger" disabled={confirmText !== "DELETE"} onClick={deleteEverything}>Delete everything</button>
        </div>
      </div>
    </Section>
  );
}

function ConsentSection({ settings, save }) {
  const consent = settings.consent;
  if (!consent) return null;
  return (
    <Section title="Consent choices">
      <p className="label">Version {consent.version}, last changed {consent.date}. Read docs/PRIVACY.md for the full privacy policy.</p>
      {Object.entries(CONSENT_TEXT).map(([key, text]) => (
        <label className="switch" key={key}>
          <input type="checkbox" checked={Boolean(consent.choices[key])} disabled={key === "activity_counts"}
            onChange={() => save({ consent: { [key]: !consent.choices[key] } })} />
          <span>{text}</span>
        </label>
      ))}
      <p className="label">Activity counts are required. To withdraw them, use "Delete all my data" below or the menu bar's Consent choices.</p>
    </Section>
  );
}

// ------------------------------------------------------------------ the page

export default function Settings() {
  const { data, error, reload } = useLoad("/api/settings");
  const [settings, setSettings] = useState(null);
  const [message, setMessage] = useState("");

  useEffect(() => { if (data) setSettings(data); }, [data]);

  /** Save some fields; returns a promise so forms can clear themselves afterwards. */
  async function save(changes) {
    try {
      setSettings(await api("PUT", "/api/settings", changes));
      setMessage("Saved.");
    } catch (problem) {
      setMessage(problem.message);
    }
  }

  if (error) return <div className="banner">{error}</div>;
  if (!settings) return <p className="empty">Loading…</p>;

  return (
    <>
      {message && <div className={`banner${message === "Saved." ? " ok" : ""}`} role="status">{message}</div>}
      <div className="grid two">
        <div className="stack" style={{ gap: 16 }}>
          <ProfileSection settings={settings} save={save} />
          <CategoriserSection settings={settings} save={save} />
          <DndSection settings={settings} save={save} />
          <CheckinSection settings={settings} save={save} />
          <QuietHoursSection settings={settings} save={save} />
        </div>
        <div className="stack" style={{ gap: 16 }}>
          <PrivateSitesSection />
          <PairingSection settings={settings} />
          <CalibrationSection settings={settings} reload={reload} />
          <DataSection settings={settings} save={save} reload={reload} />
          <ConsentSection settings={settings} save={save} />
        </div>
      </div>
    </>
  );
}
