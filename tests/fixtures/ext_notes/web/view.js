// The sample "notes" extension's tab (tests/ext_samples.py). It uses the host's page
// modules by absolute path, as a real extension does.

import { api } from "/js/api.js";
import { esc } from "/js/ui.js";

export async function show(root, rest) {
  const notes = await api("/api/ext/notes/notes");
  const log = await api("/api/ext/notes/log");
  root.innerHTML = `<div class="notes-ext">
    <p>${log.entries} entries in your Log.${rest ? " Open: " + esc(rest) : ""}</p>
    <ul>${notes.map((n) => `<li>${esc(n.text)}</li>`).join("")}</ul>
  </div>`;
}
