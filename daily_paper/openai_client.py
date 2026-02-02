from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests

from .config import DailyPaperConfig
from .utils import get_env

class OpenAIError(RuntimeError):
    pass


@dataclass
class OpenAIClient:
    api_key: str
    model: str
    timeout: float = 90.0
    max_retries: int = 1
    retry_backoff: float = 1.0
    retry_on_timeout: bool = False
    dry_run: bool = False
    temperature: float | None = None
    verbose: bool = False

    def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        if self.dry_run:
            if "Macro:" in system_prompt and "Watch:" in system_prompt:
                return (
                    "Macro: Not enough accessible detail to synthesize.\n"
                    "Watch: Next release / official update."
                )
            if "What:" in system_prompt:
                return "What: Details are unclear."
            return (
                "[dry run] Summary skipped to avoid API usage. "
                "Set DAILY_PAPER_DRY_RUN=0 to enable live calls."
            )
        self._log(
            "OpenAI request: model="
            f"{self.model}, timeout={self.timeout}s, "
            f"max_retries={self.max_retries}, retry_on_timeout={self.retry_on_timeout}."
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
                self._log(f"OpenAI request attempt {attempt} of {max_attempts}.")
                response = requests.post(
                    url,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=self.timeout,
                )
            except requests.exceptions.Timeout:
                self._log(
                    "OpenAI request timed out "
                    f"(attempt {attempt} of {max_attempts})."
                )
                if not self.retry_on_timeout or attempt == max_attempts:
                    raise
                self._backoff(attempt)
                continue
            except requests.exceptions.ConnectionError:
                self._log(
                    "OpenAI request connection error "
                    f"(attempt {attempt} of {max_attempts})."
                )
                if attempt == max_attempts:
                    raise
                self._backoff(attempt)
                continue

            if response.status_code in retryable_statuses and attempt != max_attempts:
                self._log(
                    "OpenAI request retrying due to status "
                    f"{response.status_code} (attempt {attempt} of {max_attempts})."
                )
                self._backoff(attempt)
                continue
            return response
        raise OpenAIError("Failed to reach OpenAI API after retries.")

    def _backoff(self, attempt: int) -> None:
        delay = self.retry_backoff * (2 ** (attempt - 1))
        self._log(f"OpenAI request backing off for {delay:.1f}s.")
        time.sleep(delay)

    def _log(self, message: str) -> None:
        if self.verbose:
            print(f"[daily_paper] {message}", flush=True)


def get_client(
    config: DailyPaperConfig,
    model: str,
    temperature: float | None,
) -> OpenAIClient:
    """Build an OpenAI client using config-driven retry and timeout settings."""
    api_key = get_env("OPENAI_API_KEY")
    if not api_key and not config.dry_run:
        raise OpenAIError("OPENAI_API_KEY is not set")
    return OpenAIClient(
        api_key=api_key or "",
        model=model,
        timeout=config.openai_timeout_secs,
        max_retries=config.openai_max_retries,
        retry_backoff=config.openai_retry_backoff_secs,
        retry_on_timeout=config.openai_retry_on_timeout,
        dry_run=config.dry_run,
        temperature=temperature,
        verbose=config.verbose,
    )
