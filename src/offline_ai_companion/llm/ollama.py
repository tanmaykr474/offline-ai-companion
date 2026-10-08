
import httpx

from offline_ai_companion.config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
)


class OllamaLLM:
    """Local Ollama language model client."""

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.client = client

    def generate(self, prompt: str) -> str:
        """Generate a text response using the local model."""

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

        try:
            if self.client is not None:
                response = self.client.post(
                    f"{self.host}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
            else:
                with httpx.Client(
                    timeout=self.timeout,
                    trust_env=False,
                ) as client:
                    response = client.post(
                        f"{self.host}/api/generate",
                        json=payload,
                    )

            response.raise_for_status()
            data = response.json()

            text = data.get("response")

            if not isinstance(text, str) or not text.strip():
                raise RuntimeError(
                    "Ollama returned an empty response."
                )

            return text.strip()

        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Ollama HTTP error: "
                f"{exc.response.status_code}"
            ) from exc

        except httpx.RequestError as exc:
            raise RuntimeError(
                "Cannot connect to Ollama. "
                "Check that the local server is running."
            ) from exc
