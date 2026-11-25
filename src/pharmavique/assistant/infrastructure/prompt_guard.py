"""`InjectionDetector` over Groq's Llama Prompt Guard 2 (a jailbreak / prompt-injection classifier).

The model answers with one probability. Measured 2026-11-19: an English attack scored 0.9996, an
ordinary Arabic question 0.0004, and an Arabic attack only 0.0066. It is weak in Arabic, which is
why it only adds to the deterministic rules in `assistant.domain.guardrails`.
"""

import httpx

from pharmavique.foundation.http.client import async_client

BASE_URL = "https://api.groq.com/openai/v1"


class GroqPromptGuard:
    def __init__(
        self,
        api_key: str,
        model: str,
        threshold: float = 0.9,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._threshold = threshold
        self._client = client or async_client(timeout=10.0)

    async def is_injection(self, text: str) -> bool:
        response = await self._client.post(
            f"{BASE_URL}/chat/completions",
            headers=self._headers,
            json={"model": self._model, "messages": [{"role": "user", "content": text}]},
        )
        if response.status_code != 200:
            raise RuntimeError(f"prompt guard answered HTTP {response.status_code}")
        content = response.json()["choices"][0]["message"]["content"]
        try:
            score = float(str(content).strip())
        except ValueError as error:
            raise ValueError("prompt guard returned no score") from error
        return score >= self._threshold
