from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Any


_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


class GeminiHTTPError(RuntimeError):
    def __init__(self, code: int, body: str, model: str):
        self.code = code
        self.body = body
        self.model = model
        super().__init__(f"Gemini API HTTP {code} for {model}: {body}")


def model_candidates(ai_models: str | Iterable[str]) -> list[str]:
    if isinstance(ai_models, str):
        raw_models = ai_models.split(",")
    else:
        raw_models = []
        for value in ai_models:
            raw_models.extend(str(value).split(","))

    models: list[str] = []
    seen = set()
    for model in (m.strip() for m in raw_models):
        if model and model not in seen:
            models.append(model)
            seen.add(model)
    return models or ["gemini-3.6-flash"]


def generate_content(
    *,
    api_key: str,
    ai_models: str | Iterable[str],
    prompt: str,
    generation_config: dict[str, Any],
    timeout: int,
    logger: logging.Logger,
    label: str,
    max_retries: int = 3,
) -> str:
    last_error: Exception | None = None

    for model_index, model in enumerate(model_candidates(ai_models)):
        for attempt in range(1, max_retries + 1):
            try:
                text = _generate_once(
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    generation_config=generation_config,
                    timeout=timeout,
                )
                if model_index:
                    logger.info(f"   {label} succeeded with fallback model: {model}")
                return text
            except GeminiHTTPError as e:
                last_error = e
                if e.code in _RETRYABLE_HTTP_CODES and attempt < max_retries:
                    delay = min(2 ** attempt, 8)
                    logger.warning(
                        f"{label} model {model} returned HTTP {e.code}; "
                        f"retrying in {delay}s ({attempt}/{max_retries})"
                    )
                    time.sleep(delay)
                    continue
                break

    if last_error:
        raise last_error
    raise RuntimeError("Gemini API call failed before a request was made")


def _generate_once(
    *,
    api_key: str,
    model: str,
    prompt: str,
    generation_config: dict[str, Any],
    timeout: int,
) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise GeminiHTTPError(e.code, body, model) from e

    return data["candidates"][0]["content"]["parts"][0]["text"]
