// A board you play moves on (ROADMAP 19.4): tap a piece, then a square. Each move is checked
// by the server (`POST /board`, python-chess), which sends back the position, the SAN and
// what can be played next, so there's no chess logic here. A pawn that reaches the last rank
// becomes a queen, as in Re-test.
//
//   const p = player({ board: el, orient: () => "white", changed: () => ... });
//   await p.reset(fen);        // start again from a position
//   p.state                    // the server's answer: {start, moves, fen, legal, line, pgn, over}
//   p.at                       // the move shown (0 is the start); p.go(n) shows another
//   await p.takeBack();

import { api } from "/js/api.js";
import { renderBoard, sqIdx, sqName } from "/js/board.js";

const BOARD = "/api/ext/journal/board";

export function player({ board, orient, changed, failed }) {
  let start = null;
  let played = []; // UCI
  let state = null; // the answer for every move played
  let legal = []; // the moves from the position shown
  let at = 0;
  let selected = null;
  let mine = 0; // only the newest answer counts

  async function ask(list) {
    const asked = ++mine;
    const answer = await api(BOARD, { method: "POST", body: { fen: start, moves: list } });
    return asked === mine ? answer : null;
  }

  async function settle(list, shown) {
    let answer;
    try {
      answer = await ask(list);
    } catch (err) {
      failed(err.message);
      return;
    }
    if (!answer) return;
    played = list;
    state = answer;
    at = shown;
    selected = null;
    legal = at === played.length ? answer.legal : null;
    draw();
    changed();
  }

  const fenAt = (i) => (i === 0 ? state.start : state.moves[i - 1].fen);

  function draw() {
    if (!state) return;
    const hl = {};
    if (at > 0) {
      const last = state.moves[at - 1].uci;
      hl[sqIdx(last.slice(0, 2))] = hl[sqIdx(last.slice(2, 4))] = "sel";
    }
    if (selected !== null) hl[selected] = "sel";
    const from = selected === null ? null : sqName(selected);
    const targets = from && legal ? [...new Set(legal.filter((m) => m.startsWith(from)).map((m) => sqIdx(m.slice(2, 4))))] : [];
    renderBoard(board, fenAt(at), orient(), { hl, targets, onClick: tap });
  }

  async function tap(i) {
    if (!state) return;
    if (legal === null) {
      // Shown after stepping back: ask what can be played here first.
      const answer = await ask(played.slice(0, at)).catch((err) => { failed(err.message); return null; });
      if (!answer) return;
      legal = answer.legal;
    }
    const square = sqName(i);
    if (selected !== null) {
      const moves = legal.filter((m) => m.slice(0, 4) === sqName(selected) + square);
      if (moves.length) {
        const move = moves.find((m) => m.endsWith("q")) || moves[0];
        await settle([...played.slice(0, at), move], at + 1);
        return;
      }
    }
    selected = legal.some((m) => m.startsWith(square)) && i !== selected ? i : null;
    draw();
  }

  return {
    get state() { return state; },
    get at() { return at; },
    get played() { return played.slice(0, at); },
    /** The position shown, as a FEN. */
    get fen() { return state ? fenAt(at) : start; },
    reset(fen, moves = []) {
      start = fen;
      return settle(moves, moves.length);
    },
    takeBack() {
      return at > 0 ? settle(played.slice(0, at - 1), at - 1) : Promise.resolve();
    },
    /** Show move `i` of the line played (0 is the start). */
    go(i) {
      at = Math.max(0, Math.min(played.length, i));
      selected = null;
      legal = at === played.length ? state.legal : null;
      draw();
      changed();
    },
    draw,
  };
}
