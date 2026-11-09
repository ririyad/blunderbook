"""`blunderbook update` and `blunderbook ext install`. Git runs for real on temp repos (a
bare "remote" and clones of it, no network); uv and the Windows window are never started."""

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from blunderbook import cli, ext, update
from blunderbook.ext import Installed

runner = CliRunner()
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git isn't installed")


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def commit(folder: Path, name: str, text: str = "x") -> None:
    (folder / name).write_text(text, "utf-8")
    git(folder, "add", name)
    git(folder, "commit", "--quiet", "-m", f"add {name}")


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """``(yours, theirs)``: your installed copy, and another clone that pushes new commits."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(remote))
    theirs = tmp_path / "theirs"
    git(tmp_path, "clone", "--quiet", str(remote), str(theirs))
    git(theirs, "checkout", "--quiet", "-b", "main")
    commit(theirs, "pyproject.toml", "[project]\nname = 'blunderbook'\n")
    (theirs / "extensions" / "library").mkdir(parents=True)
    commit(theirs, "extensions/library/pyproject.toml")
    git(theirs, "push", "--quiet", "-u", "origin", "main")
    yours = tmp_path / "your copy"  # a space, as in a real path
    git(tmp_path, "clone", "--quiet", str(remote), str(yours))
    return yours, theirs


def push(theirs: Path, *names: str) -> None:
    for name in names:
        commit(theirs, name)
    git(theirs, "push", "--quiet")


# ---------------------------------------------------------------- where it came from


def test_a_folder_install() -> None:
    url = '{"url": "file:///E:/apps/blunderbook", "dir_info": {}}'
    found = update.folder_from(url)
    assert found is not None and found.name == "blunderbook"
    assert found == Path.from_uri("file:///E:/apps/blunderbook")


def test_a_development_copy() -> None:
    url = '{"url": "file:///E:/Projects/blunderbook", "dir_info": {"editable": true}}'
    with pytest.raises(update.UpdateError, match="development copy"):
        update.folder_from(url)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "not json",
        "[]",
        '{"url": "https://github.com/x/blunderbook", "vcs_info": {"vcs": "git"}}',
        '{"url": "file:///tmp/blunderbook-0.1.0.whl", "archive_info": {}}',
    ],
)
def test_not_from_a_folder(text: str | None) -> None:
    assert update.folder_from(text) is None


def test_source_says_how_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "_direct_url", lambda _: None)
    with pytest.raises(update.UpdateError, match="installed from a git folder"):
        update.source()


def test_extensions_are_kept_by_folder_or_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    library = tmp_path / "extensions" / "library"
    urls = {
        "blunderbook-library": f'{{"url": "{library.as_uri()}", "dir_info": {{}}}}',
        "blunderbook-other": None,  # from an index
    }
    monkeypatch.setattr(update, "_direct_url", urls.get)
    monkeypatch.setattr(
        ext,
        "installed",
        lambda: [
            Installed("library", "blunderbook-library", "0.1.0"),
            Installed("other", "blunderbook-other", "1.0"),
            Installed("odd", None, None),
        ],
    )
    assert update.extension_specs() == [str(library), "blunderbook-other"]


def test_the_uv_command() -> None:
    folder = Path("E:/apps/my blunderbook")
    assert update.uv_command("uv", folder, ["E:/x/library", "pkg", "pkg"]) == [
        "uv", "tool", "install", "--reinstall", str(folder),
        "--with", "E:/x/library", "--with", "pkg",
    ]  # fmt: skip
    assert update.uv_command("uv", folder, []) == [
        "uv",
        "tool",
        "install",
        "--reinstall",
        str(folder),
    ]


# ---------------------------------------------------------------- git


@needs_git
def test_up_to_date(repos: tuple[Path, Path]) -> None:
    yours, _ = repos
    pending = update.check(yours)
    assert pending.new == () and pending.head == pending.upstream
    assert update.report(pending) == [f"Already up to date ({pending.head})."]


@needs_git
def test_new_changes_are_listed_then_applied(repos: tuple[Path, Path]) -> None:
    yours, theirs = repos
    push(theirs, "a.txt", "b.txt")
    before = git(yours, "rev-parse", "HEAD")
    pending = update.check(yours)
    assert git(yours, "rev-parse", "HEAD") == before  # checking changes nothing
    assert [line.split(" ", 1)[1] for line in pending.new] == ["add b.txt", "add a.txt"]
    lines = update.report(pending)
    assert lines[0] == f"2 new changes ({pending.head} \N{RIGHTWARDS ARROW} {pending.upstream}):"
    assert lines[1:] == [f"  {line}" for line in pending.new]
    assert update.apply(yours) == pending.upstream
    assert (yours / "b.txt").is_file()


def test_a_long_list_is_cut() -> None:
    pending = update.Pending("aaaaaaa", "bbbbbbb", tuple(f"c{i} change {i}" for i in range(13)))
    lines = update.report(pending)
    assert len(lines) == 1 + update.SHOWN + 1
    assert lines[-1] == "  \N{HORIZONTAL ELLIPSIS} and 3 more"
    one = update.report(update.Pending("aaaaaaa", "bbbbbbb", ("c1 one",)))
    assert one[0].startswith("1 new change (")


@needs_git
def test_local_changes_refuse(repos: tuple[Path, Path]) -> None:
    yours, theirs = repos
    push(theirs, "a.txt")
    (yours / "pyproject.toml").write_text("edited", "utf-8")
    with pytest.raises(update.UpdateError, match=r"You have changes in .*Nothing was updated"):
        update.check(yours)
    (yours / "pyproject.toml").write_text("[project]\nname = 'blunderbook'\n", "utf-8")
    (yours / "my-games.pgn").write_text("1. e4", "utf-8")  # untracked files are fine
    assert len(update.check(yours).new) == 1


@needs_git
def test_diverged_refuses(repos: tuple[Path, Path]) -> None:
    yours, theirs = repos
    push(theirs, "a.txt")
    commit(yours, "mine.txt")
    head = git(yours, "rev-parse", "HEAD")
    with pytest.raises(update.UpdateError, match="commits that aren't on origin/main"):
        update.check(yours)
    assert git(yours, "rev-parse", "HEAD") == head


@needs_git
def test_your_own_commits_alone_are_fine(repos: tuple[Path, Path]) -> None:
    yours, _ = repos
    commit(yours, "mine.txt")
    assert update.check(yours).new == ()


@needs_git
def test_no_upstream_refuses(repos: tuple[Path, Path]) -> None:
    yours, _ = repos
    git(yours, "checkout", "--quiet", "-b", "local")
    with pytest.raises(update.UpdateError, match="no upstream"):
        update.check(yours)


@needs_git
def test_not_a_checkout(tmp_path: Path) -> None:
    with pytest.raises(update.UpdateError, match="isn't a git checkout"):
        update.check(tmp_path)


@needs_git
def test_a_failed_fetch(repos: tuple[Path, Path], tmp_path: Path) -> None:
    yours, _ = repos
    git(yours, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
    with pytest.raises(update.UpdateError, match="Couldn't fetch the new version"):
        update.check(yours)


# ---------------------------------------------------------------- reinstall


def test_posix_runs_uv_here(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[list[str]] = []

    def show(args: Sequence[str]) -> int:
        ran.append(list(args))
        return 0

    monkeypatch.setattr(update, "WINDOWS", False)
    monkeypatch.setattr(update, "_show", show)
    monkeypatch.setattr(update.shutil, "which", lambda _: "/home/me/.local/bin/blunderbook")
    assert update.reinstall(["uv", "tool"], done="Done.", enable="library") == 0
    assert ran == [["uv", "tool"], ["/home/me/.local/bin/blunderbook", "ext", "enable", "library"]]
    assert capsys.readouterr().out == "Done.\n"


def test_posix_failure_stops(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(update, "WINDOWS", False)
    monkeypatch.setattr(update, "_show", lambda args: ran.append(list(args)) or 2)
    assert update.reinstall(["uv"], done="Done.", enable="library") == 2
    assert ran == [["uv"]]  # not turned on
    assert capsys.readouterr().out == ""


def test_windows_hands_off(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned: list[list[str]] = []
    monkeypatch.setattr(update, "WINDOWS", True)
    monkeypatch.setattr(update, "_spawn", lambda args: spawned.append(list(args)))
    monkeypatch.setattr(update, "_show", lambda _: pytest.fail("uv ran in this process"))
    monkeypatch.setattr(update, "program", lambda name: f"C:\\{name}.exe")
    assert update.reinstall(["uv", "tool"], done="Done.") == 0
    ((shell, *flags, script),) = spawned
    assert (shell, flags) == ("C:\\powershell.exe", ["-NoProfile", "-Command"])
    assert "& 'uv' 'tool'" in script and "'ext' 'enable'" not in script


def test_the_windows_script() -> None:
    command = ["C:\\uv.exe", "tool", "install", "--reinstall", "E:\\Rashed's apps\\blunderbook"]
    script = update.windows_script(
        command, done="Blunderbook is up to date (abc1234).", enable="library", pid=11, parent=22
    )
    assert "$wait = @(11)" in script
    assert "Get-Process -Id 22" in script and "$wait += 22" in script
    assert "-like '*\\blunderbook.exe'" in script  # the launcher, only when it is one
    assert "Get-Process -Name 'blunderbook'" in script
    assert "Waiting for blunderbook serve to stop" in script
    assert (
        "& 'C:\\uv.exe' 'tool' 'install' '--reinstall' 'E:\\Rashed''s apps\\blunderbook'" in script
    )
    assert "& 'blunderbook' 'ext' 'enable' 'library'" in script
    assert "Write-Host 'Blunderbook is up to date (abc1234).'" in script
    assert "Run blunderbook update again." in script
    assert script.rstrip().endswith("Read-Host 'Press Enter to close'")
    # The order: wait, then reinstall, then turn on.
    assert script.index("Wait-Process") < script.index("'--reinstall'") < script.index("'enable'")


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell only")
def test_the_windows_script_parses() -> None:
    """PowerShell's own parser accepts it (nothing runs)."""
    script = update.windows_script(
        ["uv", "tool", "install", "E:\\it's here"], done="Done.", enable="library", pid=1, parent=2
    )
    check = (
        "$e = $null; [System.Management.Automation.Language.Parser]::ParseInput("
        "$env:BB_SCRIPT, [ref]$null, [ref]$e) | Out-Null; $e.Count"
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command", check],
        env={**os.environ, "BB_SCRIPT": script},
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == "0"


# ---------------------------------------------------------------- the commands


@pytest.fixture
def installed_from(monkeypatch: pytest.MonkeyPatch, repos: tuple[Path, Path]) -> list[list[str]]:
    """Blunderbook "installed" from your copy, with the Library; uv only recorded."""
    yours, _ = repos
    ran: list[list[str]] = []
    monkeypatch.setattr(update, "source", lambda: yours)
    monkeypatch.setattr(
        update, "extension_specs", lambda: ["E:/apps/blunderbook/extensions/library"]
    )
    real = shutil.which
    monkeypatch.setattr(update, "program", lambda name: "uv" if name == "uv" else real(name))
    monkeypatch.setattr(update, "WINDOWS", False)
    monkeypatch.setattr(update, "_show", lambda args: ran.append(list(args)) or 0)
    return ran


@needs_git
def test_update_command(installed_from: list[list[str]], repos: tuple[Path, Path]) -> None:
    yours, theirs = repos
    push(theirs, "a.txt")
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 0, result.output
    head = git(yours, "rev-parse", "--short", "HEAD")
    assert "1 new change (" in result.output and "add a.txt" in result.output
    assert f"Updated {yours} to {head}." in result.output
    assert f"Blunderbook is up to date ({head})." in result.output
    assert installed_from == [
        ["uv", "tool", "install", "--reinstall", str(yours),
         "--with", "E:/apps/blunderbook/extensions/library"],
    ]  # fmt: skip


@needs_git
def test_update_check_changes_nothing(
    installed_from: list[list[str]], repos: tuple[Path, Path]
) -> None:
    yours, theirs = repos
    push(theirs, "a.txt")
    head = git(yours, "rev-parse", "HEAD")
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0, result.output
    assert (
        "1 new change" in result.output
        and "Run blunderbook update to install them." in result.output
    )
    assert git(yours, "rev-parse", "HEAD") == head
    assert installed_from == []


@needs_git
def test_update_when_up_to_date_still_reinstalls(installed_from: list[list[str]]) -> None:
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 0, result.output
    assert "Already up to date (" in result.output
    assert "Reinstalling it as it is" in result.output
    assert len(installed_from) == 1


@needs_git
def test_update_refusal_exits_1(installed_from: list[list[str]], repos: tuple[Path, Path]) -> None:
    yours, _ = repos
    (yours / "pyproject.toml").write_text("edited", "utf-8")
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 1
    assert "Nothing was updated." in result.output
    assert installed_from == []


@needs_git
def test_a_failed_reinstall_exits_with_its_code(
    installed_from: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update, "_show", lambda _: 2)
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 2
    assert "The reinstall failed. Run blunderbook update again." in result.output


@needs_git
def test_update_on_windows_says_where(
    installed_from: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[list[str]] = []
    monkeypatch.setattr(update, "WINDOWS", True)
    monkeypatch.setattr(update, "_spawn", lambda args: spawned.append(list(args)))
    real = shutil.which
    monkeypatch.setattr(
        update, "program", lambda name: name if name in ("uv", "powershell") else real(name)
    )
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 0, result.output
    assert "Reinstalling in a new window. It starts when this command ends." in result.output
    assert len(spawned) == 1 and installed_from == []


def test_a_development_copy_exits_1() -> None:
    """The tests run in the dev checkout: an editable install."""
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 1
    assert "This is a development copy" in result.output


@needs_git
def test_ext_install(
    installed_from: list[list[str]], repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    yours, _ = repos
    monkeypatch.setattr(ext, "find", lambda _: None)
    monkeypatch.setattr(update.shutil, "which", lambda _: "blunderbook")
    result = runner.invoke(cli.app, ["ext", "install", "library"])
    assert result.exit_code == 0, result.output
    assert installed_from == [
        ["uv", "tool", "install", "--reinstall", str(yours),
         "--with", "E:/apps/blunderbook/extensions/library",
         "--with", str(yours / "extensions" / "library")],
        ["blunderbook", "ext", "enable", "library"],
    ]  # fmt: skip
    assert "Installed the library extension." in result.output


@needs_git
@pytest.mark.parametrize("name", ["nope", "../library", "Library"])
def test_ext_install_of_an_unknown_name(installed_from: list[list[str]], name: str) -> None:
    result = runner.invoke(cli.app, ["ext", "install", name])
    assert result.exit_code == 1
    assert f"There's no extensions/{name} folder. Extensions here: library." in result.output
    assert installed_from == []


def test_ext_install_of_an_installed_one_only_turns_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(ext, "find", lambda name: object())
    monkeypatch.setattr(cli, "ext_enable", calls.append)
    monkeypatch.setattr(update, "reinstall", lambda *a, **k: pytest.fail("reinstalled"))
    result = runner.invoke(cli.app, ["ext", "install", "library"])
    assert result.exit_code == 0, result.output
    assert "The library extension is already installed." in result.output
    assert calls == ["library"]


def test_update_is_reserved() -> None:
    assert "update" in ext.RESERVED
