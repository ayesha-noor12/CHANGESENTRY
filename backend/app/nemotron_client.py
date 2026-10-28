"""NVIDIA Nemotron inference through Nebius Token Factory (OpenAI-compatible API)."""
import json
import re
from typing import TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from app.config import env

T = TypeVar("T", bound=BaseModel)


class ModelUnavailable(RuntimeError):
    """Raised when the model is not configured or returns nothing usable."""


def _client() -> OpenAI:
    api_key, base_url = env("NEBIUS_API_KEY"), env("NEBIUS_BASE_URL")
    if not api_key or not base_url or not env("NEBIUS_MODEL"):
        raise ModelUnavailable("NEBIUS_API_KEY, NEBIUS_BASE_URL and NEBIUS_MODEL must be set")
    return OpenAI(api_key=api_key, base_url=base_url, timeout=120, max_retries=1)


def model_name() -> str | None:
    return env("NEBIUS_MODEL")


def complete(messages: list[dict]) -> str:
    try:
        response = _client().chat.completions.create(
            model=env("NEBIUS_MODEL"),
            messages=messages,
            temperature=0.1,
            max_tokens=8192,
        )
    except OpenAIError as exc:
        # Never echo request details: they can contain the key in some client errors.
        raise ModelUnavailable(f"Token Factory request failed: {type(exc).__name__}: {_safe(str(exc))}") from None
    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise ModelUnavailable("The model returned an empty response.")
    return content


def extract_json(text: str) -> dict:
    """Strip reasoning traces / code fences and parse the first JSON object."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[start:end + 1])


def chat_json(system_prompt: str, user_prompt: str, schema: type[T]) -> tuple[T, int]:
    """Call the model and validate against ``schema``, with one bounded retry on bad output."""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    last_error = ""
    for attempt in (1, 2):
        raw = complete(messages)
        try:
            return schema.model_validate(extract_json(raw)), attempt
        except (ValueError, ValidationError) as exc:
            last_error = _safe(str(exc))[:600]
            messages += [
                {"role": "assistant", "content": raw[:4000]},
                {"role": "user", "content": f"That response was not valid JSON for the required schema ({last_error}). "
                                            "Return only the corrected JSON object."},
            ]
    raise ModelUnavailable(f"Model output failed validation twice: {last_error}")


def _safe(message: str) -> str:
    key = env("NEBIUS_API_KEY")
    return message.replace(key, "***") if key else message
