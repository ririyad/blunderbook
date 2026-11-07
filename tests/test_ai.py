"""The OpenRouter client (CLAUDE.md §7.10) on httpx MockTransport: never the network."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from blunderbook import ai
from blunderbook.core.explain import Prompt

HTTP = Path(__file__).parent / "fixtures" / "http"
KEY = "sk-or-v1-0123456789abcdef"
PROMPT = Prompt("system text", "user text")


def answer(status: int, body: Any) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def fixture(name: str) -> Any:
    return json.loads((HTTP / name).read_text("utf-8"))


def ask(transport: httpx.BaseTransport, model: str = "deepseek/deepseek-chat") -> ai.Answer:
    return ai.explain(PROMPT, key=KEY, model=model, transport=transport)


def problem(transport: httpx.BaseTransport) -> str:
    with pytest.raises(ai.AiError) as caught:
        ask(transport)
    message = str(caught.value)
    assert KEY not in message
    return message


def test_request_sent() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=fixture("openrouter_chat_completion.json"))

    ask(httpx.MockTransport(handle), model="anthropic/claude-haiku")
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["user-agent"].startswith("Blunderbook/")
    assert "http-referer" not in request.headers  # no leaderboard attribution
    assert "x-openrouter-title" not in request.headers
    assert json.loads(request.content) == {
        "model": "anthropic/claude-haiku",
        "messages": [
            {"role": "system", "content": "system text"},
            {"role": "user", "content": "user text"},
        ],
        "temperature": 0.2,
        "max_completion_tokens": 1000,
        "provider": {"data_collection": "deny"},
    }


def test_answer_text_and_model() -> None:
    got = ask(answer(200, fixture("openrouter_chat_completion.json")), model="deepseek/x")
    assert got.text.startswith("You played 6. Nxd5, but that knight on d5 was not defended.")
    assert "\n\nStockfish's 6. e3" in got.text
    assert got.model == "deepseek/deepseek-chat"  # the model that answered


def test_answer_without_a_model_name_uses_ours() -> None:
    body = fixture("openrouter_chat_completion.json")
    del body["model"]
    assert ask(answer(200, body), model="mine/model").model == "mine/model"


def test_out_of_credits() -> None:
    message = problem(answer(402, fixture("openrouter_error_402.json")))
    assert message == "Your OpenRouter account is out of credits. Add some on openrouter.ai."


@pytest.mark.parametrize(
    ("status", "start"),
    [
        (401, "OpenRouter didn't accept your key. Set it again with: blunderbook ai set-key"),
        (403, "OpenRouter refused this request. OpenRouter says: nope"),
        (408, "deepseek/deepseek-chat took too long."),
        (429, "OpenRouter is busy, or you've hit a rate limit."),
        (502, "deepseek/deepseek-chat is down or answered badly."),
        (503, "No provider for deepseek/deepseek-chat is available that doesn't keep your data."),
        (400, "OpenRouter refused the request for deepseek/deepseek-chat. OpenRouter says: nope"),
        (500, "OpenRouter answered with an error (HTTP 500). OpenRouter says: nope"),
    ],
)
def test_errors_are_plain(status: int, start: str) -> None:
    assert problem(answer(status, {"error": {"code": status, "message": "nope"}})).startswith(start)


def test_key_in_an_error_message_is_redacted() -> None:
    body = {"error": {"code": 400, "message": f"bad key {KEY} for model"}}
    assert "bad key [token] for model" in problem(answer(400, body))


def test_error_inside_a_200() -> None:
    assert problem(answer(200, {"error": {"code": 502, "message": "upstream"}})).startswith(
        "deepseek/deepseek-chat is down"
    )
    body = {"choices": [{"finish_reason": "error", "message": {"content": "partial"}}]}
    assert "stopped with an error" in problem(answer(200, body))


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"finish_reason": "length", "message": {"content": None}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "   "}}]},
    ],
)
def test_no_text(body: Any) -> None:
    message = problem(answer(200, body))
    assert "no text" in message


def test_not_json() -> None:
    assert problem(answer(200, b"<html>")) == "OpenRouter's answer couldn't be read. Try again."
    assert problem(answer(502, b"Bad gateway")).startswith("deepseek/deepseek-chat is down")


def test_timeout_and_no_connection() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route for {KEY}", request=request)

    assert problem(httpx.MockTransport(slow)) == "OpenRouter didn't answer in time. Try again."
    assert problem(httpx.MockTransport(offline)) == "Can't reach OpenRouter: no route for [token]"
