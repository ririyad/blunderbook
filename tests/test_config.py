import sys
import tomllib
from pathlib import Path

import pytest

from blunderbook import config
from blunderbook.config import BackupConfig, ChesscomConfig, Config, LichessConfig, Thresholds


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
        ("[backup]\nkeep = 0", "backup.keep"),
        ('[backup]\nkeep = "14"', "backup.keep"),
        ('[backup]\nauto = "yes"', "backup.auto"),
        ("[backup]\ndir = false", "backup.dir"),
        ("backup = 1", "[backup]"),
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
        backup=BackupConfig(dir=r"%OneDrive%\Blunderbook", keep=30, auto=False),
    )
    path = config.save(cfg, tmp_path / "nested" / "config.toml")
    assert path.read_text("utf-8").startswith("# Blunderbook settings.")
    assert config.load(path) == cfg
    assert not path.with_name("config.toml.tmp").exists()


def test_rendered_defaults_parse_and_use_literal_strings_for_paths() -> None:
    text = config.render(Config(stockfish_path=r"C:\sf\stockfish.exe"))
    assert r"stockfish_path = 'C:\sf\stockfish.exe'" in text
    data = tomllib.loads(text)
    assert data["thresholds"]["blunder"] == 0.15
    assert data["backup"] == {"dir": "", "keep": 14, "auto": True}


def test_backup_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[backup]\nkeep = 3\n", "utf-8")
    assert config.load(path).backup == BackupConfig(dir="", keep=3, auto=True)


# ---------------------------------------------------------------- backup folder


def folder_for(raw: str, config_dir: Path) -> Path:
    return config.backup_folder(Config(backup=BackupConfig(dir=raw)), config_dir=config_dir)


def test_empty_backup_dir_is_next_to_the_database(tmp_path: Path, db_file: Path) -> None:
    assert folder_for("", tmp_path) == db_file.parent / "backups"
    assert folder_for("  ''  ", tmp_path) == db_file.parent / "backups"
    assert config.default_backup_folder() == db_file.parent / "backups"


def test_backup_dir_absolute_quoted_and_relative(tmp_path: Path) -> None:
    target = tmp_path / "Backups"
    assert folder_for(str(target), tmp_path / "cfg") == target
    assert folder_for(f'"{target}"', tmp_path / "cfg") == target
    assert folder_for("bk", tmp_path / "cfg") == tmp_path / "cfg" / "bk"  # next to config.toml


def test_backup_dir_expands_home_and_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BB_CLOUD", str(tmp_path / "cloud"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    assert folder_for("$BB_CLOUD/Blunderbook", tmp_path) == tmp_path / "cloud" / "Blunderbook"
    assert folder_for("${BB_CLOUD}/Blunderbook", tmp_path) == tmp_path / "cloud" / "Blunderbook"
    assert folder_for("~/bk", tmp_path) == tmp_path / "home" / "bk"
    if sys.platform == "win32":
        assert folder_for(r"%BB_CLOUD%\Blunderbook", tmp_path) == tmp_path / "cloud" / "Blunderbook"


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("$BB_MISSING/Blunderbook", "$BB_MISSING"),
        ("${BB_MISSING}/Blunderbook", "${BB_MISSING}"),
        *([(r"%BB_MISSING%\Blunderbook", "%BB_MISSING%")] if sys.platform == "win32" else []),
    ],
)
def test_backup_dir_with_an_unset_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str, shown: str
) -> None:
    monkeypatch.delenv("BB_MISSING", raising=False)
    with pytest.raises(config.ConfigError) as err:
        folder_for(raw, tmp_path)
    assert f"backup.dir uses {shown}, which isn't set on this computer" in str(err.value)
    assert not list(tmp_path.iterdir())


def test_backup_dir_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.backup_dir_setting("  ") == ""
    assert config.backup_dir_setting(f"'{tmp_path / 'bk'}'") == str(tmp_path / "bk")
    assert config.backup_dir_setting("rel/bk", cwd=tmp_path) == str(tmp_path / "rel" / "bk")
    monkeypatch.setenv("BB_CLOUD", str(tmp_path / "cloud"))
    assert config.backup_dir_setting("$BB_CLOUD/bk") == "$BB_CLOUD/bk"  # stays portable
    assert config.backup_dir_setting("~/bk") == "~/bk"


def test_token_never_in_repr_or_str() -> None:
    cfg = Config(lichess=LichessConfig(username="rashed", token="lip_secret"))
    assert "lip_secret" not in repr(cfg)
    assert "lip_secret" not in str(cfg)
    assert "lip_secret" not in repr(cfg.lichess)
