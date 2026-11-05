import tomllib
from pathlib import Path

import pytest

from blunderbook import config
from blunderbook.config import ChesscomConfig, Config, LichessConfig, Thresholds


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    cfg = config.load(tmp_path / "config.toml")
    assert cfg == Config()
    assert cfg.engine_depth == 16
    assert cfg.thresholds == Thresholds(0.05, 0.10, 0.15, 60)


def test_partial_file_keeps_other_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('my_names = [" Rashed ", ""]\n[thresholds]\nblunder = 0.2\n', "utf-8")
    cfg = config.load(path)
    assert cfg.my_names == ("Rashed",)
    assert cfg.thresholds.blunder == 0.2
    assert cfg.thresholds.mistake == 0.10
    assert cfg.engine_threads == 2


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('future_option = true\n[lichess]\ntheme = "dark"\n', "utf-8")
    assert config.load(path) == Config()


@pytest.mark.parametrize(
    ("toml", "key"),
    [
        ('engine_depth = "16"', "engine_depth"),
        ("engine_depth = 0", "engine_depth"),
        ("engine_threads = true", "engine_threads"),
        ('my_names = "Rashed"', "my_names"),
        ("my_names = [1, 2]", "my_names"),
        ("stockfish_path = 3", "stockfish_path"),
        ("[thresholds]\nblunder = 1.5", "thresholds.blunder"),
        ("[thresholds]\naccept_margin_cp = -1", "thresholds.accept_margin_cp"),
        ("[thresholds]\nmistake = 0.2", "inaccuracy <= mistake <= blunder"),
        ("[thresholds]\ninaccuracy = 0.12", "inaccuracy <= mistake <= blunder"),
        ("lichess = 3", "[lichess]"),
        ("[lichess]\ntoken = 123", "lichess.token"),
    ],
)
def test_bad_values_name_the_key(tmp_path: Path, toml: str, key: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(toml + "\n", "utf-8")
    with pytest.raises(config.ConfigError) as err:
        config.load(path)
    assert key in str(err.value)
    assert str(path) in str(err.value)


def test_invalid_toml_with_windows_path_gives_a_hint(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('stockfish_path = "C:\\Users\\me\\stockfish.exe"\n', "utf-8")
    with pytest.raises(config.ConfigError, match="single quotes"):
        config.load(path)


def test_utf8_bom_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes('\ufeffmy_names = ["Rashed"]\n'.encode())
    assert config.load(path).my_names == ("Rashed",)


@pytest.mark.parametrize(
    "stockfish_path",
    [
        "",
        r"C:\Program Files\Stockfish\stockfish-windows-x86-64-avx2.exe",
        "/opt/homebrew/bin/stockfish",
        r"C:\Users\O'Brien\stockfish.exe",  # quote forces a basic string
        'odd "quoted" \\ name\twith tab',
    ],
)
def test_save_then_load_round_trip(tmp_path: Path, stockfish_path: str) -> None:
    cfg = Config(
        my_names=("Rashed", "rashed_blitz", "রাশেদ"),
        stockfish_path=stockfish_path,
        engine_depth=20,
        engine_threads=4,
        engine_hash_mb=256,
        thresholds=Thresholds(0.04, 0.09, 0.2, 50),
        lichess=LichessConfig(username="rashed", token="lip_secret"),
        chesscom=ChesscomConfig(username="rashed_blitz", contact="me@example.com"),
    )
    path = config.save(cfg, tmp_path / "nested" / "config.toml")
    assert path.read_text("utf-8").startswith("# Blunderbook settings.")
    assert config.load(path) == cfg
    assert not path.with_name("config.toml.tmp").exists()


def test_rendered_defaults_parse_and_use_literal_strings_for_paths() -> None:
    text = config.render(Config(stockfish_path=r"C:\sf\stockfish.exe"))
    assert r"stockfish_path = 'C:\sf\stockfish.exe'" in text
    assert tomllib.loads(text)["thresholds"]["blunder"] == 0.15


def test_token_never_in_repr_or_str() -> None:
    cfg = Config(lichess=LichessConfig(username="rashed", token="lip_secret"))
    assert "lip_secret" not in repr(cfg)
    assert "lip_secret" not in str(cfg)
    assert "lip_secret" not in repr(cfg.lichess)
