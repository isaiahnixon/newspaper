from __future__ import annotations

import json
import os
from dataclasses import dataclass
import time

import requests

from .config import DailyPaperConfig


class OpenAIError(RuntimeError):
    pass


@dataclass
class OpenAIClient:
    api_key: str
    model: str
    timeout: int = 30
    temperature: float | None = None
    max_retries: int = 2
    retry_backoff: float = 1.0
    dry_run: bool = False
    test_mode: bool = False

    def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        # Honor dry-run/test-mode flags to avoid network calls (and cost).
        if self.dry_run or self.test_mode:
            return "Summary skipped (dry run/test mode enabled)."
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

        # Retry only on transient network errors or rate/5xx responses.
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=self.timeout,
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise OpenAIError("OpenAI API request timed out") from exc
                time.sleep(self.retry_backoff * (2**attempt))
                continue

            if response.status_code == 200:
                data = response.json()
                try:
                    return data["choices"][0]["message"]["content"].strip()
                except (KeyError, IndexError, TypeError) as exc:
                    raise OpenAIError("Unexpected OpenAI response format") from exc

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                time.sleep(self.retry_backoff * (2**attempt))
                continue

            raise OpenAIError(
                f"OpenAI API error {response.status_code}: {response.text[:200]}"
            )

        raise OpenAIError("OpenAI API request failed after retries")


def get_client(config: DailyPaperConfig, model: str) -> OpenAIClient:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIError("OPENAI_API_KEY is not set")
    return OpenAIClient(
        api_key=api_key,
        model=model,
        timeout=config.request_timeout,
        temperature=config.temperature,
        max_retries=config.max_retries,
        retry_backoff=config.retry_backoff,
        dry_run=config.dry_run,
        test_mode=config.test_mode,
    )
