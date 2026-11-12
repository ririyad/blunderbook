"""Extensions (CLAUDE.md §15): separate packages that add a tab, routes, commands and their
own database, found when they're installed and turned on in config.toml.

An extension package declares an entry point in the ``blunderbook.extensions`` group, named
after the extension, that points at an :class:`Extension`::

    [project.entry-points."blunderbook.extensions"]
    library = "blunderbook_library:extension"

Core never imports an extension by name. One that is turned on but missing, broken, or made
for another host API is reported once and left out: the app runs without it.
"""

import ast
import re
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

import typer
from fastapi import APIRouter

from blunderbook import config
from blunderbook.db import backup, connection
from blunderbook.db.connection import CORE, Store

GROUP: Final = "blunderbook.extensions"
HOST_API: Final = 1  # bump when the contract or the host API changes incompatibly

NAME: Final = re.compile(r"[a-z]+")
# Names already used by commands, page routes or served folders.
RESERVED: Final = frozenset(
    {
        "ai", "api", "backup", "blunderbook", "css", "doctor", "engine", "ext", "fen",
        "games", "import", "init", "js", "log", "patterns", "pieces", "print", "restore",
        "retest", "serve", "sync", "update",
    }
)  # fmt: skip


@dataclass(frozen=True, kw_only=True)
class Extension:
    """What an extension package hands to Blunderbook."""

    name: str  # "library": [a-z]+, the same as its entry point's name
    title: str  # the tab's label: "Library"
    host_api: int  # the HOST_API it was written for
    router: APIRouter | None = None  # mounted at /api/ext/<name>
    web: Traversable | None = None  # a folder with view.js (and view.css), at /ext/<name>/
    migrations: Traversable | None = None  # its own NNNN_name.sql files, for <name>.db
    cli: typer.Typer | None = field(default=None, repr=False)  # `blunderbook <name> ...`
    # The most backups of <name>.db kept, when fewer than backup.keep will do (its data can
    # be downloaded again); None: backup.keep, like Blunderbook's own.
    backups_kept: int | None = None


@dataclass(frozen=True, slots=True)
class Installed:
    """An extension package on this computer, loaded or not."""

    name: str
    package: str | None  # the distribution, e.g. "blunderbook-library"
    version: str | None


@dataclass(frozen=True, slots=True)
class Loaded:
    """The extensions turned on and usable, and why any others were left out."""

    extensions: tuple[Extension, ...] = ()
    problems: tuple[str, ...] = ()


def installed(found: Iterable[EntryPoint] | None = None) -> list[Installed]:
    """Every extension package on this computer, by name."""
    points = _points(found)
    return [
        Installed(
            name=ep.name,
            package=ep.dist.name if ep.dist is not None else None,
            version=ep.dist.version if ep.dist is not None else None,
        )
        for ep in sorted(points.values(), key=lambda ep: ep.name)
    ]


def find(name: str, found: Iterable[EntryPoint] | None = None) -> EntryPoint | None:
    """The installed extension called ``name``, not loaded yet."""
    return _points(found).get(name)


def load(enabled: Sequence[str], found: Iterable[EntryPoint] | None = None) -> Loaded:
    """Load the extensions named in ``enabled``, in that order. Never raises: a missing or
    broken one becomes a problem, and the others still load."""
    points = _points(found)
    good: list[Extension] = []
    problems: list[str] = []
    for name in dict.fromkeys(enabled):
        point = points.get(name)
        if point is None:
            problems.append(
                f"The {name} extension is turned on but isn't installed. Install it, "
                f"or run: blunderbook ext disable {name}"
            )
            continue
        extension, problem = load_one(point)
        if problem is not None:
            problems.append(problem)
        elif extension is not None:
            good.append(extension)
    return Loaded(tuple(good), tuple(problems))


def load_one(point: EntryPoint) -> tuple[Extension | None, str | None]:
    """Import one extension and check it. Returns it, or a plain reason it can't be used."""
    name = point.name
    try:
        value = point.load()
    except Exception as exc:  # any failure in someone else's code: report, don't crash
        return None, f"The {name} extension couldn't be loaded: {type(exc).__name__}: {exc}"
    if not isinstance(value, Extension):
        return None, f"The {name} extension doesn't point at a Blunderbook Extension."
    if value.name != name:
        return None, f"The {name} extension calls itself {value.name!r}; the names must match."
    if not NAME.fullmatch(name):
        return None, f"{name!r} can't be an extension name: use lowercase letters only."
    if name in RESERVED:
        return None, f"{name!r} can't be an extension name: Blunderbook uses it already."
    if value.host_api != HOST_API:
        return None, (
            f"The {name} extension was made for host API {value.host_api}, and this "
            f"Blunderbook has host API {HOST_API}. Update the one that's older."
        )
    if value.web is not None:
        folder = web_folder(value)
        if folder is None:
            return None, (
                f"The {name} extension's page files aren't in a folder on disk. "
                "Install it unzipped."
            )
        if not (folder / "view.js").is_file():
            return None, f"The {name} extension's page folder has no view.js."
    if value.migrations is not None and not value.migrations.is_dir():
        return None, f"The {name} extension's migrations folder is missing."
    kept = value.backups_kept
    if kept is not None and (type(kept) is not int or kept < 1):
        return None, f"The {name} extension's backups_kept must be 1 or more, not {kept!r}."
    return value, None


def web_folder(extension: Extension) -> Path | None:
    """The folder with the extension's page files, or None when it has no page or its files
    aren't a folder on disk (a zipped install: the server can only serve real files)."""
    if extension.web is None:
        return None
    folder = Path(str(extension.web))
    return folder if folder.is_dir() else None


# What an extension may import from Blunderbook: the host API, this module and the core.
HOST_MODULES: Final = ("blunderbook.host", "blunderbook.ext", "blunderbook.core")


def boundary_problems(package: Path) -> list[str]:
    """Imports of Blunderbook outside the host API in the ``.py`` files under ``package``,
    as plain lines; [] when there are none. For an extension's own tests."""
    found: list[str] = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module == "blunderbook":
                    names = [f"blunderbook.{alias.name}" for alias in node.names]
                else:
                    names = [node.module]
            else:
                continue
            for name in names:
                if _outside_host_api(name):
                    where = f"{path.relative_to(package).as_posix()}:{node.lineno}"
                    found.append(f"{where} imports {name}, which isn't part of the host API")
    return found


def _outside_host_api(module: str) -> bool:
    if module != "blunderbook" and not module.startswith("blunderbook."):
        return False
    return not any(module == m or module.startswith(m + ".") for m in HOST_MODULES)


def _points(found: Iterable[EntryPoint] | None) -> dict[str, EntryPoint]:
    points = entry_points(group=GROUP) if found is None else found
    return {ep.name: ep for ep in points}


# ---------------------------------------------------------------- databases


def store(extension: Extension) -> Store | None:
    """The extension's own database, or None when it has no migrations (and so no DB)."""
    if extension.migrations is None:
        return None
    return Store(
        extension.name,
        f"the {extension.name} extension",
        extension.migrations,
        keep=extension.backups_kept,
    )


def db_path(extension: Extension, core: Path | None = None) -> Path:
    """``<name>.db``, next to Blunderbook's own database (``core``, or the usual one)."""
    return (core or config.db_path()).parent / f"{extension.name}.db"


def databases(cfg: config.Config) -> list[tuple[Store, Path]]:
    """Every database to back up: Blunderbook's, then each extension's that's on and has
    one. Extensions that can't be loaded are left out (``doctor`` reports them)."""
    found: list[tuple[Store, Path]] = [(CORE, config.db_path())]
    for extension in load(cfg.extensions.enabled).extensions:
        own = store(extension)
        if own is not None:
            found.append((own, db_path(extension)))
    return found


@dataclass(frozen=True, slots=True)
class DailyBackups:
    taken: tuple[Path, ...] = ()  # the backups made
    problems: tuple[str, ...] = ()  # "The daily backup didn't work: ..."


def daily_backups(cfg: config.Config, db: Path | None = None) -> DailyBackups:
    """Take the daily backups that are due (CLAUDE.md §6): Blunderbook's database, then each
    extension's. A failure is a problem, never an exception: it must not stop the command.
    ``db`` replaces Blunderbook's own database path."""
    try:
        folder = config.backup_folder(cfg)
    except config.ConfigError as exc:
        return DailyBackups(problems=(f"The daily backup didn't work: {exc}",))
    taken: list[Path] = []
    problems: list[str] = []
    for own, path in databases(cfg):
        if own is CORE and db is not None:
            path = db
        try:
            snapshot = backup.auto(path, folder, keep=cfg.backup.keep, store=own)
        except backup.BackupError as exc:
            whose = "" if own is CORE else f" of {own.label}'s database"
            problems.append(f"The daily backup{whose} didn't work: {exc}")
            continue
        if snapshot is not None:
            taken.append(snapshot.backup.path)
    return DailyBackups(tuple(taken), tuple(problems))


def open_db(
    extension: Extension,
    cfg: config.Config,
    *,
    any_thread: bool = False,
    on_backup: Callable[[Path], object] | None = None,
) -> sqlite3.Connection:
    """Open the extension's database, creating it if it's missing. One with data is backed
    up (``-pre-migrate``) before it's upgraded, as Blunderbook's own is; if that backup
    fails, it isn't upgraded. ``on_backup`` hears where the backup went. Raises
    ``StorageError``; close it with ``contextlib.closing``."""
    own = store(extension)
    if own is None:
        raise connection.StorageError(f"The {extension.name} extension has no database.")
    path = db_path(extension)

    def before_migrate() -> None:
        try:
            snapshot = backup.take(
                path,
                config.backup_folder(cfg),
                keep=cfg.backup.keep,
                reason="pre-migrate",
                store=own,
            )
        except (config.ConfigError, backup.BackupError) as exc:
            raise connection.StorageError(
                f"Can't back up {own.label}'s database before upgrading it, so it wasn't "
                f"upgraded: {exc}"
            ) from exc
        if on_backup is not None:
            on_backup(snapshot.backup.path)

    conn = connection.open_db(path, create=True, before_migrate=before_migrate, store=own)
    if any_thread:  # reopen for the API's worker threads, now that it's up to date
        conn.close()
        conn = connection.connect(path, any_thread=True)
    return conn
