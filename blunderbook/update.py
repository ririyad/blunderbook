"""`blunderbook update` and `blunderbook ext install`: bring the installed copy up to date
with its git folder, or add an extension from that folder (CLAUDE.md §9).

Blunderbook is installed with `uv tool install` from a git checkout. The installed packages
record where they came from (PEP 610 ``direct_url.json``), so the folder and every installed
extension are found with no setting. An update is a ``git fetch`` (the only network call),
a fast-forward of the folder, and the same ``uv tool install --reinstall`` you'd type, with
one ``--with`` for each extension, so none is left out.

Windows locks a running program's files, so this command can't reinstall itself there: it
hands the reinstall to a PowerShell window that waits for Blunderbook to exit (and for any
running ``serve``), then runs uv. On macOS and Linux uv runs here.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Final

from blunderbook import ext

PACKAGE: Final = "blunderbook"
SHOWN: Final = 10  # new changes listed by name; the rest are counted
WINDOWS = sys.platform == "win32"  # tests set it


class UpdateError(Exception):
    """Why the update can't run. Nothing was changed."""


@dataclass(frozen=True, slots=True)
class Pending:
    """What a fetch found: the folder's commit, its upstream's, and the commits in between
    as ``"abc1234 subject"``, oldest last (as ``git log`` lists them)."""

    head: str
    upstream: str
    new: tuple[str, ...]


# ---------------------------------------------------------------- where it came from


def folder_from(direct_url: str | None) -> Path | None:
    """The local folder a package was installed from, or None when it came from anywhere
    else (an index, a URL, a wheel). An editable install is a development copy."""
    if not direct_url:
        return None
    try:
        data = json.loads(direct_url)
    except ValueError:
        return None
    url = data.get("url") if isinstance(data, dict) else None
    info = data.get("dir_info") if isinstance(data, dict) else None
    if not isinstance(url, str) or not url.startswith("file:") or not isinstance(info, dict):
        return None
    if info.get("editable"):
        raise UpdateError("This is a development copy: run git pull, then uv sync, in its folder.")
    try:
        return Path.from_uri(url)
    except ValueError:
        return None


def _direct_url(package: str) -> str | None:
    try:
        return metadata.distribution(package).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None


def source() -> Path:
    """The git folder Blunderbook was installed from."""
    folder = folder_from(_direct_url(PACKAGE))
    if folder is None:
        raise UpdateError(
            "blunderbook update works for a copy installed from a git folder with "
            "uv tool install (see the README). Reinstall it the way you installed it."
        )
    if not folder.is_dir():
        raise UpdateError(f"The folder Blunderbook was installed from is gone: {folder}")
    return folder


def extension_specs() -> list[str]:
    """What to pass to ``--with`` to keep each installed extension: its folder, or its
    package name when it didn't come from a folder."""
    specs: list[str] = []
    for item in ext.installed():
        if item.package is None:
            continue
        try:
            folder = folder_from(_direct_url(item.package))
        except UpdateError:  # an editable extension in a dev copy: keep it by name
            folder = None
        spec = str(folder) if folder is not None else item.package
        if spec not in specs:
            specs.append(spec)
    return specs


def available(folder: Path) -> list[str]:
    """The extensions in the folder's ``extensions/``, by name."""
    root = folder / "extensions"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "pyproject.toml").is_file())


# ---------------------------------------------------------------- the programs


def program(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        hint = {
            "git": "Install Git (git-scm.com), then try again.",
            "uv": "Install uv (docs.astral.sh/uv), then try again.",
        }.get(name, "")
        raise UpdateError(f"{name} isn't on your PATH. {hint}".strip())
    return found


def _capture(args: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a program and collect what it says (git)."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # never wait for a password prompt
    return subprocess.run(
        list(args),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _show(args: Sequence[str]) -> int:
    """Run a program with its output on this terminal (uv), and give its exit code."""
    return subprocess.run(list(args), check=False).returncode


def _spawn(args: Sequence[str]) -> None:
    """Start a program in a console window of its own, which outlives this one (Windows)."""
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(list(args), creationflags=flags, close_fds=True)


# ---------------------------------------------------------------- git


def _git(folder: Path, *args: str) -> str:
    done = _capture([program("git"), *args], cwd=folder)
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        raise UpdateError(said[-1] if said else f"git {args[0]} failed.")
    return done.stdout.strip()


def check(folder: Path) -> Pending:
    """Fetch, and say what's new. Changes nothing in the folder."""
    git = program("git")
    inside = _capture([git, "rev-parse", "--is-inside-work-tree"], cwd=folder)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise UpdateError(f"{folder} isn't a git checkout, so it can't be updated.")
    if _git(folder, "status", "--porcelain", "--untracked-files=no"):
        raise UpdateError(f"You have changes in {folder}. Nothing was updated.")
    upstream = _capture(
        [git, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=folder
    )
    if upstream.returncode != 0:
        raise UpdateError(f"The branch in {folder} has no upstream to update from.")
    try:
        _git(folder, "fetch", "--quiet")
    except UpdateError as exc:
        raise UpdateError(f"Couldn't fetch the new version: {exc}") from None
    new = _git(folder, "log", "--format=%h %s", "HEAD..@{u}")
    ahead = int(_git(folder, "rev-list", "--count", "@{u}..HEAD") or 0)
    if new and ahead:
        branch = upstream.stdout.strip()
        raise UpdateError(
            f"Your copy in {folder} has commits that aren't on {branch}, and {branch} has "
            "new ones. Nothing was updated."
        )
    return Pending(
        head=_git(folder, "rev-parse", "--short", "HEAD"),
        upstream=_git(folder, "rev-parse", "--short", "@{u}"),
        new=tuple(new.splitlines()) if new else (),
    )


def apply(folder: Path) -> str:
    """Fast-forward the folder to its upstream; give the new short commit."""
    _git(folder, "merge", "--ff-only", "--quiet", "@{u}")
    return _git(folder, "rev-parse", "--short", "HEAD")


def report(pending: Pending) -> list[str]:
    if not pending.new:
        return [f"Already up to date ({pending.head})."]
    n = len(pending.new)
    lines = [
        f"{n} new change{'' if n == 1 else 's'} "
        f"({pending.head} \N{RIGHTWARDS ARROW} {pending.upstream}):"
    ]
    lines += [f"  {line}" for line in pending.new[:SHOWN]]
    if n > SHOWN:
        lines.append(f"  \N{HORIZONTAL ELLIPSIS} and {n - SHOWN} more")
    return lines


# ---------------------------------------------------------------- reinstall


def uv_command(uv: str, folder: Path, extensions: Sequence[str]) -> list[str]:
    """``uv tool install --reinstall <folder>``, with one ``--with`` for each extension."""
    command = [uv, "tool", "install", "--reinstall", str(folder)]
    for spec in dict.fromkeys(extensions):
        command += ["--with", spec]
    return command


def _ps(value: str) -> str:
    """A PowerShell literal string."""
    return "'" + value.replace("'", "''") + "'"


def windows_script(
    command: Sequence[str], *, done: str, enable: str | None, pid: int, parent: int
) -> str:
    """The PowerShell the new window runs: wait for this process and its launcher, then
    for any other running Blunderbook (``serve``), then reinstall, and keep the window open
    until you've read it."""
    enabling = ""
    if enable is not None:
        enabling = f"  & 'blunderbook' 'ext' 'enable' {_ps(enable)}\n"
    return (
        "$Host.UI.RawUI.WindowTitle = 'Blunderbook update'\n"
        f"$wait = @({pid})\n"
        f"$launcher = Get-Process -Id {parent} -ErrorAction SilentlyContinue\n"
        "$exe = $null\n"
        "if ($launcher -and $launcher.Path -like '*\\blunderbook.exe') {\n"
        f"  $wait += {parent}\n"
        "  $exe = $launcher.Path\n"
        "}\n"
        "Wait-Process -Id $wait -ErrorAction SilentlyContinue\n"
        "$others = @(Get-Process -Name 'blunderbook' -ErrorAction SilentlyContinue |"
        " Where-Object { -not $exe -or $_.Path -eq $exe })\n"
        "if ($others.Count -gt 0) {\n"
        "  Write-Host 'Waiting for blunderbook serve to stop (Ctrl+C in its window)...'\n"
        "  $others | Wait-Process -ErrorAction SilentlyContinue\n"
        "}\n"
        f"& {' '.join(_ps(part) for part in command)}\n"
        "if ($LASTEXITCODE -eq 0) {\n"
        f"{enabling}"
        "  Write-Host ''\n"
        f"  Write-Host {_ps(done)}\n"
        "} else {\n"
        "  Write-Host ''\n"
        "  Write-Host 'The reinstall failed. Run blunderbook update again.'\n"
        "}\n"
        "Read-Host 'Press Enter to close'\n"
    )


def reinstall(command: Sequence[str], *, done: str, enable: str | None = None) -> int:
    """Reinstall with ``command``, then turn on ``enable`` from the new install. Gives the
    exit code; on Windows the work goes on in a new window after this command ends."""
    if WINDOWS:
        shell = program("powershell")
        script = windows_script(
            command, done=done, enable=enable, pid=os.getpid(), parent=os.getppid()
        )
        _spawn([shell, "-NoProfile", "-Command", script])
        return 0
    code = _show(command)
    if code != 0:
        return code
    if enable is not None:
        found = shutil.which("blunderbook")
        if found is None:
            print(f"Now run: blunderbook ext enable {enable}")
        else:
            code = _show([found, "ext", "enable", enable])
    if code == 0:
        print(done)
    return code
