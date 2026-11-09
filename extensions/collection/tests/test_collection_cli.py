"""The Collection's commands (ROADMAP 12.1): `blunderbook collection import FILE --into NAME`
and `list`, on their own and through `blunderbook` with the extension turned on."""

from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from blunderbook_collection import commands, extension, store
from collection_fakes import (  # noqa: F401  (fixtures)
    CLASSICS,
    FakeEngine,
    cfg_file,
    fake,
    no_engine,
)
from typer.testing import CliRunner

from blunderbook import cli, config, ext, host
from blunderbook.db import connection

runner = CliRunner()
DOT = "\N{MIDDLE DOT}"
MORPHY = "Paul Morphy vs Duke Karl / Count Isouard"


@pytest.fixture
def restore_commands() -> Iterator[None]:
    groups = list(cli.app.registered_groups)
    yield
    cli.app.registered_groups[:] = groups


def import_(*args: str) -> tuple[int, str]:
    result = runner.invoke(commands, ["import", *args])
    return result.exit_code, result.output


def test_import(fake: FakeEngine) -> None:
    code, out = import_(str(CLASSICS), "--into", "Classics", "--depth", "8")
    assert code == 0, out
    assert out == (
        "Analysing with Stockfish 17.1 at depth 8.\n"
        f"Game 1 {DOT} {MORPHY} {DOT} added\n"
        f"Game 2 {DOT} Kermur de Legal vs Saint Brie {DOT} added\n"
        f"Game 3 {DOT} A vs B {DOT} Illegal move 2. Ke3\n"
        f"Game 4 {DOT} {MORPHY} {DOT} Same game as game 1 \N{EM DASH} skipped\n"
        "New collection: Classics.\n"
        f"4 games read {DOT} 2 added {DOT} 1 skipped {DOT} 1 error\n"
        "Classics: 2 games.\n"
    )


def test_import_again_and_into_another(fake: FakeEngine) -> None:
    import_(str(CLASSICS), "--into", "Classics")
    code, out = import_(str(CLASSICS), "--into", "classics")
    assert code == 0, out
    assert "Analysing" not in out  # nothing new to analyse
    assert f"Game 1 {DOT} {MORPHY} {DOT} Already in Classics \N{EM DASH} skipped\n" in out
    assert out.endswith(
        f"4 games read {DOT} 0 added {DOT} 3 skipped {DOT} 1 error\nClassics: 2 games.\n"
    )
    code, out = import_(str(CLASSICS), "--into", "Morphy")
    assert f"Game 1 {DOT} {MORPHY} {DOT} added (already analysed)\n" in out
    assert "New collection: Morphy.\n" in out
    assert fake.opened == 1


def test_the_default_depth_is_engine_depth(fake: FakeEngine, cfg_file: Path) -> None:
    config.save(
        config.Config(engine_depth=11, extensions=config.ExtensionsConfig(enabled=("collection",))),
        cfg_file,
    )
    _, out = import_(str(CLASSICS), "--into", "Classics")
    assert out.startswith("Analysing with Stockfish 17.1 at depth 11.\n")


def test_no_stockfish(no_engine: None) -> None:
    code, out = import_(str(CLASSICS), "--into", "Classics")
    assert code == 1
    assert f"Game 1 {DOT} {MORPHY} {DOT} not analysed\n" in out
    assert f"4 games read {DOT} 0 added {DOT} 1 skipped {DOT} 1 error {DOT} 2 not analysed\n" in out
    assert out.endswith(
        "Analysis stopped: Can't analyse: Stockfish wasn't found.\n"
        "Import the file again to analyse the rest. Games already added are skipped.\n"
    )
    with closing(host.open_db(extension)) as conn:
        assert store.collections(conn) == []


def test_the_engine_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "engine", FakeEngine(fail_on=40))
    code, out = import_(str(CLASSICS), "--into", "Classics")
    assert code == 1
    assert f"Game 2 {DOT} Kermur de Legal vs Saint Brie {DOT} not analysed\n" in out
    assert "Classics: 1 game.\nAnalysis stopped: Stockfish stopped unexpectedly.\n" in out


def test_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "engine", FakeEngine(fail_on=40, interrupt=True))
    code, out = import_(str(CLASSICS), "--into", "Classics")
    assert code == 130
    assert out.endswith(
        "Classics: 1 game.\n"
        "Stopped. The games added so far are kept: import the file again to finish.\n"
    )


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        (["missing.pgn", "--into", "C"], "Can't read missing.pgn"),
        (["FILE", "--into", "  "], "Give the collection a name."),
        (["EMPTY", "--into", "C"], "No games found in"),
    ],
)
def test_import_problems(tmp_path: Path, fake: FakeEngine, args: list[str], problem: str) -> None:
    empty = tmp_path / "empty.pgn"
    empty.write_text("\n", "utf-8")
    swap = {"FILE": str(CLASSICS), "EMPTY": str(empty)}
    code, out = import_(*[swap.get(a, a) for a in args])
    assert code == 1
    assert problem in out
    assert fake.opened == 0


def test_a_windows_1252_file(tmp_path: Path, fake: FakeEngine) -> None:
    path = tmp_path / "cp1252.pgn"
    path.write_bytes('[White "Réti"]\n[Black "Tartakower"]\n\n1. e4 c6 *\n'.encode("cp1252"))
    code, out = import_(str(path), "--into", "Vienna")
    assert code == 0, out
    assert out.startswith("Read as Windows-1252 (the file isn't UTF-8).\n")
    assert f"Game 1 {DOT} Réti vs Tartakower {DOT} added\n" in out


def test_list(fake: FakeEngine) -> None:
    empty = runner.invoke(commands, ["list"])
    assert empty.output == (
        "No collections yet. Add games with: blunderbook collection import FILE --into NAME\n"
    )
    import_(str(CLASSICS), "--into", "Classics")
    import_(str(CLASSICS), "--into", "Adults")
    assert runner.invoke(commands, ["list"]).output == (
        f"Adults {DOT} 2 games\nClassics {DOT} 2 games\n"
    )
    games = runner.invoke(commands, ["list", "classics"])
    assert games.exit_code == 0
    assert games.output == (
        f"Classics {DOT} 2 games\n"
        f"  #1 {MORPHY} {DOT} 1-0 {DOT} Paris {DOT} 1858.??.?? {DOT} C41 Philidor Defence "
        f"{DOT} 17 moves\n"
        f"  #2 Kermur de Legal vs Saint Brie {DOT} 1-0 {DOT} Paris {DOT} 1750.??.?? {DOT} C41 "
        f"{DOT} 7 moves\n"
    )
    missing = runner.invoke(commands, ["list", "Nope"])
    assert (missing.exit_code, missing.output) == (1, "No collection called Nope.\n")


def test_through_blunderbook(fake: FakeEngine, cfg_file: Path, restore_commands: None) -> None:
    config.save(config.Config(), cfg_file)
    on = runner.invoke(cli.app, ["ext", "enable", "collection"])
    assert on.exit_code == 0, on.output
    assert on.output.startswith("Turned on collection (Collection).\n")
    cli.add_extension_commands()
    result = runner.invoke(cli.app, ["collection", "import", str(CLASSICS), "--into", "C"])
    assert result.exit_code == 0, result.output
    assert "2 added" in result.output
    assert ext.db_path(extension).exists()


def test_collection_db_is_backed_up(fake: FakeEngine, cfg_file: Path) -> None:
    with closing(connection.open_db(config.db_path(), create=True)):
        pass
    import_(str(CLASSICS), "--into", "Classics")
    done = runner.invoke(cli.app, ["backup"])
    assert done.exit_code == 0, done.output
    folder = config.backup_folder(config.load(cfg_file))
    assert any(p.name.startswith("collection-") for p in folder.iterdir())


@pytest.mark.engine
def test_with_stockfish() -> None:
    """Légal's game at depth 8: after 5... Bxd1 White mates in two, and the end is mate."""
    try:
        with host.engine():
            pass
    except host.HostError as exc:
        pytest.skip(str(exc))
    code, out = import_(str(CLASSICS), "--into", "Classics", "--depth", "8")
    assert code == 0, out
    with closing(host.open_db(extension)) as conn:
        found = store.find(conn, "Classics")
        assert found is not None
        legal = store.games(conn, found.id)[1]
        kept = store.positions(conn, legal.id)
    after_bxd1 = kept[10]
    assert after_bxd1.move_san == "Bxd1"
    assert after_bxd1.score.mate is not None and after_bxd1.score.mate > 0
    assert after_bxd1.best_uci == "c4f7"  # 6. Bxf7+
    assert kept[-1].score.mate == 0 and kept[-1].best_uci is None


# ---------------------------------------------------------------- stats and players (12.2)


def stats_(*args: str) -> tuple[int, str]:
    result = runner.invoke(commands, ["stats", *args])
    return result.exit_code, result.output


def test_stats(fake: FakeEngine) -> None:
    import_(str(CLASSICS), "--into", "Classics")
    code, out = stats_("classics")
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == f"Classics {DOT} 2 games {DOT} White won 2 {DOT} drawn 0 {DOT} Black won 0"
    assert lines[2].split() == ["Games", "Moves", "Accuracy", "ACPL", "??", "?", "?!"]
    assert lines[3].split() == ["White", "2", "24", "100.0", "0", "0", "0", "0"]
    assert lines[4].split() == ["Black", "2", "22", "100.0", "0", "0", "0", "0"]
    assert "By phase (both sides' moves; the endgame is six pieces or fewer)" in lines
    assert f"#1 {MORPHY}" in out and "clean \N{MIDDLE DOT} clean" in out
    assert "C41 Philidor Defence" in out


def test_stats_of_a_player(fake: FakeEngine) -> None:
    import_(str(CLASSICS), "--into", "Classics")
    code, out = stats_("Classics", "--player", "paul  MORPHY", "--phase", "opening")
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == f"Classics {DOT} 1 game {DOT} won 1 {DOT} drawn 0 {DOT} lost 0"
    assert lines[1] == "Only: the opening"
    assert lines[4].split()[:4] == ["Paul", "Morphy", "1", "10"]  # moves 1 to 10
    assert lines[5].split()[:3] == ["Opponents", "1", "10"]
    assert "As White: C41 Philidor Defence" in out


def test_stats_of_every_collection(fake: FakeEngine) -> None:
    import_(str(CLASSICS), "--into", "Classics")
    import_(str(CLASSICS), "--into", "Again")
    _, out = stats_("--color", "black", "--opening", "C41")
    assert out.splitlines()[:2] == [
        f"All collections {DOT} 2 games {DOT} White won 2 {DOT} drawn 0 {DOT} Black won 0",
        f"Only: Black's moves {DOT} opening C41",
    ]


def test_stats_problems(fake: FakeEngine) -> None:
    import_(str(CLASSICS), "--into", "Classics")
    assert stats_("Classics", "--result", "won") == (
        1,
        "--result won needs --player: whose result is it?\n",
    )
    assert stats_("Nope") == (1, "No collection called Nope.\n")
    assert stats_("Classics", "--player", "Nobody") == (0, "No games of Nobody in Classics.\n")
    assert stats_("Classics", "--result", "drawn") == (
        0,
        "No games in Classics (drawn).\n",
    )
    code, out = stats_("Classics", "--phase", "late")
    assert code == 2 and "late" in out


def test_players(fake: FakeEngine) -> None:
    hint = "Add games with: blunderbook collection import FILE --into NAME\n"
    assert runner.invoke(commands, ["players"]).output == "No games yet. " + hint
    assert stats_() == (0, "No games yet. " + hint)
    import_(str(CLASSICS), "--into", "Classics")
    out = runner.invoke(commands, ["players", "Classics"]).output.splitlines()
    assert out[0] == f"Classics {DOT} 4 players"
    assert out[1].split() == ["Games", "White", "Black", "Won", "Drawn", "Lost", "Accuracy"]
    assert out[2].split() == [
        "Duke",
        "Karl",
        "/",
        "Count",
        "Isouard",
        "1",
        "0",
        "1",
        "0",
        "0",
        "1",
        "100.0",
    ]
    assert [line.split()[0] for line in out[2:]] == ["Duke", "Kermur", "Paul", "Saint"]
