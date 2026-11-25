/*
 * extension/background.js — tracks time on the active tab and reports it to the Commit app
 * (README module M2.2). Runs as the extension's service worker.
 *
 * What is tracked: only the ACTIVE tab in the FOCUSED Chrome window, while the user is active.
 * Tracking pauses when Chrome loses focus, the screen is locked, or the user is idle (chrome.idle).
 *
 * How: the time on one page is a "segment". A segment ends (and a heartbeat is sent) when the
 * active tab or its title changes, when Chrome loses focus / the user goes idle, and every 30
 * seconds (an alarm), so time is reported even on a page that does not change.
 *
 * What is sent to http://127.0.0.1 (nothing else is ever contacted):
 *   normal website          {domain, title, seconds}   the app uses the title to pick a category, then discards it
 *   domain on private list  {category: "Private", seconds}   no domain, no title
 *   chrome:// pages etc.    {category: "Other", seconds}
 *   incognito               nothing — the extension does not run in incognito ("incognito": "not_allowed")
 *
 * Segment state lives in chrome.storage.session (memory only, cleared when Chrome closes).
 */

importScripts("common.js");   // normaliseDomain, isPrivate, describePage, getSettings, callApp

const HEARTBEAT_ALARM = "commit-heartbeat";
const HEARTBEAT_MINUTES = 0.5;          // every 30 seconds (the shortest alarm Chrome allows)
const IDLE_DETECTION_SECONDS = 60;      // no input for this long = idle
const MAX_SEGMENT_SECONDS = 120;        // never report more than this in one heartbeat (e.g. after sleep)
const MILLISECONDS_PER_SECOND = 1000;

// ------------------------------------------------------------------ server calls

/** Fetch the private list from the app and keep a copy (used even when the app is briefly offline). */
async function refreshPrivateDomains() {
  const result = await callApp("GET", "/api/private-domains");
  if (result.ok) {
    await chrome.storage.local.set({ privateDomains: result.data.domains });
  }
}

/** Report `seconds` spent on the segment's page. If the app is not running, the time is dropped. */
async function sendHeartbeat(segment, seconds) {
  const settings = await getSettings();
  const page = describePage(segment.url, segment.title, settings.privateDomains);
  await callApp("POST", "/api/web/heartbeat", { ...page, seconds: seconds });
}

// ------------------------------------------------------------------ segments

/** End the current segment (if any) and report its time. */
async function closeSegment() {
  const { segment } = await chrome.storage.session.get("segment");
  if (!segment) {
    return;
  }
  await chrome.storage.session.remove("segment");
  const seconds = Math.min(Math.round((Date.now() - segment.startedAt) / MILLISECONDS_PER_SECOND), MAX_SEGMENT_SECONDS);
  if (seconds >= 1) {
    await sendHeartbeat(segment, seconds);
  }
}

/** Start a segment for the active tab — only if Chrome is focused and the user is active. */
async function startSegmentForActiveTab() {
  const idleState = await chrome.idle.queryState(IDLE_DETECTION_SECONDS);
  if (idleState !== "active") {
    return;                                 // idle or screen locked
  }
  const focusedWindow = await chrome.windows.getLastFocused();
  if (!focusedWindow || !focusedWindow.focused) {
    return;                                 // another app is in front
  }
  const [tab] = await chrome.tabs.query({ active: true, windowId: focusedWindow.id });
  if (!tab || tab.incognito) {
    return;
  }
  await chrome.storage.session.set({
    segment: { tabId: tab.id, url: tab.url || "", title: tab.title || "", startedAt: Date.now() },
  });
}

/** Report the current segment and start a new one for whatever is active now. */
async function restartSegment() {
  await closeSegment();
  await startSegmentForActiveTab();
}

// Chrome events can arrive close together; run the handlers one after another so segments never overlap.
let pendingWork = Promise.resolve();
function runInOrder(task) {
  pendingWork = pendingWork.then(task).catch((error) => console.warn("Commit:", error.message));
  return pendingWork;
}

// ------------------------------------------------------------------ alarm and events

/** Make sure the 30-second alarm exists (creating it again would reset its timer). */
async function ensureAlarm() {
  const existing = await chrome.alarms.get(HEARTBEAT_ALARM);
  if (!existing) {
    await chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: HEARTBEAT_MINUTES });
  }
}

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.tabs.create({ url: "welcome.html" });   // explain what is collected (README 9.1)
  }
  runInOrder(ensureAlarm);
});
chrome.runtime.onStartup.addListener(() => runInOrder(ensureAlarm));

chrome.idle.setDetectionInterval(IDLE_DETECTION_SECONDS);
chrome.tabs.onActivated.addListener(() => runInOrder(restartSegment));
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.active && (changeInfo.title || changeInfo.url)) {
    runInOrder(restartSegment);
  }
});
chrome.windows.onFocusChanged.addListener(() => runInOrder(restartSegment));
chrome.idle.onStateChanged.addListener(() => runInOrder(restartSegment));
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === HEARTBEAT_ALARM) {
    runInOrder(async () => {
      await refreshPrivateDomains();
      await restartSegment();
    });
  }
});
runInOrder(ensureAlarm);
