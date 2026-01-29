from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import requests


class OpenAIError(RuntimeError):
    pass


@dataclass
class OpenAIClient:
    api_key: str
    model: str
    timeout: int = 30
    max_retries: int = 0
    retry_backoff: float = 1.0
    retry_on_timeout: bool = False
    dry_run: bool = False
    temperature: float | None = None

    def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        if self.dry_run:
            return (
                "[dry run] Summary skipped to avoid API usage. "
                "Set DAILY_PAPER_DRY_RUN=0 to enable live calls."
            )
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        response = self._post_with_retries(url, headers, payload)
        if response.status_code != 200:
            raise OpenAIError(
                f"OpenAI API error {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIError("Unexpected OpenAI response format") from exc

    def _post_with_retries(
        self, url: str, headers: dict[str, str], payload: dict[str, object]
    ) -> requests.Response:
        max_attempts = max(self.max_retries, 0) + 1
        retryable_statuses = {429, 500, 502, 503, 504}
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=self.timeout,
                )
            except requests.exceptions.Timeout:
                if not self.retry_on_timeout or attempt == max_attempts:
                    raise
                self._backoff(attempt)
                continue
            except requests.exceptions.ConnectionError:
                if attempt == max_attempts:
                    raise
                self._backoff(attempt)
                continue

            if response.status_code in retryable_statuses and attempt != max_attempts:
                self._backoff(attempt)
                continue
            return response
        raise OpenAIError("Failed to reach OpenAI API after retries.")

    def _backoff(self, attempt: int) -> None:
        delay = self.retry_backoff * (2 ** (attempt - 1))
        time.sleep(delay)


def _env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _env_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def get_client(model: str, temperature: float | None) -> OpenAIClient:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIError("OPENAI_API_KEY is not set")
    timeout = _env_float(os.getenv("OPENAI_TIMEOUT_SECS"))
    # Keep retries disabled by default to avoid unexpected cost spikes.
    max_retries = _env_int(os.getenv("OPENAI_MAX_RETRIES"))
    # Backoff only matters when retries are enabled.
    retry_backoff = _env_float(os.getenv("OPENAI_RETRY_BACKOFF_SECS"))
    # Retrying on timeouts can multiply spend; keep opt-in.
    retry_on_timeout = _env_truthy(os.getenv("OPENAI_RETRY_ON_TIMEOUT"))
    dry_run = _env_truthy(os.getenv("DAILY_PAPER_DRY_RUN")) or _env_truthy(
        os.getenv("OPENAI_DRY_RUN")
    )
    return OpenAIClient(
        api_key=api_key,
        model=model,
        timeout=timeout if timeout is not None else 30,
        max_retries=max_retries if max_retries is not None else 0,
        retry_backoff=retry_backoff if retry_backoff is not None else 1.0,
        retry_on_timeout=retry_on_timeout,
        dry_run=dry_run,
        temperature=temperature,
    )
