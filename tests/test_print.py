"""The A4 print page (CLAUDE.md §9 `print`, §11): `printing.render()` and the `print` command,
against the Log tests' entries in a temp database."""

import re
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_api_blunders import NOW, elephant, fen_entry, scholars, sql
from typer.testing import CliRunner

from blunderbook import config, printing
from blunderbook.cli import app
from blunderbook.core.models import CAUSES, Entry, Eval
from blunderbook.db import connection, repo

runner = CliRunner()
TODAY = date.today()
BOX, TICKED = "\N{BALLOT BOX}", "\N{BALLOT BOX WITH X}"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    return path


@pytest.fixture
def ids(db_file: Path) -> dict[str, int]:
    """The Elephant (6. Nxd5??), Scholar's mate (3... Nf6??) and a FEN entry (32. Rc7??)."""
    made: dict[str, int] = {}
    with closing(connection.open_db(db_file, create=True)) as conn:
        for minutes, (name, make) in enumerate(
            (("elephant", elephant), ("scholars", scholars), ("fen", fen_entry))
        ):
            game, blunder = make()
            saved = repo.add_game(conn, game, [blunder], now=NOW + timedelta(minutes=minutes))
            assert saved is not None
            made[name] = saved.blunder_ids[0]
    return made


def entries(db_file: Path, *blunder_ids: int) -> list[Entry]:
    with closing(connection.open_db(db_file)) as conn:
        found = [repo.get_entry(conn, i) for i in blunder_ids]
    assert all(e is not None for e in found)
    return [e for e in found if e is not None]


def notes(db_file: Path, blunder_id: int, **fields: Any) -> None:
    with closing(connection.open_db(db_file)) as conn:
        assert repo.update_notes(conn, blunder_id, **fields) is not None


def articles(page: str) -> list[str]:
    return re.findall(r'<article class="entry">.*?</article>', page, re.DOTALL)


# ---------------------------------------------------------------- render


def test_two_entries_per_page(ids: dict[str, int], db_file: Path) -> None:
    page = printing.render(entries(db_file, *ids.values()), today=date(2026, 11, 6))
    sheets = page.split('<div class="sheet">')[1:]
    assert [len(articles(s)) for s in sheets] == [2, 1]
    assert "3 entries \N{MIDDLE DOT} 2 pages \N{MIDDLE DOT} made 2026-11-06" in page


def test_the_page_stands_alone(ids: dict[str, int], db_file: Path) -> None:
    """Opened straight from disk: the CSS is inlined, nothing loads from elsewhere."""
    page = printing.render(entries(db_file, ids["elephant"]), today=TODAY)
    assert page.startswith("<!DOCTYPE html>")
    assert "<style>" in page and "@page { size: A4; margin: 10mm; }" in page
    assert 'href="css/print.css"' not in page
    assert 'href="favicon.svg"' not in page and 'href="data:image/svg+xml;base64,' in page
    assert "<!-- entries -->" not in page and "filled in by" not in page
    assert "<script" not in page
    urls = set(re.findall(r"(?:https?:)?//[\w.-]+\.\w+", page)) - {"http://www.w3.org"}
    assert not urls


def test_an_entry_has_the_paper_logs_parts(ids: dict[str, int], db_file: Path) -> None:
    (entry,) = articles(printing.render(entries(db_file, ids["elephant"]), today=TODAY))
    assert "<h2>6. Nxd5?? <span" in entry
    assert f"Entry #{ids['elephant']}" in entry
    assert "Rashed (1512) vs Karim S. (1498) \N{MIDDLE DOT} 2026-10-12" in entry
    assert "I played" in entry and "Best was" in entry and "6. e3" in entry
    assert "<dt>Time control</dt><dd>Blitz 3+2</dd>" in entry
    assert "<dt>Result</dt><dd>Loss (0-1)</dd>" in entry
    assert "<dt>Eval</dt><dd>+0.36 \N{RIGHTWARDS ARROW} \N{MINUS SIGN}4.09</dd>" in entry
    assert "What I was thinking" in entry and "Lesson" in entry
    assert "Re-tested on" in entry and f"{BOX} Solved" in entry and f"{BOX} Missed again" in entry
    assert "Not re-tested yet \N{MIDDLE DOT} next due" in entry
    assert entry.count('class="rule"') == 8  # no notes yet: lines to write on, in both boxes
    assert "<svg" in entry


def test_a_missed_win_has_its_word_and_no_mark(ids: dict[str, int], db_file: Path) -> None:
    with closing(connection.connect(db_file)) as conn:
        conn.execute("UPDATE blunders SET judgment = 'missed' WHERE id = ?", (ids["elephant"],))
    (entry,) = articles(printing.render(entries(db_file, ids["elephant"]), today=TODAY))
    assert '<h2>6. Nxd5 <span class="serif">Missed win</span></h2>' in entry
    assert "Nxd5?" not in entry


def test_causes_in_the_fixed_order_ticked_and_suggested(ids: dict[str, int], db_file: Path) -> None:
    (unconfirmed,) = articles(printing.render(entries(db_file, ids["scholars"]), today=TODAY))
    shown = re.findall(r'<span class="tick">(.)</span>([^<]+)', unconfirmed)
    assert [c.strip() for _, c in shown] == list(CAUSES)
    assert {t for t, _ in shown} == {BOX}
    assert 'Missed their threat <span class="sugg">(suggested)</span>' in unconfirmed

    notes(db_file, ids["scholars"], causes=["Moved too fast", "Other"], other_cause="Tired")
    (confirmed,) = articles(printing.render(entries(db_file, ids["scholars"]), today=TODAY))
    assert f'<span class="tick">{TICKED}</span>Moved too fast' in confirmed
    assert f'<span class="tick">{TICKED}</span>Other: Tired' in confirmed
    assert "(suggested)" not in confirmed  # once you confirm causes, suggestions step back


def test_your_text_is_escaped_and_kept(ids: dict[str, int], db_file: Path) -> None:
    notes(
        db_file,
        ids["elephant"],
        thinking="</div><script>alert(1)</script>",
        lesson="Check Bb4+ & every capture.\nThen move.",
    )
    (entry,) = articles(printing.render(entries(db_file, ids["elephant"]), today=TODAY))
    assert "<script>" not in entry
    assert "&lt;/div&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in entry
    assert "Check Bb4+ &amp; every capture.\nThen move." in entry  # pre-wrap keeps the break
    assert entry.count('class="rule"') == 0


def test_long_notes_are_cut_to_fit(ids: dict[str, int], db_file: Path) -> None:
    notes(db_file, ids["elephant"], lesson="word " * 400)
    (entry,) = articles(printing.render(entries(db_file, ids["elephant"]), today=TODAY))
    lesson = re.search(r'<h3>Lesson</h3><div class="text">(.*?)</div>', entry, re.DOTALL)
    assert lesson is not None
    assert len(lesson[1]) <= printing.LONGEST_NOTE + 2
    assert lesson[1].endswith("\N{HORIZONTAL ELLIPSIS}")


def test_missing_data_shows_a_dash(ids: dict[str, int], db_file: Path) -> None:
    (entry,) = articles(printing.render(entries(db_file, ids["fen"]), today=TODAY))
    assert "<dt>Clock left</dt><dd>—</dd>" in entry
    assert "<dt>Time control</dt><dd>—</dd>" in entry


def test_the_board_faces_your_side(ids: dict[str, int], db_file: Path) -> None:
    white = printing.board_svg(
        "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6", "c3d5", "white"
    )
    black = printing.board_svg(
        "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6", "c3d5", "black"
    )
    assert white != black
    assert 'class="arrow"' in white
    assert "#ffce9e" not in white and "#d18b47" not in white  # black and white, not brown


@pytest.mark.parametrize(
    ("score", "text"),
    [
        (Eval(cp=36), "+0.36"),
        (Eval(cp=-409), "\N{MINUS SIGN}4.09"),
        (Eval(cp=0), "0.00"),
        (Eval(mate=2), "+M2"),
        (Eval(mate=-1), "\N{MINUS SIGN}M1"),
        (Eval(mate=0), "#"),
    ],
)
def test_fmt_eval(score: Eval, text: str) -> None:
    assert printing.fmt_eval(score) == text


def test_clock_and_time_spent() -> None:
    assert printing.fmt_clock(402) == "6:42"
    assert printing.fmt_clock(5400) == "1:30:00"
    assert printing.fmt_clock(None) is None
    assert printing.fmt_spent(1.24) == "1.2 s"
    assert printing.fmt_spent(14.6) == "15 s"
    assert printing.fmt_spent(None) is None


# ---------------------------------------------------------------- the command


def test_print_all_entries(
    tmp_path: Path, cfg_file: Path, ids: dict[str, int], db_file: Path
) -> None:
    out = tmp_path / "log.html"
    result = runner.invoke(app, ["print", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert f"Wrote 3 entries (2 pages) to {out}" in result.output
    assert "Open it in your browser and print it on A4." in result.output
    page = out.read_text("utf-8")
    labels = re.findall(r"<h2>([^<]+?) <span", page)
    assert labels == ["32. Rc7??", "3... Nf6??", "6. Nxd5??"]  # the Log's order: newest first
    assert not list(tmp_path.glob("*.partial"))


def test_print_ids_in_the_order_given(
    tmp_path: Path, cfg_file: Path, ids: dict[str, int], db_file: Path
) -> None:
    out = tmp_path / "two.html"
    chosen = f"{ids['elephant']}, {ids['fen']},{ids['elephant']}"
    result = runner.invoke(app, ["print", "--ids", chosen, "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "Wrote 2 entries (1 page)" in result.output
    assert re.findall(r"<h2>([^<]+?) <span", out.read_text("utf-8")) == ["6. Nxd5??", "32. Rc7??"]


def test_print_due(tmp_path: Path, cfg_file: Path, ids: dict[str, int], db_file: Path) -> None:
    later = (TODAY + timedelta(days=3)).isoformat()
    sql(db_file, "UPDATE blunders SET due_on = ? WHERE id <> ?", later, ids["scholars"])
    out = tmp_path / "due.html"
    result = runner.invoke(app, ["print", "--due", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "Wrote 1 entry (1 page)" in result.output
    assert re.findall(r"<h2>([^<]+?) <span", out.read_text("utf-8")) == ["3... Nf6??"]

    sql(db_file, "UPDATE blunders SET due_on = ?", later)
    result = runner.invoke(app, ["print", "--due", "--out", str(out)])
    assert result.exit_code == 1
    assert "Nothing is due for a re-test." in result.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--ids", "1", "--due"], "Use --ids or --due, not both."),
        (["--ids", "one,2"], "--ids takes entry numbers separated by commas, e.g. --ids 3,12."),
        (["--ids", " , "], "--ids takes entry numbers separated by commas"),
        (["--ids", "999"], "No entry #999. Nothing was written."),
    ],
)
def test_print_refuses(
    tmp_path: Path, cfg_file: Path, ids: dict[str, int], args: list[str], message: str
) -> None:
    out = tmp_path / "log.html"
    result = runner.invoke(app, ["print", *args, "--out", str(out)])
    assert result.exit_code == 1
    assert message in result.output
    assert not out.exists()


def test_print_needs_out(cfg_file: Path, ids: dict[str, int]) -> None:
    assert runner.invoke(app, ["print"]).exit_code == 2


def test_print_without_a_database(tmp_path: Path, cfg_file: Path, db_file: Path) -> None:
    result = runner.invoke(app, ["print", "--out", str(tmp_path / "log.html")])
    assert result.exit_code == 1
    assert "Nothing to print yet: import a PGN first" in result.output
    assert not db_file.exists()  # printing never creates one


def test_print_with_no_entries(tmp_path: Path, cfg_file: Path, db_file: Path) -> None:
    with closing(connection.open_db(db_file, create=True)):
        pass
    result = runner.invoke(app, ["print", "--out", str(tmp_path / "log.html")])
    assert result.exit_code == 1
    assert "No entries to print yet." in result.output


def test_print_into_a_missing_folder(tmp_path: Path, cfg_file: Path, ids: dict[str, int]) -> None:
    out = tmp_path / "nope" / "log.html"
    result = runner.invoke(app, ["print", "--out", str(out)])
    assert result.exit_code == 1
    assert f"There's no folder {out.parent}. Nothing was written." in result.output


def test_print_replaces_an_older_page(tmp_path: Path, cfg_file: Path, ids: dict[str, int]) -> None:
    out = tmp_path / "log.html"
    out.write_text("old", "utf-8")
    assert runner.invoke(app, ["print", "--out", str(out)]).exit_code == 0
    assert out.read_text("utf-8").startswith("<!DOCTYPE html>")
