
import time

import httpx

from offline_ai_companion.config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
)


class OllamaLLM:
    """Local Ollama language model client with failure recovery."""

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
        max_retries: int = 1,
        retry_delay: float = 0.5,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Timeout must be positive.")

        if max_retries < 0:
            raise ValueError("Maximum retries cannot be negative.")

        if retry_delay < 0:
            raise ValueError("Retry delay cannot be negative.")

        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.client = client
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _send_request(self, payload: dict) -> httpx.Response:
        """Send a request using an injected or temporary client."""

        url = f"{self.host}/api/generate"

        if self.client is not None:
            return self.client.post(
                url,
                json=payload,
                timeout=self.timeout,
            )

        with httpx.Client(
            timeout=self.timeout,
            trust_env=False,
        ) as client:
            return client.post(
                url,
                json=payload,
            )

    def generate(self, prompt: str) -> str:
        """Generate a response with bounded retries."""

        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        payload = {
            "model": self.model,
            "prompt": prompt.strip(),
            "stream": False,
            "options": {
                "temperature": 0.4,
                "num_predict": 160,
            },
        }

        for attempt in range(self.max_retries + 1):
            try:
                response = self._send_request(payload)
                response.raise_for_status()

                try:
                    data = response.json()
                except ValueError as exc:
                    raise RuntimeError(
                        "Ollama returned invalid JSON."
                    ) from exc

                if not isinstance(data, dict):
                    raise RuntimeError(
                        "Ollama returned an invalid response format."
                    )

                text = data.get("response")

                if not isinstance(text, str) or not text.strip():
                    raise RuntimeError(
                        "Ollama returned an empty response."
                    )

                return text.strip()

            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                    continue

                raise RuntimeError(
                    "Ollama request timed out. "
                    "The local model may be busy."
                ) from exc

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code

                # Retry only temporary server failures.
                if status in (502, 503, 504) and attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                    continue

                raise RuntimeError(
                    f"Ollama HTTP error: {status}"
                ) from exc

            except httpx.RequestError as exc:
                if (
                    isinstance(exc, httpx.ConnectError)
                    and attempt < self.max_retries
                ):
                    time.sleep(self.retry_delay)
                    continue

                raise RuntimeError(
                    "Cannot connect to Ollama. "
                    "Check that the local server is running."
                ) from exc

        raise RuntimeError("Ollama generation failed.")
