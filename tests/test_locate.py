import sys
from pathlib import Path

import pytest

from blunderbook.config import (
    NOT_FOUND,
    STOCKFISH_ENV,
    Config,
    EnginePathError,
    locate_stockfish,
    resolve_engine_path,
)

WINDOWS = sys.platform == "win32"


def program(folder: Path, stem: str) -> Path:
    """Create a fake runnable program named like a Stockfish release binary."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (stem + ".exe" if WINDOWS else stem)
    path.write_bytes(b"")
    path.chmod(0o755)
    return path


def no_which(_: str) -> str | None:
    return None


# ---------------------------------------------------------------- resolve_engine_path


def test_file_path(tmp_path: Path) -> None:
    exe = program(tmp_path, "stockfish")
    assert resolve_engine_path(str(exe)) == exe


@pytest.mark.parametrize("wrap", ['"{}"', "'{}'", "  {}  ", ' "{}" \n'])
def test_pasted_quotes_and_spaces_are_stripped(tmp_path: Path, wrap: str) -> None:
    exe = program(tmp_path / "Program Files" / "Stockfish", "stockfish")
    assert resolve_engine_path(wrap.format(exe)) == exe


def test_home_and_env_vars_are_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = program(tmp_path / "tools", "stockfish")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("BB_TOOLS", str(tmp_path / "tools"))
    assert resolve_engine_path("~/tools/" + exe.name) == exe
    env_ref = "%BB_TOOLS%" if WINDOWS else "$BB_TOOLS"
    assert resolve_engine_path(f"{env_ref}/{exe.name}") == exe


def test_relative_path_uses_base(tmp_path: Path) -> None:
    exe = program(tmp_path / "engines", "stockfish")
    assert resolve_engine_path("engines/" + exe.name, base=tmp_path) == exe


def test_folder_with_one_program(tmp_path: Path) -> None:
    exe = program(tmp_path, "stockfish-windows-x86-64-avx2")
    (tmp_path / "stockfish.nnue").write_bytes(b"")
    (tmp_path / "stockfish-README.md").write_text("docs")
    assert resolve_engine_path(str(tmp_path)) == exe


def test_unzipped_release_folder_is_searched_one_level_down(tmp_path: Path) -> None:
    # The official zip unpacks to stockfish/stockfish-<os>-<arch>[.exe] plus docs and src.
    exe = program(tmp_path / "stockfish", "stockfish-ubuntu-x86-64-avx2")
    (tmp_path / "stockfish" / "src").mkdir()
    (tmp_path / "stockfish" / "Copying.txt").write_text("GPL")
    assert resolve_engine_path(str(tmp_path)) == exe


def test_folder_search_stops_one_level_down(tmp_path: Path) -> None:
    program(tmp_path / "a" / "b", "stockfish")
    with pytest.raises(EnginePathError, match="No Stockfish program found"):
        resolve_engine_path(str(tmp_path))


def test_folder_with_several_programs_lists_them(tmp_path: Path) -> None:
    first = program(tmp_path, "stockfish-avx2")
    second = program(tmp_path / "old", "stockfish-16")
    with pytest.raises(EnginePathError, match="More than one") as err:
        resolve_engine_path(str(tmp_path))
    assert str(first) in str(err.value)
    assert str(second) in str(err.value)


def test_nothing_there(tmp_path: Path) -> None:
    with pytest.raises(EnginePathError, match="Nothing found"):
        resolve_engine_path(str(tmp_path / "missing.exe"))


def test_empty_input() -> None:
    with pytest.raises(EnginePathError, match="empty"):
        resolve_engine_path('  ""  ')


def test_file_that_isnt_a_program(tmp_path: Path) -> None:
    text = tmp_path / "stockfish.txt"
    text.write_text("not a program")
    with pytest.raises(EnginePathError, match="isn't a program"):
        resolve_engine_path(str(text))


# ---------------------------------------------------------------- locate_stockfish


def test_lookup_order(tmp_path: Path) -> None:
    flag = program(tmp_path / "flag", "stockfish")
    env = program(tmp_path / "env", "stockfish")
    cfg = program(tmp_path / "cfg", "stockfish")
    on_path = program(tmp_path / "path", "stockfish")

    def which(_: str) -> str:
        return str(on_path)

    settings = Config(stockfish_path=str(cfg))
    environ = {STOCKFISH_ENV: str(env)}

    found = locate_stockfish(str(flag), settings, env=environ, which=which)
    assert (found.path, found.origin) == (flag, "flag")
    found = locate_stockfish(None, settings, env=environ, which=which)
    assert (found.path, found.origin) == (env, "env")
    found = locate_stockfish(None, settings, env={}, which=which)
    assert (found.path, found.origin) == (cfg, "config")
    found = locate_stockfish(None, Config(), env={}, which=which)
    assert (found.path, found.origin) == (on_path, "path")


def test_blank_settings_are_treated_as_unset(tmp_path: Path) -> None:
    on_path = program(tmp_path, "stockfish")
    found = locate_stockfish(
        "  ",
        Config(stockfish_path=""),
        env={STOCKFISH_ENV: ""},
        which=lambda _: str(on_path),
    )
    assert found.origin == "path"


def test_broken_setting_does_not_fall_through(tmp_path: Path) -> None:
    on_path = program(tmp_path, "stockfish")
    found = locate_stockfish(
        None,
        Config(stockfish_path=str(tmp_path / "gone" / "stockfish.exe")),
        env={},
        which=lambda _: str(on_path),
    )
    assert found.path is None
    assert found.origin == "config"
    assert found.problem is not None
    assert "Nothing found" in found.problem
    assert "config.toml" in found.problem


def test_relative_config_path_is_next_to_config_file(tmp_path: Path) -> None:
    exe = program(tmp_path / "engines", "stockfish")
    found = locate_stockfish(
        None,
        Config(stockfish_path="engines/" + exe.name),
        env={},
        which=no_which,
        config_dir=tmp_path,
    )
    assert found.path == exe


def test_nothing_anywhere() -> None:
    found = locate_stockfish(None, Config(), env={}, which=no_which)
    assert (found.path, found.origin, found.problem) == (None, None, NOT_FOUND)
