// dashboard/src/App.jsx — the page frame: sidebar, header (greeting + "Download weekly report"), and the
// current screen. Screens are chosen by the address hash (#/home, #/activity, …), so no router library is needed.
import { useEffect, useState } from "react";
import { api, downloadWeeklyPdf } from "./api.js";
import Sidebar, { PAGES } from "./components/Sidebar.jsx";
import { useLoad } from "./components/useLoad.js";
import { greeting } from "./format.js";
import Activity from "./pages/Activity.jsx";
import Alerts from "./pages/Alerts.jsx";
import Home from "./pages/Home.jsx";
import Settings from "./pages/Settings.jsx";
import WeeklyReport from "./pages/WeeklyReport.jsx";

const SCREENS = { home: Home, activity: Activity, report: WeeklyReport, alerts: Alerts, settings: Settings };
const STATUS_REFRESH_SECONDS = 15;

/** The page id from the address, e.g. "#/activity" -> "activity" (Home if unknown). */
function pageFromHash() {
  const id = window.location.hash.replace("#/", "");
  return SCREENS[id] ? id : "home";
}

export default function App() {
  const [page, setPage] = useState(pageFromHash());
  const [downloadError, setDownloadError] = useState(null);
  const { data: status, reload: reloadStatus } = useLoad("/api/status", STATUS_REFRESH_SECONDS);
  const { data: settings } = useLoad("/api/settings");

  // Follow the address bar when a navigation link is clicked.
  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  async function togglePause() {
    await api("POST", status.paused ? "/api/resume" : "/api/pause");
    reloadStatus();
  }

  async function download() {
    try {
      await downloadWeeklyPdf();
      setDownloadError(null);
    } catch (problem) {
      setDownloadError(problem.message);
    }
  }

  const Screen = SCREENS[page];
  const name = settings && settings.name ? `, ${settings.name}` : "";
  const title = page === "home" ? `${greeting()}${name}` : PAGES.find((item) => item.id === page).label;

  return (
    <div className="layout">
      <Sidebar page={page} status={status} onTogglePause={togglePause} />
      <main className="main">
        <header className="header">
          <div>
            <h1>{title}</h1>
            <p className="subtitle">{new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}</p>
          </div>
          <button className="button" onClick={download}>Download weekly report</button>
        </header>
        {downloadError && <div className="banner">{downloadError}</div>}
        <Screen key={page} />
      </main>
    </div>
  );
}
