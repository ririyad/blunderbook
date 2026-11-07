// The demo extension's tab: your marks, with the entry each is on.

import { api } from "/js/api.js";
import { esc } from "/js/ui.js";
import { markLine } from "./parts.js";

export async function show(root) {
  const marks = await api("/api/ext/demo/marks");
  root.innerHTML = `<div class="demo"><ul>${marks.map((m) => `<li>${esc(markLine(m))}</li>`).join("")}</ul></div>`;
}
