"""Extensions for the extension tests (CLAUDE.md §15). Loaded through hand-made entry
points such as ``EntryPoint("sample", "ext_samples:sample", ext.GROUP)``."""

import typer

from blunderbook import ext

commands = typer.Typer(no_args_is_help=True)


@commands.command("hello")
def hello() -> None:
    """Say hello."""
    typer.echo("Hello from the sample extension.")


sample = ext.Extension(name="sample", title="Sample", host_api=ext.HOST_API, cli=commands)
other = ext.Extension(name="other", title="Other", host_api=ext.HOST_API)
reserved = ext.Extension(name="log", title="Log", host_api=ext.HOST_API)
bad_name = ext.Extension(name="Bad1", title="Bad", host_api=ext.HOST_API)
old_api = ext.Extension(name="old", title="Old", host_api=ext.HOST_API + 1)
not_an_extension = {"name": "plain"}
