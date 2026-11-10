"""Load and save config.toml, and work out which Stockfish to use (CLAUDE.md §6).

Stockfish lookup order, first match wins:
  1. a ``--stockfish`` option on the command
  2. the ``BLUNDERBOOK_STOCKFISH`` environment variable
  3. ``stockfish_path`` in config.toml
  4. ``stockfish`` on PATH

A setting that is present but broken is reported as a problem. It never falls through to
a lower one, so you always know which engine is running.
"""

import os
import re
import shutil
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_config_dir, user_data_dir

from blunderbook.core.models import Thresholds

APP_NAME = "blunderbook"
STOCKFISH_ENV = "BLUNDERBOOK_STOCKFISH"

NOT_FOUND = (
    "No Stockfish found. Install Stockfish 17 or newer, then run:\n"
    "  blunderbook engine set PATH\n"
    "PATH can be the program itself or the folder you unzipped it to."
)


class ConfigError(Exception):
    """config.toml can't be read or has a bad value. The message names the key."""


class EnginePathError(Exception):
    """A Stockfish path that doesn't lead to a program. The message says why."""


# ---------------------------------------------------------------- locations


def config_path() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def db_path() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False)) / "blunderbook.db"


def default_backup_folder() -> Path:
    return db_path().parent / "backups"


def backup_folder(config: Config, *, config_dir: Path | None = None) -> Path:
    """Where backups go: ``[backup] dir``, or a ``backups`` folder next to the database.

    Like stockfish_path, it accepts surrounding quotes, ``~`` and environment variables,
    and a relative path is relative to the config folder. An environment variable that
    isn't set is an error, so a missing ``%OneDrive%`` never becomes a stray folder."""
    text = _unquote(config.backup.dir)
    if not text:
        return default_backup_folder()
    unset = _unset_variables(text)
    if unset:
        raise ConfigError(
            f"backup.dir uses {unset[0]}, which isn't set on this computer ({config.backup.dir})."
        )
    return _absolute(text, config_dir or config_path().parent)


def backup_dir_setting(raw: str, *, cwd: Path | None = None) -> str:
    """The ``backup.dir`` value to save for a folder someone typed. It's kept as typed when
    it's absolute once ``~`` and variables are expanded, so ``%OneDrive%\\Blunderbook``
    stays portable. A relative folder is saved as its absolute path from ``cwd``."""
    text = _unquote(raw)
    if not text:
        return ""
    if Path(os.path.expandvars(os.path.expanduser(text))).is_absolute():
        return text
    return str(_absolute(text, cwd))


# ---------------------------------------------------------------- model


@dataclass(frozen=True, slots=True)
class LichessConfig:
    username: str = ""
    token: str = field(default="", repr=False)  # never printed, never logged


@dataclass(frozen=True, slots=True)
class ChesscomConfig:
    username: str = ""
    contact: str = ""


@dataclass(frozen=True, slots=True)
class BackupConfig:
    dir: str = ""  # empty = <data folder>/backups; quotes, ~ and env vars allowed
    keep: int = 14  # newest backups kept
    auto: bool = True  # once a day before commands that change data


@dataclass(frozen=True, slots=True)
class AiConfig:
    enabled: bool = False  # off until you turn it on with `blunderbook ai on`
    model: str = ""  # an OpenRouter model id; no default, you choose
    key: str = field(default="", repr=False)  # OpenRouter API key: never printed, never logged


@dataclass(frozen=True, slots=True)
class ExtensionsConfig:
    enabled: tuple[str, ...] = ()  # extension names, turned on with `blunderbook ext enable`


@dataclass(frozen=True, slots=True)
class Config:
    my_names: tuple[str, ...] = ()
    stockfish_path: str = ""
    engine_depth: int = 16
    engine_threads: int = 2
    engine_hash_mb: int = 128
    thresholds: Thresholds = field(default_factory=Thresholds)
    lichess: LichessConfig = field(default_factory=LichessConfig)
    chesscom: ChesscomConfig = field(default_factory=ChesscomConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    extensions: ExtensionsConfig = field(default_factory=ExtensionsConfig)


def ai_problem(config: Config) -> str | None:
    """Why AI explanations can't run, in plain words, or None when they can."""
    ai = config.ai
    if not ai.enabled:
        return "AI explanations are off. Turn them on with: blunderbook ai on"
    if not ai.key.strip():
        return "No OpenRouter key is set. Set it with: blunderbook ai set-key"
    if not ai.model.strip():
        return "No model is set. Set it with: blunderbook ai model NAME"
    return None


# ---------------------------------------------------------------- load


def all_names(config: Config) -> list[str]:
    """The names that mark your side in a game: ``my_names`` and your site usernames."""
    return [*config.my_names, config.lichess.username, config.chesscom.username]


def load(path: Path | None = None) -> Config:
    """Read config.toml. A missing file gives the defaults."""
    path = path or config_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return Config()
    except OSError as exc:
        raise ConfigError(f"Can't read {path}: {exc.strerror}") from None
    try:
        text = raw.decode("utf-8-sig")
        data = tomllib.loads(text)
    except UnicodeDecodeError:
        raise ConfigError(f"{path} isn't UTF-8 text.") from None
    except tomllib.TOMLDecodeError as exc:
        hint = ""
        if "\\" in text:
            hint = (
                "\nFor Windows paths, use single quotes, like "
                "stockfish_path = 'C:\\path\\stockfish.exe'"
            )
        raise ConfigError(f"{path} isn't valid TOML: {exc}{hint}") from None
    try:
        return _from_dict(data)
    except ConfigError as exc:
        raise ConfigError(f"Problem in {path}: {exc}") from None


def _from_dict(data: Mapping[str, Any]) -> Config:
    root = _Table(data)
    th = root.table("thresholds")
    li = root.table("lichess")
    cc = root.table("chesscom")
    bk = root.table("backup")
    ai = root.table("ai")
    ext = root.table("extensions")
    d = Config()
    dt = d.thresholds
    thresholds = Thresholds(
        inaccuracy=th.fraction("inaccuracy", dt.inaccuracy),
        mistake=th.fraction("mistake", dt.mistake),
        blunder=th.fraction("blunder", dt.blunder),
        accept_margin_cp=th.whole("accept_margin_cp", dt.accept_margin_cp, minimum=0),
        missed_win_cp=th.whole("missed_win_cp", dt.missed_win_cp, minimum=0),
    )
    if not thresholds.inaccuracy <= thresholds.mistake <= thresholds.blunder:
        raise ConfigError("thresholds must go up: inaccuracy <= mistake <= blunder")
    return Config(
        my_names=root.names("my_names", d.my_names),
        stockfish_path=root.text("stockfish_path", d.stockfish_path),
        engine_depth=root.whole("engine_depth", d.engine_depth, minimum=1),
        engine_threads=root.whole("engine_threads", d.engine_threads, minimum=1),
        engine_hash_mb=root.whole("engine_hash_mb", d.engine_hash_mb, minimum=1),
        thresholds=thresholds,
        lichess=LichessConfig(username=li.text("username", ""), token=li.text("token", "")),
        chesscom=ChesscomConfig(username=cc.text("username", ""), contact=cc.text("contact", "")),
        backup=BackupConfig(
            dir=bk.text("dir", d.backup.dir),
            keep=bk.whole("keep", d.backup.keep, minimum=1),
            auto=bk.flag("auto", d.backup.auto),
        ),
        ai=AiConfig(
            enabled=ai.flag("enabled", d.ai.enabled),
            model=ai.text("model", d.ai.model).strip(),
            key=ai.text("key", d.ai.key).strip(),
        ),
        extensions=ExtensionsConfig(enabled=_extension_names(ext.names("enabled", ()))),
    )


def _extension_names(names: tuple[str, ...]) -> tuple[str, ...]:
    for name in names:
        if not re.fullmatch(r"[a-z]+", name):
            raise ConfigError(
                f"extensions.enabled: {name!r} isn't an extension name (lowercase letters only)"
            )
    return tuple(dict.fromkeys(names))


class _Table:
    """Typed reads from one TOML table. Unknown keys are ignored."""

    def __init__(self, data: Mapping[str, Any], where: str = "") -> None:
        self._data = data
        self._where = where

    def _name(self, key: str) -> str:
        return f"{self._where}.{key}" if self._where else key

    def table(self, key: str) -> _Table:
        value = self._data.get(key, {})
        if not isinstance(value, dict):
            raise ConfigError(f"[{self._name(key)}] must be a table")
        return _Table(value, self._name(key))

    def text(self, key: str, default: str) -> str:
        value = self._data.get(key, default)
        if not isinstance(value, str):
            raise ConfigError(f"{self._name(key)} must be text in quotes")
        return value

    def whole(self, key: str, default: int, *, minimum: int) -> int:
        value = self._data.get(key, default)
        if type(value) is not int or value < minimum:
            raise ConfigError(f"{self._name(key)} must be a whole number, {minimum} or more")
        return value

    def flag(self, key: str, default: bool) -> bool:
        value = self._data.get(key, default)
        if not isinstance(value, bool):
            raise ConfigError(f"{self._name(key)} must be true or false")
        return value

    def fraction(self, key: str, default: float) -> float:
        value = self._data.get(key, default)
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ConfigError(f"{self._name(key)} must be a number from 0 to 1")
        return float(value)

    def names(self, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = self._data.get(key, list(default))
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f'{self._name(key)} must be a list of names, like ["Rashed"]')
        return tuple(v.strip() for v in value if v.strip())


# ---------------------------------------------------------------- save


def save(config: Config, path: Path | None = None) -> Path:
    """Write config.toml from the template, atomically. Returns the path written."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(render(config), encoding="utf-8", newline="\n")
    if os.name != "nt":
        tmp.chmod(0o600)  # it can hold a Lichess token
    os.replace(tmp, path)
    return path


def render(config: Config) -> str:
    """The full config.toml text for ``config``. Comments come from this template."""
    t, li, cc, bk = config.thresholds, config.lichess, config.chesscom, config.backup
    ai = config.ai
    lines = [
        "# Blunderbook settings.",
        "# The app rewrites this file when you change a setting, so comments you add",
        "# here aren't kept.",
        "",
        "# Names and usernames used to work out which side you played.",
        f"my_names = {_toml_list(config.my_names)}",
        "",
        "# The Stockfish program, or empty to look for `stockfish` on PATH.",
        "# Set it with: blunderbook engine set PATH",
        f"stockfish_path = {_toml_str(config.stockfish_path)}",
        "",
        "# First-pass search depth per position, and engine threads and hash.",
        f"engine_depth = {config.engine_depth}",
        f"engine_threads = {config.engine_threads}",
        f"engine_hash_mb = {config.engine_hash_mb}",
        "",
        "# Swing thresholds, 0 to 1. Imports only log moves at or above `blunder`, and",
        "# missed wins: a mate you missed, or a drop of missed_win_cp centipawns or more",
        "# while you stay ahead (0 turns missed wins off).",
        "# Re-tests accept moves within accept_margin_cp centipawns of the best move.",
        "[thresholds]",
        f"inaccuracy = {t.inaccuracy!r}",
        f"mistake = {t.mistake!r}",
        f"blunder = {t.blunder!r}",
        f"accept_margin_cp = {t.accept_margin_cp}",
        f"missed_win_cp = {t.missed_win_cp}",
        "",
        "[lichess]",
        f"username = {_toml_str(li.username)}",
        "# Optional personal token. Never commit or share this file.",
        f"token = {_toml_str(li.token)}",
        "",
        "[chesscom]",
        f"username = {_toml_str(cc.username)}",
        "# Sent in the User-Agent header, as Chess.com asks. Your email works.",
        f"contact = {_toml_str(cc.contact)}",
        "",
        "# Database backups. Empty dir = a `backups` folder next to the database. For a",
        "# copy off this computer, use a folder your cloud drive syncs, such as",
        "# '%OneDrive%\\Blunderbook'. Backups hold the database only, never this file.",
        "[backup]",
        f"dir = {_toml_str(bk.dir)}",
        "# How many of the newest backups to keep (1 or more).",
        f"keep = {bk.keep}",
        "# Back up once a day before import, fen, sync and serve.",
        f"auto = {'true' if bk.auto else 'false'}",
        "",
        "# Optional AI explanations of a blunder, through OpenRouter (openrouter.ai), with",
        '# your own key. Off by default. Nothing is sent until you press "Explain this',
        "# blunder\" on the page: the position and Stockfish's lines, never names or notes.",
        "# Set with: blunderbook ai set-key, blunderbook ai model NAME, blunderbook ai on",
        "[ai]",
        f"enabled = {'true' if ai.enabled else 'false'}",
        "# An OpenRouter model id, as listed on openrouter.ai/models.",
        f"model = {_toml_str(ai.model)}",
        "# Your OpenRouter API key. Never commit or share this file.",
        f"key = {_toml_str(ai.key)}",
        "",
        "# Extensions turned on, by name. Set with: blunderbook ext enable NAME",
        "[extensions]",
        f"enabled = {_toml_list(config.extensions.enabled)}",
    ]
    return "\n".join(lines) + "\n"


_BASIC_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_str(value: str) -> str:
    # Literal strings keep Windows paths readable: 'C:\Users\you\stockfish.exe'.
    if "'" not in value and all(ord(ch) >= 0x20 and ord(ch) != 0x7F for ch in value):
        return f"'{value}'"
    out = []
    for ch in value:
        if ch in _BASIC_ESCAPES:
            out.append(_BASIC_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


# ---------------------------------------------------------------- Stockfish location

Origin = Literal["flag", "env", "config", "path"]

ORIGIN_LABELS: dict[Origin, str] = {
    "flag": "the --stockfish option",
    "env": f"the {STOCKFISH_ENV} environment variable",
    "config": "config.toml (stockfish_path)",
    "path": "PATH",
}

# Files that sit next to Stockfish in release archives but aren't the program.
_NOT_PROGRAMS = {".nnue", ".txt", ".md", ".zip", ".tar", ".gz", ".tgz", ".7z"}


@dataclass(frozen=True, slots=True)
class StockfishLocation:
    """Found: ``path`` and ``origin`` set. Broken setting: ``origin`` and ``problem`` set.
    Nothing anywhere: only ``problem`` set."""

    path: Path | None
    origin: Origin | None
    problem: str | None = None


def locate_stockfish(
    flag: str | None = None,
    config: Config | None = None,
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
    config_dir: Path | None = None,
) -> StockfishLocation:
    env = os.environ if env is None else env
    which = which or shutil.which
    settings: list[tuple[Origin, str | None]] = [
        ("flag", flag),
        ("env", env.get(STOCKFISH_ENV)),
        ("config", config.stockfish_path if config else None),
    ]
    for origin, raw in settings:
        if raw is None or not raw.strip():
            continue
        # Relative paths in config.toml mean "next to config.toml"; others mean "from here".
        base = (config_dir or config_path().parent) if origin == "config" else None
        try:
            return StockfishLocation(resolve_engine_path(raw, base=base), origin)
        except EnginePathError as exc:
            return StockfishLocation(None, origin, f"{exc} (from {ORIGIN_LABELS[origin]})")
    found = which("stockfish")
    if found:
        return StockfishLocation(Path(found), "path")
    return StockfishLocation(None, None, NOT_FOUND)


def resolve_engine_path(raw: str, base: Path | None = None) -> Path:
    """Turn what a person typed or pasted into the Stockfish program's absolute path.

    Accepts surrounding quotes, ``~``, environment variables, and a folder (searched,
    plus one level down).
    """
    text = _unquote(raw)
    if not text:
        raise EnginePathError("The path is empty.")
    path = _absolute(text, base)
    if path.is_dir():
        return _find_in_folder(path)
    if not path.exists():
        raise EnginePathError(f"Nothing found at {path}.")
    if not _is_program(path):
        raise EnginePathError(f"{path} isn't a program you can run.")
    return path


def _unquote(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


# $NAME and ${NAME} everywhere; %NAME% on Windows, where expandvars reads it too.
_VARIABLE = re.compile(r"\$(\w+)|\$\{([^}]*)\}" + (r"|%([^%]+)%" if os.name == "nt" else ""))


def _unset_variables(text: str) -> list[str]:
    """The variables ``text`` uses that aren't set, as written (``%OneDrive%``)."""
    unset = []
    for match in _VARIABLE.finditer(text):
        name = next(g for g in match.groups() if g is not None)
        if not name or name not in os.environ:
            unset.append(match.group(0))
    return unset


def _absolute(text: str, base: Path | None) -> Path:
    """Expand ``~`` and environment variables, and make the path absolute against ``base``
    (default: the current folder)."""
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    # abspath, not resolve(): keep symlinks such as Homebrew's bin/stockfish, which
    # survive upgrades, instead of the versioned file they point to.
    return Path(os.path.abspath(path))


def _find_in_folder(folder: Path) -> Path:
    found: set[Path] = set()
    for directory in [folder, *_subfolders(folder)]:
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        found.update(p for p in entries if _looks_like_stockfish(p))
    if not found:
        raise EnginePathError(
            f"No Stockfish program found in {folder}. "
            "Point to the program itself, or the folder you unzipped."
        )
    if len(found) > 1:
        listed = "\n".join(f"  {p}" for p in sorted(found))
        raise EnginePathError(
            f"More than one Stockfish program in {folder}:\n{listed}\nPass the full path of one."
        )
    return found.pop()


def _subfolders(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_dir())
    except OSError:
        return []


def _looks_like_stockfish(path: Path) -> bool:
    return (
        path.name.lower().startswith("stockfish")
        and path.suffix.lower() not in _NOT_PROGRAMS
        and _is_program(path)
    )


def _is_program(path: Path) -> bool:
    if not path.is_file():
        return False
    if sys.platform == "win32":
        runnable = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(";")
        return path.suffix.lower() in runnable
    return os.access(path, os.X_OK)
