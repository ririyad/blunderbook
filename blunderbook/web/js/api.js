// Calls to the local JSON API (CLAUDE.md §10). Errors come back as ApiError with the
// server's own message, ready to show.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/** GET (or `options.method`) `path`; returns the parsed JSON, or null for 204. */
export async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: { Accept: "application/json" } };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Can't reach Blunderbook. Is blunderbook serve still running?", 0);
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(message(data, response), response.status);
  return data;
}

function message(data, response) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) return detail.map((d) => d.msg).join(" ");
  return `The server answered ${response.status} ${response.statusText}.`.replace(" .", ".");
}
