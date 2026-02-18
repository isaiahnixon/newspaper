from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import DailyPaperConfig
from .utils import get_env

# Path to the mock data file
MOCK_DATA_PATH = Path(__file__).parent / "mock_data.json"

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
    _mock_data: dict | None = None

    def __post_init__(self):
        if self.dry_run:
            self._load_mock_data()

    def _load_mock_data(self):
        if MOCK_DATA_PATH.exists():
            with open(MOCK_DATA_PATH, 'r', encoding='utf-8') as f:
                self._mock_data = json.load(f)
            self._log(f"[dry run] Loaded mock data from {MOCK_DATA_PATH}.")
        else:
            self._log(f"[dry run] No mock data file found at {MOCK_DATA_PATH}.")
            self._mock_data = {}

    def chat_completion(self, system_prompt: str, user_prompt: str, topic: str | None = None) -> str:
        if self.dry_run:
            return self._get_mock_summary(system_prompt, user_prompt, topic)

        self._log(
            "[live call] OpenAI request: model="
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

    def _get_mock_summary(self, system_prompt: str, user_prompt: str, topic: str | None = None) -> str:
        if self._mock_data is None:
            self._load_mock_data()

        if not self._mock_data:
            self._log("[dry run] Mock data is empty or not loaded, returning generic placeholder.")
            return (
                "[dry run] Summary skipped to avoid API usage. "
                "Set DAILY_PAPER_DRY_RUN=0 to enable live calls. "
                "For better dry run data, generate mock_data.json."
            )

        self._log(
            f"[dry run debug] _get_mock_summary called. user_prompt: {user_prompt[:150]}..., "
            f"system_prompt: {system_prompt[:150]}..."
        )

        is_topic_request = "Write the macro summary for" in user_prompt
        is_item_request = (
            "Summarize the following item in one neutral sentence" in user_prompt
            or (
                "Title:" in user_prompt
                and "item in one neutral sentence" in system_prompt.lower()
            )
        )

        if is_topic_request and topic:
            self._log(f"[dry run debug] Using provided topic '{topic}' for mock topic summary lookup.")
            topic_entry = self._mock_data.get(topic)
            if topic_entry and topic_entry.get("topic_summary"):
                self._log(f"[dry run debug] Using mock topic summary for '{topic}'.")
                return topic_entry["topic_summary"]
            self._log(
                f"[dry run debug] Provided topic '{topic}' missing in mock data keys: {list(self._mock_data.keys())}."
            )

        topic_match = re.search(r"Write the macro summary for ([\w\s\.-]+?)\.", user_prompt)
        if is_topic_request and topic_match:
            topic_name = topic_match.group(1).strip()
            self._log(f"[dry run debug] Extracted topic_name for topic summary: '{topic_name}'.")
            if topic_name in self._mock_data:
                self._log(f"[dry run debug] Topic '{topic_name}' found in mock data.")
                if "topic_summary" in self._mock_data[topic_name] and self._mock_data[topic_name]["topic_summary"]:
                    self._log(f"[dry run debug] Using mock topic summary for '{topic_name}'.")
                    return self._mock_data[topic_name]["topic_summary"]
                self._log(f"[dry run debug] Mock topic summary is empty for '{topic_name}'.")
                return f"[dry run] Topic summary for '{topic_name}' (mock data empty)"
            self._log(
                f"[dry run debug] Topic '{topic_name}' NOT found in mock data keys: {list(self._mock_data.keys())}."
            )
            return f"[dry run] Topic summary for '{topic_name}' (mock data missing)"

        title_match = re.search(r"Title: (.+?)\n", user_prompt)
        if is_item_request and title_match:
            item_title = title_match.group(1).strip()
            self._log(f"[dry run debug] Extracted item_title for item summary: '{item_title}'.")

            target_topic = topic
            if target_topic and target_topic in self._mock_data:
                item_summaries = self._mock_data[target_topic].get("item_summaries")
                if item_summaries:
                    hash_val = hash(item_title) % len(item_summaries)
                    mock_item_summary = item_summaries[hash_val]
                    self._log(
                        f"[dry run debug] Using mock item summary for '{item_title}' "
                        f"from topic '{target_topic}'."
                    )
                    return mock_item_summary

            self._log(
                f"[dry run debug] No specific mock item summary found for '{item_title}' "
                f"under topic '{target_topic}', using Lorem Ipsum."
            )
            return (
                "[dry run] Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
                "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat."
            )

        self._log(f"[dry run debug] Falling back to generic placeholder summary for '{self.model}'.")
        return (
            "[dry run] Summary skipped to avoid API usage. "
            "Set DAILY_PAPER_DRY_RUN=0 to enable live calls. "
            "For better dry run data, generate mock_data.json."
        )

    def _post_with_retries(
        self, url: str, headers: dict[str, str], payload: dict[str, object]
    ) -> requests.Response:
        max_attempts = max(self.max_retries, 0) + 1
        retryable_statuses = {429, 500, 502, 503, 504}
        for attempt in range(1, max_attempts + 1):
            try:
                self._log(f"[live call] OpenAI request attempt {attempt} of {max_attempts}.")
                response = requests.post(
                    url,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=self.timeout,
                )
            except requests.exceptions.Timeout:
                self._log(
                    "[live call] OpenAI request timed out "
                    f"(attempt {attempt} of {max_attempts})."
                )
                if not self.retry_on_timeout or attempt == max_attempts:
                    raise
                self._backoff(attempt)
                continue
            except requests.exceptions.ConnectionError:
                self._log(
                    "[live call] OpenAI request connection error "
                    f"(attempt {attempt} of {max_attempts})."
                )
                if attempt == max_attempts:
                    raise
                self._backoff(attempt)
                continue

            if response.status_code in retryable_statuses and attempt != max_attempts:
                self._log(
                    "[live call] OpenAI request retrying due to status "
                    f"{response.status_code} (attempt {attempt} of {max_attempts})."
                )
                self._backoff(attempt)
                continue
            return response
        raise OpenAIError("Failed to reach OpenAI API after retries.")

    def _backoff(self, attempt: int) -> None:
        delay = self.retry_backoff * (2 ** (attempt - 1))
        self._log(f"[live call] OpenAI request backing off for {delay:.1f}s.")
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
