"""
LLM client used by the chat assistant and the mapping-sheet AI fallback.

Every call goes through the generic OpenAI SDK against an OpenAI-compatible
endpoint (Ollama, vLLM, LiteLLM, Azure/OpenAI, a corporate gateway, ...):

    client = OpenAI(base_url=..., api_key=..., default_headers=...)
    client.chat.completions.create(model=..., messages=[...])

Settings come from the UI (Settings → LLM API); anything left blank there
falls back to backend/.env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
Running server-side also sidesteps the browser CORS restriction.
"""
from __future__ import annotations

import json
import os
import re

import openai
from openai import AsyncOpenAI

from app.models.schemas import LlmProviderConfig

TIMEOUT_S = 180
MAX_TOKENS = 4096
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class LlmError(RuntimeError):
    pass


def _headers(config: LlmProviderConfig) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in config.custom_headers:
        name = h.name.strip()
        if not name:
            continue
        if not _HEADER_NAME_RE.match(name):
            raise LlmError(f"Invalid header name '{name}' (letters, digits and - only).")
        if "\n" in h.value or "\r" in h.value:
            raise LlmError(f"Header '{name}' value must be a single line.")
        out[name] = h.value
    return out


async def call_llm(prompt: str, config: LlmProviderConfig) -> str:
    base_url = (config.custom_url or os.environ.get("LLM_BASE_URL", "")).strip()
    api_key = (config.custom_key or os.environ.get("LLM_API_KEY", "")).strip() or "dummy"
    model = (config.custom_model or os.environ.get("LLM_MODEL", "")).strip()
    if not base_url:
        raise LlmError("No LLM base URL. Set it in Settings → LLM API (e.g. http://localhost:11434/v1) "
                       "or LLM_BASE_URL in backend/.env.")
    if not model:
        raise LlmError("No model name. Set it in Settings → LLM API or LLM_MODEL in backend/.env.")

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, default_headers=_headers(config),
                         timeout=TIMEOUT_S, max_retries=1)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
        )
    except openai.AuthenticationError as exc:
        raise LlmError(f"LLM API rejected the credentials (401): {_detail(exc)}") from exc
    except openai.PermissionDeniedError as exc:
        raise LlmError(f"LLM API denied access (403): {_detail(exc)}") from exc
    except openai.NotFoundError as exc:
        raise LlmError(f"Not found (404) at {base_url.rstrip('/')}/chat/completions — check the base URL and "
                       f"model '{model}': {_detail(exc)}") from exc
    except openai.RateLimitError as exc:
        raise LlmError(f"LLM API rate limit (429): {_detail(exc)}") from exc
    except openai.APIStatusError as exc:
        raise LlmError(f"LLM API returned {exc.status_code}: {_detail(exc)}") from exc
    except openai.APITimeoutError as exc:
        raise LlmError(f"LLM API timed out after {TIMEOUT_S}s ({base_url}).") from exc
    except openai.APIConnectionError as exc:
        raise LlmError(f"Could not reach {base_url} (network / proxy / SSL): {exc}") from exc
    finally:
        await client.close()

    choice = response.choices[0] if response.choices else None
    text = (choice.message.content if choice and choice.message else None) or ""
    if choice and choice.finish_reason == "length" and not text.strip():
        raise LlmError("LLM response was cut off (max tokens) — try fewer rows at a time.")
    return text


def _detail(exc: openai.APIStatusError) -> str:
    body = exc.body
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        return str(err)[:300]
    return (exc.message or str(exc))[:300]


def extract_json(raw: str):
    """Parses the first JSON object/array in an LLM reply, tolerating code
    fences and stray prose around it."""
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if starts:
        start = min(starts)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise LlmError(f"LLM returned unparsable JSON: {raw[:200]}")
