"""OpenRouter client for the optional AI explanation (CLAUDE.md §7.10).

The only network call outside the sync adapters, and only when you press "Explain this
blunder". It sends the prompt from ``core/explain.py``, nothing else.

API notes, checked 2026-11-07 against openrouter.ai/docs (API reference "Chat completion",
"Errors", "Provider routing", and the quickstart):

Endpoint
    ``POST https://openrouter.ai/api/v1/chat/completions``, OpenAI-compatible.

Headers
    ``Authorization: Bearer <key>`` and JSON. The optional ``HTTP-Referer`` and
    ``X-OpenRouter-Title`` headers only put an app on OpenRouter's leaderboards: not sent.

Body we send
    - ``model``: your model id from config.toml, as listed on openrouter.ai/models.
    - ``messages``: one ``system`` and one ``user`` message.
    - ``temperature`` (0 to 2): 0.2, to keep the wording close to the facts.
    - ``max_completion_tokens``: ``max_tokens`` is deprecated in its favour. Room for models
      that think before answering; the answer itself is 3 or 4 sentences.
    - ``provider.data_collection = "deny"``: only providers that don't collect your data.
      (``provider.zdr`` would narrow it to zero-data-retention endpoints; not sent, since
      it leaves many models with no provider.)
    - ``stream``: left at its default, false.

Answer
    ``choices[0].message.content`` (string or null), ``choices[0].finish_reason``, and
    ``model``: the model that answered.

Errors
    ``{"error": {"code": <int>, "message": <str>, "metadata"?: {...}}}`` with the same HTTP
    status: 400 bad request, 401 bad or disabled key, 402 no credits, 403 refused (moderation,
    guardrail), 408 timed out, 429 rate limited, 502 the model is down or answered badly,
    503 no provider meets the routing rules. The reference also lists 404, 413, 422, 500,
    524 and 529. An error can also arrive with HTTP 200 (no ``choices``, or
    ``finish_reason: "error"``), so the body is always checked.
    TODO(verify): the exact wording of a real 503 for ``data_collection: "deny"``.
"""

from dataclasses import dataclass
from typing import Any, Final

import httpx

from blunderbook.core.explain import Prompt
from blunderbook.sources.base import USER_AGENT, redact

URL: Final = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT: Final = httpx.Timeout(90.0, connect=10.0)
TEMPERATURE: Final = 0.2
MAX_COMPLETION_TOKENS: Final = 1000
LONGEST_DETAIL: Final = 300  # characters of OpenRouter's own message shown with an error


class AiError(Exception):
    """An explanation that couldn't be written. The message is plain and holds no key."""


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    model: str  # the model that answered, as OpenRouter names it


def explain(
    prompt: Prompt, *, key: str, model: str, transport: httpx.BaseTransport | None = None
) -> Answer:
    """Ask ``model`` to explain. Raises AiError. ``transport`` is for tests."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
        "temperature": TEMPERATURE,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "provider": {"data_collection": "deny"},
    }
    headers = {"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT) as client:
            response = client.post(URL, json=body, headers=headers)
    except httpx.TimeoutException:
        raise AiError("OpenRouter didn't answer in time. Try again.") from None
    except httpx.HTTPError as exc:
        raise AiError(redact(f"Can't reach OpenRouter: {exc}", key)) from None
    return _answer(response, key=key, model=model)


def _answer(response: httpx.Response, *, key: str, model: str) -> Answer:
    try:
        data: Any = response.json()
    except ValueError:
        if response.status_code != 200:
            raise AiError(_problem(response.status_code, "", model)) from None
        raise AiError("OpenRouter's answer couldn't be read. Try again.") from None
    if not isinstance(data, dict):
        raise AiError("OpenRouter's answer couldn't be read. Try again.")

    error = data.get("error")
    if response.status_code != 200 or error is not None:
        code, detail = response.status_code, ""
        if isinstance(error, dict):
            if isinstance(error.get("code"), int) and response.status_code == 200:
                code = error["code"]
            if isinstance(error.get("message"), str):
                detail = redact(error["message"], key).strip()[:LONGEST_DETAIL]
        raise AiError(_problem(code, detail, model))

    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(choice, dict):
        raise AiError("OpenRouter's answer had no text. Try again.")
    message = choice.get("message")
    text = message.get("content") if isinstance(message, dict) else None
    finish = choice.get("finish_reason")
    if finish == "error":
        raise AiError(f"{model} stopped with an error. Try again, or pick another model.")
    if not isinstance(text, str) or not text.strip():
        raise AiError(
            f"{model} sent no text. A model that thinks first can use up its space: "
            "try again, or pick another model."
        )
    answered = data.get("model")
    return Answer(text.strip(), answered if isinstance(answered, str) and answered else model)


def _problem(code: int, detail: str, model: str) -> str:
    """A plain message for an OpenRouter error."""
    said = f" OpenRouter says: {detail}" if detail else ""
    match code:
        case 401:
            return "OpenRouter didn't accept your key. Set it again with: blunderbook ai set-key"
        case 402:
            return "Your OpenRouter account is out of credits. Add some on openrouter.ai."
        case 403:
            return f"OpenRouter refused this request.{said}"
        case 408 | 524:
            return f"{model} took too long. Try again."
        case 429:
            return "OpenRouter is busy, or you've hit a rate limit. Try again in a minute."
        case 502 | 529:
            return f"{model} is down or answered badly. Try again, or pick another model."
        case 503:
            return (
                f"No provider for {model} is available that doesn't keep your data. "
                f"Try again later, or pick another model.{said}"
            )
        case 400 | 404 | 422:
            return (
                f"OpenRouter refused the request for {model}.{said} "
                "Check the model id with: blunderbook ai show"
            )
        case _:
            return f"OpenRouter answered with an error (HTTP {code}).{said}"
