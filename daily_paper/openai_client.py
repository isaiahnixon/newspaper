from __future__ import annotations

import json
import os
from dataclasses import dataclass

import requests


class OpenAIError(RuntimeError):
    pass


@dataclass
class OpenAIClient:
    api_key: str
    model: str
    timeout: int = 30

    def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
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
            "temperature": 0.2,
        }
        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise OpenAIError(
                f"OpenAI API error {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIError("Unexpected OpenAI response format") from exc


def get_client(model: str) -> OpenAIClient:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIError("OPENAI_API_KEY is not set")
    return OpenAIClient(api_key=api_key, model=model)
