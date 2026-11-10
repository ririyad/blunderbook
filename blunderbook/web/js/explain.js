// The optional AI explanation (CLAUDE.md §7.10, §11), shared by the Log and the Re-test
// result. It shows a saved explanation, and when AI is on, a button to ask for one and
// "What's sent": the exact text that goes to OpenRouter, loaded when you open it.
//
// Nothing is sent until the button is pressed. With AI off and nothing saved, it shows
// nothing at all.

import { api } from "./api.js";
import { JUDGMENT_WORD, fmtDate, localDay } from "./format.js";
import { esc } from "./ui.js";

/** Fill `box` for entry `id`. `saved` is the entry's explanation or null; `judgment` names
 *  the button ("Explain this blunder"). */
export async function showExplanation(box, id, saved, judgment) {
  let ai = { enabled: false, model: null };
  try {
    ai = await api("/api/ai"); // read each time: `blunderbook ai on` needs no restart
  } catch {
    // Settings can't be read: show what's saved, without the button.
  }
  draw(box, { id, saved, judgment, ai });
}

function draw(box, state) {
  const { saved, ai } = state;
  if (!saved && !ai.enabled) {
    box.replaceChildren();
    return;
  }
  const label = saved ? "Explain again" : `Explain this ${JUDGMENT_WORD[state.judgment] || "move"}`;
  const actions = ai.enabled
    ? `<div class="ai-row">
         <button class="btn ghost ai-ask" type="button">${esc(label)}</button>
         <details class="ai-sent"><summary>What's sent</summary><div class="ai-prompt small">Loading…</div></details>
       </div>`
    : "";
  box.innerHTML = (saved ? savedHtml(saved) : "")
    + actions
    + '<div class="small ai-msg" aria-live="polite"></div>';
  box.querySelector(".ai-ask")?.addEventListener("click", () => ask(box, state));
  const sent = box.querySelector(".ai-sent");
  sent?.addEventListener("toggle", () => {
    if (sent.open && !sent.dataset.loaded) loadPrompt(sent, state.id);
  });
}

function savedHtml(saved) {
  const paragraphs = saved.text.split(/\n\s*\n/).map((p) => `<p>${esc(p.trim())}</p>`).join("");
  const when = fmtDate(localDay(saved.created_at));
  return `<div class="ai-box">
    <div class="ai-k">AI explanation <span class="auto">auto</span></div>
    ${paragraphs}
    <p class="small">Written by ${esc(saved.model)}${when ? " on " + esc(when) : ""}, from Stockfish's lines. It can be wrong: the lines themselves are the engine's.</p>
  </div>`;
}

async function loadPrompt(details, id) {
  const out = details.querySelector(".ai-prompt");
  try {
    const prompt = await api(`/api/blunders/${id}/explanation/prompt`);
    details.dataset.loaded = "1";
    out.innerHTML = `<p>Sent to OpenRouter and ${esc(prompt.model || "your model")}, and nothing else: no names, ratings or notes of yours.</p>
      <div class="lbl">Instructions</div><pre>${esc(prompt.system)}</pre>
      <div class="lbl">About this move</div><pre>${esc(prompt.user)}</pre>`;
  } catch (err) {
    out.textContent = "Couldn't load it: " + err.message;
  }
}

async function ask(box, state) {
  const button = box.querySelector(".ai-ask");
  const msg = box.querySelector(".ai-msg");
  button.disabled = true;
  msg.classList.remove("fail");
  msg.textContent = `Asking ${state.ai.model}… This can take a few seconds.`;
  try {
    const saved = await api(`/api/blunders/${state.id}/explanation`, { method: "POST" });
    state.saved = saved;
    draw(box, state);
    box.querySelector(".ai-msg").textContent = "Saved.";
  } catch (err) {
    button.disabled = false;
    msg.classList.add("fail");
    msg.textContent = "No explanation: " + err.message;
  }
}
