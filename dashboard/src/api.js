// dashboard/src/api.js — the only place that talks to the Commit app's local API (README section 14).
//
// Every request carries the pairing token, which the Commit app put into the page as
// <meta name="commit-token">. In `npm run dev` there is no token in the page; Vite's proxy adds it.

const tokenTag = document.querySelector('meta[name="commit-token"]');
const TOKEN = tokenTag ? tokenTag.content : "";

/** Headers for every request (JSON + the pairing token, when we have one). */
function headers(withBody) {
  const result = {};
  if (TOKEN) result["X-Commit-Token"] = TOKEN;
  if (withBody) result["Content-Type"] = "application/json";
  return result;
}

/** Turn a failed response into an Error with the server's friendly message. */
async function errorFrom(response) {
  let message = `Request failed (${response.status}).`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail)) message = "Please check the values you entered.";
  } catch {
    // the body was not JSON; keep the generic message
  }
  return new Error(message);
}

/**
 * Call the API.
 * In:  HTTP method, path such as "/api/today", optional JSON body.
 * Out: the parsed JSON response. Throws an Error with a readable message on failure.
 */
export async function api(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: headers(body !== undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Commit is not running. Start it with `python -m agent.main` and reload this page.");
  }
  if (!response.ok) throw await errorFrom(response);
  return response.json();
}

/** Download the weekly PDF (fetched with the token header, then saved via a temporary link). */
export async function downloadWeeklyPdf(start) {
  const query = start ? `?start=${start}` : "";
  const response = await fetch(`/api/report/pdf${query}`, { headers: headers(false) });
  if (!response.ok) throw await errorFrom(response);
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `commit-week-${start || "last-7-days"}.pdf`;
  link.click();
  URL.revokeObjectURL(link.href);
}
