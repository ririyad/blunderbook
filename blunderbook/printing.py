"""The A4 print page (CLAUDE.md §9 `print`, §11): entries laid out like the paper Blunder Log,
two per page, black and white, printed through the browser's print dialog.

`render()` fills `web/print.html` with the entries and inlines `web/css/print.css`, so the
file it gives works on its own, opened straight from disk. Boards are SVG from python-chess.
"""

import html
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Final

import chess
import chess.svg

from blunderbook.core import detect, timecontrol
from blunderbook.core.models import CAUSES, Color, Entry, Eval, Game, TimeControl

WEB: Final = Path(__file__).parent / "web"
PER_PAGE: Final = 2
MARKS: Final = {"blunder": "??", "mistake": "?", "inaccuracy": "?!"}
JUDGMENT: Final = {"blunder": "Blunder", "mistake": "Mistake", "inaccuracy": "Inaccuracy"}
SOURCE: Final = {
    "lichess": "Lichess",
    "chesscom": "Chess.com",
    "pgn": "PGN file",
    "otb": "Over the board",
    "fen": "FEN entry",
}
STATUS: Final = {"new": "Not re-tested yet", "solved": "Solved", "missed": "Missed again"}
LONGEST_NOTE: Final = 700  # characters of your notes that fit in a box; the rest is cut
BOARD_COLORS: Final = {
    "square light": "#ffffff",
    "square dark": "#bdbdbd",
    "margin": "#ffffff",
    "coord": "#1b1b1b",
    "inner border": "#1b1b1b",
    "outer border": "#ffffff",
}
ARROW: Final = "#1b1b1bcc"
_ENTRIES: Final = ("<!-- entries -->", "<!-- /entries -->")
_STYLESHEET: Final = '<link rel="stylesheet" href="css/print.css">'


def render(entries: Sequence[Entry], *, today: date) -> str:
    """The whole page, ready to save as one .html file."""
    page = (WEB / "print.html").read_text("utf-8")
    css = (WEB / "css" / "print.css").read_text("utf-8")
    start, end = page.index(_ENTRIES[0]), page.index(_ENTRIES[1]) + len(_ENTRIES[1])
    sheets = [entries[i : i + PER_PAGE] for i in range(0, len(entries), PER_PAGE)]
    body = _intro(len(entries), len(sheets), today) + "".join(
        '<div class="sheet">' + "".join(_entry(e) for e in sheet) + "</div>\n" for sheet in sheets
    )
    page = page[:start] + body + page[end:]
    return page.replace(_STYLESHEET, f"<style>\n{css}</style>")


def _intro(n: int, pages: int, today: date) -> str:
    entries = "1 entry" if n == 1 else f"{n} entries"
    sheets = "1 page" if pages == 1 else f"{pages} pages"
    return (
        '<div class="screen-only intro"><h1>Blunder Log</h1>'
        f"<p>{entries} \N{MIDDLE DOT} {sheets} \N{MIDDLE DOT} made {today.isoformat()}</p>"
        "<p>Print it from your browser on A4, in black and white. This note isn't printed.</p>"
        "</div>\n"
    )


def _entry(entry: Entry) -> str:
    b, g = entry.blunder, entry.game
    label = move_label(b.move_no, g.my_color) + b.played_san
    return f"""<article class="entry">
<header><h2>{_e(label)}{MARKS[b.judgment]} <span class="serif">{JUDGMENT[b.judgment]}</span></h2>
<div class="meta">Entry #{b.id}<br>{_e(_game_line(g))}</div></header>
<div class="top">
<div class="board">{board_svg(b.fen_before, b.played_uci, g.my_color)}</div>
<div class="facts">
<div class="pair">
<div class="box"><div class="k">I played</div><div class="v">{_e(label)}{MARKS[b.judgment]}</div>
<div class="line">{_e(b.refutation_san or "")}</div></div>
<div class="box"><div class="k">Best was</div>
<div class="v">{_e(move_label(b.move_no, g.my_color) + b.best_san)}</div>
<div class="line">{_e(b.best_line_san)}</div></div>
</div>
<dl class="grid">{_details(entry)}</dl>
</div>
</div>
<div class="causes">{_causes(entry)}</div>
<div class="write">
<section><h3>What I was thinking</h3>{_note(b.thinking)}</section>
<section><h3>Lesson</h3>{_note(b.lesson)}</section>
</div>
<div class="retest"><span>Re-tested on <span class="blank"></span>
&nbsp; \N{BALLOT BOX} Solved &nbsp; \N{BALLOT BOX} Missed again</span>
<span class="status">{_e(_schedule(entry))}</span></div>
</article>
"""


def move_label(move_no: int, color: str) -> str:
    """``6. `` for White, ``6... `` for Black."""
    return f"{move_no}. " if color == "white" else f"{move_no}... "


def board_svg(fen: str, played_uci: str, my_color: str) -> str:
    """The position before your move, from your side, with your move as an arrow."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(played_uci)
    return chess.svg.board(
        board,
        orientation=my_color == "white",
        arrows=[chess.svg.Arrow(move.from_square, move.to_square, color=ARROW)],
        coordinates=True,
        colors=BOARD_COLORS,
    )


def _game_line(g: Game) -> str:
    players = f"{g.white or '?'}{_elo(g.white_elo)} vs {g.black or '?'}{_elo(g.black_elo)}"
    return " \N{MIDDLE DOT} ".join([players, g.played_on.isoformat() if g.played_on else "—"])


def _elo(elo: int | None) -> str:
    return "" if elo is None else f" ({elo})"


def _details(entry: Entry) -> str:
    b, g = entry.blunder, entry.game
    me = g.my_color
    them: Color = "black" if me == "white" else "white"
    before_pct = round(100 * detect.chances(b.eval_before, me, me))  # you were to move
    after_pct = round(100 * detect.chances(b.eval_after, them, me))
    rows = [
        ("Source", g.site_label or SOURCE[g.source]),
        ("You played", me.capitalize()),
        ("Time control", time_control(g) or "—"),
        ("Result", result(g) or "—"),
        ("Opening", " ".join(x for x in (g.eco, g.opening) if x) or "—"),
        ("Eval", f"{fmt_eval(b.eval_before)} \N{RIGHTWARDS ARROW} {fmt_eval(b.eval_after)}"),
        ("Your chances", f"{before_pct}% \N{RIGHTWARDS ARROW} {after_pct}%"),
        ("Clock left", fmt_clock(b.clock_left_s) or "—"),
        ("Time on move", fmt_spent(b.time_spent_s) or "—"),
    ]
    return "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in rows)


def _causes(entry: Entry) -> str:
    b = entry.blunder
    out = []
    for cause in CAUSES:
        ticked = cause in b.causes
        tick = "\N{BALLOT BOX WITH X}" if ticked else "\N{BALLOT BOX}"
        text = _e(cause)
        if cause == "Other" and ticked and b.other_cause:
            text += f": {_e(b.other_cause)}"
        if not ticked and not b.causes and cause in b.auto_causes:
            text += ' <span class="sugg">(suggested)</span>'
        out.append(f'<div><span class="tick">{tick}</span>{text}</div>')
    return "".join(out)


def _note(text: str) -> str:
    text = text.strip()
    if not text:  # lines to write on
        return '<div class="rule"></div>' * 4
    if len(text) > LONGEST_NOTE:
        text = text[:LONGEST_NOTE].rstrip() + " \N{HORIZONTAL ELLIPSIS}"
    return f'<div class="text">{_e(text)}</div>'


def _schedule(entry: Entry) -> str:
    b = entry.blunder
    parts = [STATUS[b.status]]
    if b.status == "solved" and b.streak > 1:
        parts.append(f"{b.streak} in a row")
    parts.append(f"next due {b.due_on.isoformat()}")
    return " \N{MIDDLE DOT} ".join(parts)


def time_control(g: Game) -> str | None:
    """``Blitz 3+2``, ``3+2`` without a speed, or None."""
    if g.tc_base_s is None or g.tc_inc_s is None:
        return None
    label = timecontrol.label(TimeControl(g.tc_base_s, g.tc_inc_s))
    return f"{g.speed.capitalize()} {label}" if g.speed else label


def result(g: Game) -> str | None:
    """``Loss (0-1)`` from your side, or None when it isn't known."""
    if g.result == "1/2-1/2":
        return "Draw (1/2-1/2)"
    if g.result in ("1-0", "0-1"):
        won = (g.result == "1-0") == (g.my_color == "white")
        return f"{'Win' if won else 'Loss'} ({g.result})"
    return None


def fmt_eval(score: Eval) -> str:
    """White's point of view, as the Log shows it: ``+0.36``, ``-M2`` (a minus sign), ``#``."""
    if score.mate is not None:
        if score.mate == 0:
            return "#"
        return ("+" if score.mate > 0 else "\N{MINUS SIGN}") + f"M{abs(score.mate)}"
    assert score.cp is not None
    value = score.cp / 100
    sign = "+" if value > 0 else "\N{MINUS SIGN}" if value < 0 else ""
    return f"{sign}{abs(value):.2f}"


def fmt_clock(seconds: float | None) -> str | None:
    """``6:42``, ``1:30:00``."""
    if seconds is None:
        return None
    t = round(seconds)
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_spent(seconds: float | None) -> str | None:
    """``1.2 s``, ``15 s``."""
    if seconds is None:
        return None
    return f"{round(seconds, 1):g} s" if seconds < 10 else f"{round(seconds)} s"


def _e(text: str) -> str:
    return html.escape(text, quote=True)
