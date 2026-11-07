"""Extensions (CLAUDE.md §15): separate packages that add a tab, routes, commands and their
own database, found when they're installed and turned on in config.toml.

An extension package declares an entry point in the ``blunderbook.extensions`` group, named
after the extension, that points at an :class:`Extension`::

    [project.entry-points."blunderbook.extensions"]
    library = "blunderbook_library:extension"

Core never imports an extension by name. One that is turned on but missing, broken, or made
for another host API is reported once and left out: the app runs without it.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from importlib.resources.abc import Traversable
from typing import Final

import typer
from fastapi import APIRouter

GROUP: Final = "blunderbook.extensions"
HOST_API: Final = 1  # bump when the contract or the host API changes incompatibly

NAME: Final = re.compile(r"[a-z]+")
# Names already used by commands, page routes or served folders.
RESERVED: Final = frozenset(
    {
        "ai", "api", "backup", "css", "doctor", "engine", "ext", "fen", "import", "init",
        "js", "log", "patterns", "pieces", "print", "restore", "retest", "serve", "sync",
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
    return value, None


def _points(found: Iterable[EntryPoint] | None) -> dict[str, EntryPoint]:
    points = entry_points(group=GROUP) if found is None else found
    return {ep.name: ep for ep in points}
