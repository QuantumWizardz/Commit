/*
 * extension/common.js — small helpers shared by the background worker and the popup.
 * Loaded with importScripts() in background.js and with a <script> tag in popup.html.
 * The pure functions (isPrivate, describePage, normaliseDomain) are tested from Python via Node
 * (tests/test_extension.py).
 */

const DEFAULT_PORT = 8765;              // the Commit app's local server port (config server.port)

/** "WWW.Bank.com" or "https://www.bank.com/login" -> "bank.com" */
function normaliseDomain(text) {
  let host = text.trim().toLowerCase().replace(/^https?:\/\//, "").split("/")[0].split(":")[0];
  return host.replace(/^www\./, "");
}

/** True if `domain` is on the private list, or is a subdomain of a listed domain (bank.com covers online.bank.com). */
function isPrivate(domain, privateDomains) {
  return privateDomains.some((listed) => domain === listed || domain.endsWith("." + listed));
}

/**
 * Decide what to send for a page.
 * In:  the tab URL, its title, the private list.
 * Out: {domain, title} for normal websites, {category: "Private"} or {category: "Other"} otherwise.
 *      The full URL is never sent — only the domain.
 */
function describePage(url, title, privateDomains) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch (error) {
    return { category: "Other" };
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { category: "Other" };          // chrome://, new tab, extension pages, files
  }
  const domain = normaliseDomain(parsed.hostname);
  if (isPrivate(domain, privateDomains)) {
    return { category: "Private" };
  }
  return { domain: domain, title: title || "" };
}

/** Saved settings: pairing token, port, and the last known private list. */
async function getSettings() {
  return chrome.storage.local.get({ token: "", port: DEFAULT_PORT, privateDomains: [] });
}

/**
 * Send one request to the Commit app on this computer.
 * Out: {ok: true, data} on success; {ok: false, reason} with reason "not_paired", "wrong_token",
 *      "error" or "offline" otherwise. Never throws.
 */
async function callApp(method, path, body) {
  const settings = await getSettings();
  if (!settings.token) {
    return { ok: false, reason: "not_paired" };
  }
  const options = {
    method: method,
    headers: { "Content-Type": "application/json", "X-Commit-Token": settings.token },
  };
  if (body !== undefined) {
    options.body = JSON.stringify(body);
  }
  try {
    const response = await fetch(`http://127.0.0.1:${settings.port}${path}`, options);
    if (response.status === 401) {
      return { ok: false, reason: "wrong_token" };
    }
    if (!response.ok) {
      return { ok: false, reason: "error" };
    }
    return { ok: true, data: await response.json() };
  } catch (error) {
    return { ok: false, reason: "offline" };   // the app is not running
  }
}

// Let Node load this file for tests (in Chrome, `module` does not exist).
if (typeof module !== "undefined") {
  module.exports = { normaliseDomain, isPrivate, describePage };
}
