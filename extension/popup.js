/*
 * extension/popup.js — the popup: connection status, "Don't track this site", the private list
 * (README 9.1), and the pairing token + port.
 *
 * The private list lives in the Commit app (so the dashboard can edit it too); the popup reads
 * and changes it through the app's local API. All page text is set with textContent (never as HTML).
 */

const STATUS_TEXT = {
  not_paired: "Not paired",
  wrong_token: "Wrong token",
  offline: "App not running",
  error: "App error",
};

let currentDomain = null;   // domain of the active tab, or null for chrome:// pages

function show(id, text) {
  document.getElementById(id).textContent = text;
}

/** Status chip: green when connected, amber otherwise. */
async function showStatus() {
  const result = await callApp("GET", "/api/status");
  const dot = document.getElementById("status-dot");
  if (result.ok) {
    dot.className = "dot ok";
    show("status-text", result.data.website_tracking ? `Connected · ${result.data.state}` : "Connected · website tracking off");
  } else {
    dot.className = "dot warn";
    show("status-text", STATUS_TEXT[result.reason]);
  }
}

/** Draw the private list with a Remove button per domain. */
function drawPrivateList(domains) {
  const list = document.getElementById("private-list");
  list.replaceChildren();
  if (domains.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No private sites yet.";
    list.appendChild(empty);
  }
  for (const domain of domains) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = domain;
    const remove = document.createElement("button");
    remove.className = "button secondary";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => changePrivate("DELETE", domain));
    item.append(name, remove);
    list.appendChild(item);
  }
  drawCurrentSite(domains);
}

/** "This site" card: shows the domain and a Don't track / Track again button. */
function drawCurrentSite(domains) {
  const button = document.getElementById("current-toggle");
  if (currentDomain === null) {
    show("current-domain", "Not a website");
    button.hidden = true;
    return;
  }
  const listed = domains.find((listedDomain) => currentDomain === listedDomain || currentDomain.endsWith("." + listedDomain));
  show("current-domain", listed ? `${currentDomain} (private)` : currentDomain);
  button.hidden = false;
  button.textContent = listed ? "Track again" : "Don't track";
  button.onclick = () => changePrivate(listed ? "DELETE" : "POST", listed || currentDomain);
}

/** Load the private list from the app (falls back to the saved copy when the app is offline). */
async function loadPrivateList() {
  const result = await callApp("GET", "/api/private-domains");
  if (result.ok) {
    await chrome.storage.local.set({ privateDomains: result.data.domains });
    drawPrivateList(result.data.domains);
  } else {
    drawPrivateList((await getSettings()).privateDomains);
  }
}

/** Add (POST) or remove (DELETE) a private domain through the app. */
async function changePrivate(method, domain) {
  const result = await callApp(method, "/api/private-domains", { domain: normaliseDomain(domain) });
  if (!result.ok) {
    show("message", "Could not change the list: " + STATUS_TEXT[result.reason] + ". Is the Commit app running and paired?");
    return;
  }
  await chrome.storage.local.set({ privateDomains: result.data.domains });
  show("message", "");
  drawPrivateList(result.data.domains);
}

/** Save the pairing token and port, then re-check the connection. */
async function saveSettings() {
  const token = document.getElementById("token-input").value.trim();
  const port = Number(document.getElementById("port-input").value) || DEFAULT_PORT;
  await chrome.storage.local.set({ token: token, port: port });
  show("message", "Saved.");
  await showStatus();
  await loadPrivateList();
}

async function init() {
  const settings = await getSettings();
  document.getElementById("token-input").value = settings.token;
  document.getElementById("port-input").value = settings.port;

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const page = tab ? describePage(tab.url || "", "", []) : { category: "Other" };
  currentDomain = page.domain || null;

  document.getElementById("settings-save").addEventListener("click", saveSettings);
  document.getElementById("private-add").addEventListener("click", () => {
    const input = document.getElementById("private-input");
    if (input.value.trim()) {
      changePrivate("POST", input.value).then(() => { input.value = ""; });
    }
  });
  await showStatus();
  await loadPrivateList();
}

init();
