"""HTTP for the Rankings extension: one request at a time, only when you press Update or run
``blunderbook rankings update`` (CLAUDE.md §1.3, §15). Nothing here runs on its own.

- A descriptive User-Agent on every request, and a timeout.
- HTTP 429: wait (``Retry-After``, at least a minute, as the sites ask), try once more, then
  stop with a plain message.
- Downloads go to a file as they arrive, with a size cap, and send back what the server said
  last time (``ETag`` / ``Last-Modified``), so an unchanged file isn't downloaded again.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import httpx

VERSION: Final = "0.1.0"  # the package's version (a test checks pyproject.toml)
USER_AGENT: Final = f"Blunderbook-Rankings/{VERSION} (local chess app)"
TIMEOUT: Final = httpx.Timeout(30.0)
WAIT_429_S: Final = 60.0
LONGEST_WAIT_S: Final = 300.0  # a longer Retry-After stops the update instead of hanging it
MAX_DOWNLOAD_BYTES: Final = 200 * 1024 * 1024  # FIDE's biggest list is about 14 MB
CHUNK: Final = 64 * 1024

Progress = Callable[[float], None]  # 0..1 of this step
Wait = Callable[[float], None]  # sleeps; raises Stopped when the update is stopped


class RankingsError(Exception):
    """An update that can't go on. The message is plain and ready to show."""


class Stopped(Exception):
    """The update was stopped (Ctrl+C on ``serve``, or the job's stop). Nothing is saved."""


@dataclass(frozen=True, slots=True)
class Validators:
    """What the server said about a file last time."""

    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class Downloaded:
    path: Path
    validators: Validators


def client(user_agent: str = USER_AGENT) -> httpx.Client:
    """The client for one update. Close it (``with``) when the update ends."""
    return httpx.Client(headers={"User-Agent": user_agent}, timeout=TIMEOUT, follow_redirects=True)


def host_of(url: str) -> str:
    return urlsplit(url).hostname or url


def conditional(saved: Validators) -> dict[str, str]:
    """The headers that ask for a file only if it changed."""
    headers: dict[str, str] = {}
    if saved.etag:
        headers["If-None-Match"] = saved.etag
    if saved.last_modified:
        headers["If-Modified-Since"] = saved.last_modified
    return headers


def validators(response: httpx.Response) -> Validators:
    return Validators(
        etag=response.headers.get("ETag"), last_modified=response.headers.get("Last-Modified")
    )


def unchanged(response: httpx.Response, saved: Validators) -> bool:
    """A 304, or a 200 carrying the same ETag as last time (a server that ignores the
    conditional headers). With no ETag on both sides, the same Last-Modified."""
    if response.status_code == 304:
        return True
    got = validators(response)
    if saved.etag and got.etag:
        return got.etag == saved.etag
    return bool(saved.last_modified and got.last_modified == saved.last_modified)


def get_json(
    http: httpx.Client, url: str, wait: Wait, headers: dict[str, str] | None = None
) -> httpx.Response:
    """GET ``url``: the response (200 or 304), after at most one wait for a 429."""
    with _send(http, url, wait, headers or {}) as response:
        response.read()
        return response


def download(
    http: httpx.Client,
    url: str,
    dest: Path,
    saved: Validators,
    wait: Wait,
    progress: Progress,
    stop: Callable[[], bool],
) -> Downloaded | None:
    """Download ``url`` to ``dest`` as it arrives. None when it hasn't changed since
    ``saved``. Raises RankingsError, or Stopped between chunks."""
    with _send(http, url, wait, conditional(saved)) as response:
        if unchanged(response, saved):
            return None
        size = _int(response.headers.get("Content-Length"))
        if size is not None and size > MAX_DOWNLOAD_BYTES:
            raise RankingsError(f"{host_of(url)} sent a file too big to be a rating list.")
        done = 0
        try:
            with dest.open("wb") as out:
                for chunk in response.iter_bytes(CHUNK):
                    if stop():
                        raise Stopped
                    done += len(chunk)
                    if done > MAX_DOWNLOAD_BYTES:
                        raise RankingsError(
                            f"{host_of(url)} sent a file too big to be a rating list."
                        )
                    out.write(chunk)
                    if size:
                        progress(min(done / size, 1.0))
        except httpx.HTTPError as exc:
            raise RankingsError(f"The download from {host_of(url)} broke off: {_why(exc)}") from exc
        progress(1.0)
        return Downloaded(dest, validators(response))


class _send:
    """A streamed GET that answers 200 or 304, else raises RankingsError. One retry after
    a 429."""

    def __init__(self, http: httpx.Client, url: str, wait: Wait, headers: dict[str, str]) -> None:
        self.http, self.url, self.wait, self.headers = http, url, wait, headers
        self.response: httpx.Response | None = None

    def __enter__(self) -> httpx.Response:
        for attempt in range(2):
            response = self._open()
            if response.status_code != 429:
                break
            response.close()
            seconds = wait_for(response)
            if attempt == 1 or seconds > LONGEST_WAIT_S:
                raise RankingsError(
                    f"{host_of(self.url)} asked to slow down (HTTP 429). "
                    "Try again in a few minutes."
                )
            self.wait(seconds)
        self.response = response
        if response.status_code not in (200, 304):
            response.close()
            raise RankingsError(
                f"{host_of(self.url)} answered HTTP {response.status_code} for {self.url}."
            )
        return response

    def __exit__(self, *exc: object) -> None:
        if self.response is not None:
            self.response.close()

    def _open(self) -> httpx.Response:
        try:
            request = self.http.build_request("GET", self.url, headers=self.headers)
            return self.http.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise RankingsError(f"Can't reach {host_of(self.url)}: {_why(exc)}") from exc


def wait_for(response: httpx.Response) -> float:
    """How long to wait after a 429: Retry-After if it says longer, else one minute."""
    try:
        asked = float(response.headers.get("Retry-After", "0"))
    except ValueError:
        asked = 0.0
    return max(WAIT_429_S, asked)


def sleeper(stop: Callable[[], bool]) -> Wait:
    """A wait that checks ``stop`` every second, and raises Stopped when it's set."""

    def wait(seconds: float) -> None:
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            if stop():
                raise Stopped
            time.sleep(min(1.0, left))

    return wait


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _why(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "it took too long to answer."
    if isinstance(exc, httpx.ConnectError):
        return "no connection (are you online?)."
    return str(exc) or type(exc).__name__
