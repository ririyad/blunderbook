"""The AI explanation routes (CLAUDE.md §7.10, §10) against a real temp database, with
OpenRouter replaced by httpx MockTransport. Nothing here reaches the network."""

import json
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api_blunders import NOW, URL, elephant, fen_entry, scholars

from blunderbook import ai, config
from blunderbook.api.app import create_app
from blunderbook.config import AiConfig, Config
from blunderbook.core import explain
from blunderbook.db import connection, repo

HTTP = Path(__file__).parent / "fixtures" / "http"
KEY = "sk-or-v1-0123456789abcdef"
ANSWER = json.loads((HTTP / "openrouter_chat_completion.json").read_text("utf-8"))


@pytest.fixture
def ids(db_file: Path) -> dict[str, int]:
    made: dict[str, int] = {}
    with closing(connection.open_db(db_file, create=True)) as conn:
        for minutes, (name, make) in enumerate(
            (("elephant", elephant), ("scholars", scholars), ("fen", fen_entry))
        ):
            game, blunder = make()
            saved = repo.add_game(conn, game, [blunder], now=NOW + timedelta(minutes=minutes))
            assert saved is not None
            made[name] = saved.blunder_ids[0]
    return made


@pytest.fixture
def client(db_file: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_file), base_url=URL) as test_client:
        yield test_client


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    return path


def ai_on(cfg_file: Path, **fields: Any) -> None:
    settings = {"enabled": True, "model": "deepseek/deepseek-chat", "key": KEY, **fields}
    config.save(Config(my_names=("Rashed",), ai=AiConfig(**settings)), cfg_file)


Requests = list[httpx.Request]


@pytest.fixture
def openrouter(monkeypatch: pytest.MonkeyPatch) -> Callable[[int, Any], Requests]:
    """Answer OpenRouter calls with ``status`` and ``body``; returns the requests made."""
    real = ai.explain

    def setup(status: int, body: Any) -> Requests:
        seen: Requests = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(status, json=body)

        def fake(prompt: explain.Prompt, *, key: str, model: str) -> ai.Answer:
            return real(prompt, key=key, model=model, transport=httpx.MockTransport(handle))

        monkeypatch.setattr(ai, "explain", fake)
        return seen

    return setup


def explain_now(client: TestClient, blunder_id: int, **headers: str) -> httpx.Response:
    return client.post(f"/api/blunders/{blunder_id}/explanation", headers=headers)


# ---------------------------------------------------------------- /api/ai


def test_ai_off_by_default(client: TestClient, cfg_file: Path) -> None:
    assert client.get("/api/ai").json() == {"enabled": False, "model": None}


def test_ai_on(client: TestClient, cfg_file: Path) -> None:
    ai_on(cfg_file)
    response = client.get("/api/ai")
    assert response.json() == {"enabled": True, "model": "deepseek/deepseek-chat"}
    assert KEY not in response.text


def test_ai_on_without_a_key_isnt_enabled(client: TestClient, cfg_file: Path) -> None:
    ai_on(cfg_file, key="")
    assert client.get("/api/ai").json() == {"enabled": False, "model": "deepseek/deepseek-chat"}


def test_broken_config_is_a_503(client: TestClient, cfg_file: Path) -> None:
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("[ai]\nenabled = 'yes'\n", "utf-8")
    response = client.get("/api/ai")
    assert response.status_code == 503
    assert "ai.enabled must be true or false" in response.json()["detail"]


# ---------------------------------------------------------------- What's sent


def test_prompt_is_what_would_be_sent(
    client: TestClient, cfg_file: Path, ids: dict[str, int]
) -> None:
    ai_on(cfg_file)
    client.patch(f"/api/blunders/{ids['elephant']}", json={"thinking": "Zzthinking"})
    response = client.get(f"/api/blunders/{ids['elephant']}/explanation/prompt")
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "deepseek/deepseek-chat"
    assert body["system"] == explain.SYSTEM
    assert body["user"].startswith("You played White. Your move was 6. Nxd5??, a blunder.")
    for private in ("Zzthinking", "Rashed", "1512", "1498", KEY):
        assert private not in response.text


def test_prompt_for_a_missing_entry(
    client: TestClient, cfg_file: Path, ids: dict[str, int]
) -> None:
    assert client.get("/api/blunders/99/explanation/prompt").status_code == 404


# ---------------------------------------------------------------- explaining


def test_explain_saves_and_shows_in_the_log(
    client: TestClient, cfg_file: Path, ids: dict[str, int], openrouter: Callable[..., Requests]
) -> None:
    ai_on(cfg_file)
    seen = openrouter(200, ANSWER)
    blunder_id = ids["elephant"]
    assert client.get(f"/api/blunders/{blunder_id}").json()["explanation"] is None

    response = explain_now(client, blunder_id, Origin=URL)
    assert response.status_code == 200, response.text
    made = response.json()
    assert made["text"].startswith("You played 6. Nxd5")
    assert made["model"] == "deepseek/deepseek-chat"
    assert KEY not in response.text

    (request,) = seen
    sent = json.loads(request.content)
    prompt = client.get(f"/api/blunders/{blunder_id}/explanation/prompt").json()
    assert sent["messages"] == [
        {"role": "system", "content": prompt["system"]},
        {"role": "user", "content": prompt["user"]},
    ]
    assert client.get(f"/api/blunders/{blunder_id}").json()["explanation"] == made
    assert client.get(f"/api/blunders/{ids['scholars']}").json()["explanation"] is None


def test_explaining_again_replaces_it(
    client: TestClient, cfg_file: Path, ids: dict[str, int], openrouter: Callable[..., Requests]
) -> None:
    ai_on(cfg_file)
    openrouter(200, ANSWER)
    explain_now(client, ids["fen"])
    second = {**ANSWER, "model": "anthropic/claude-haiku"}
    second["choices"] = [{"finish_reason": "stop", "message": {"content": "Second try."}}]
    openrouter(200, second)
    made = explain_now(client, ids["fen"]).json()
    assert (made["text"], made["model"]) == ("Second try.", "anthropic/claude-haiku")
    assert client.get(f"/api/blunders/{ids['fen']}").json()["explanation"] == made


def test_off_is_a_503_and_nothing_is_sent(
    client: TestClient, cfg_file: Path, ids: dict[str, int], openrouter: Callable[..., Requests]
) -> None:
    seen = openrouter(200, ANSWER)
    response = explain_now(client, ids["elephant"])
    assert response.status_code == 503
    assert response.json()["detail"].startswith("AI explanations are off.")
    ai_on(cfg_file, key="")
    assert explain_now(client, ids["elephant"]).json()["detail"].startswith("No OpenRouter key")
    assert seen == []


def test_another_website_cant_ask(
    client: TestClient, cfg_file: Path, ids: dict[str, int], openrouter: Callable[..., Requests]
) -> None:
    ai_on(cfg_file)
    seen = openrouter(200, ANSWER)
    response = explain_now(client, ids["elephant"], Origin="https://evil.example")
    assert response.status_code == 403
    assert seen == []


def test_missing_entry(
    client: TestClient, cfg_file: Path, ids: dict[str, int], openrouter: Callable[..., Requests]
) -> None:
    ai_on(cfg_file)
    seen = openrouter(200, ANSWER)
    assert explain_now(client, 99).status_code == 404
    assert seen == []


def test_openrouter_error_is_a_502_and_nothing_is_saved(
    client: TestClient, cfg_file: Path, ids: dict[str, int], openrouter: Callable[..., Requests]
) -> None:
    ai_on(cfg_file)
    openrouter(401, {"error": {"code": 401, "message": f"No auth for {KEY}"}})
    response = explain_now(client, ids["elephant"])
    assert response.status_code == 502
    assert response.json()["detail"].startswith("OpenRouter didn't accept your key.")
    assert KEY not in response.text
    assert client.get(f"/api/blunders/{ids['elephant']}").json()["explanation"] is None


def test_deleting_the_entry_deletes_its_explanation(
    client: TestClient,
    cfg_file: Path,
    ids: dict[str, int],
    db_file: Path,
    openrouter: Callable[..., Requests],
) -> None:
    ai_on(cfg_file)
    openrouter(200, ANSWER)
    explain_now(client, ids["elephant"])
    assert client.delete(f"/api/blunders/{ids['elephant']}").status_code == 204
    with closing(connection.connect(db_file)) as conn:
        assert conn.execute("SELECT count(*) FROM explanations").fetchone()[0] == 0


# ---------------------------------------------------------------- Re-test


def test_retest_shows_it_only_after_the_attempt(
    client: TestClient, cfg_file: Path, ids: dict[str, int], openrouter: Callable[..., Requests]
) -> None:
    ai_on(cfg_file)
    openrouter(200, ANSWER)
    made = explain_now(client, ids["elephant"]).json()
    queue = client.get("/api/retest/queue").json()
    assert "explanation" not in json.dumps(queue)
    assert ANSWER["choices"][0]["message"]["content"][:30] not in json.dumps(queue)
    result = client.post(
        f"/api/retest/{ids['elephant']}/attempt", json={"move_uci": None, "used_hint": False}
    ).json()
    assert result["explanation"] == made
