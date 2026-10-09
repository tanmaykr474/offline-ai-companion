
import time
from urllib.parse import urlsplit

import httpx
from offline_ai_companion.llm.local_endpoint import local_endpoint
from offline_ai_companion.core.performance import timed
from offline_ai_companion.core.privacy_policy import model_text
from offline_ai_companion.core.cancellation import check_cancel, current_cancel, cancellable_wait

from offline_ai_companion.config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
    NOVA_OLLAMA_NUM_CTX,
    NOVA_OLLAMA_NUM_THREAD,
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

        self.host = local_endpoint(host)
        parsed = urlsplit(host)
        self._localhost_origin = self.host if parsed.hostname.lower().rstrip(".") == "localhost" else None
        self._localhost_authority = parsed.netloc.lower()
        self.model = model
        self.timeout = timeout
        self.client = client
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _send_request(self, payload: dict) -> httpx.Response:
        """Send a request using an injected or temporary client."""

        url = f"{local_endpoint(self.host)}/api/generate"
        options = {}
        if self.host == self._localhost_origin:
            options["headers"] = {"Host": self._localhost_authority}
            if url.startswith("https:"):
                # Connect to a literal loopback address but retain TLS identity.
                options["extensions"] = {"sni_hostname": "localhost"}

        if self.client is not None:
            if issubclass(type(self.client), httpx.Client):
                # A supplied client must not route prompts through a proxy or
                # rewrite requests with hooks/auth. Mock transports remain usable.
                if (self.client.trust_env is True
                        or any(transport is not None for transport in self.client._mounts.values())
                        or self.client.event_hooks.get("request")
                        or self.client.auth is not None):
                    raise ValueError("Injected Ollama clients must disable environment proxies, mounts, request hooks and auth.")
            return self.client.post(
                url,
                json=payload,
                timeout=self.timeout,
                follow_redirects=False,
                **options,
            )

        with httpx.Client(
            timeout=self.timeout,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            return client.post(
                url,
                json=payload,
                **options,
            )

    @timed("ollama_response")
    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.4,
        num_predict: int = 160,
        json_mode: bool = False,
    ) -> str:
        """Generate a response with bounded retries."""

        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        prompt = model_text(prompt)

        payload = {
            "model": self.model,
            "prompt": prompt.strip(),
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }

        if NOVA_OLLAMA_NUM_CTX is not None:
            payload["options"]["num_ctx"] = NOVA_OLLAMA_NUM_CTX
        if NOVA_OLLAMA_NUM_THREAD is not None:
            payload["options"]["num_thread"] = NOVA_OLLAMA_NUM_THREAD

        if json_mode:
            payload["format"] = "json"

        for attempt in range(self.max_retries + 1):
            check_cancel()
            try:
                response = self._send_request(payload)
                check_cancel()
                if 300 <= response.status_code < 400:
                    raise RuntimeError("Ollama redirects are blocked by local-only policy.")
                response.raise_for_status()

                try:
                    data = response.json()
                except ValueError as exc:
                    raise RuntimeError(
                        "Ollama returned invalid JSON."
                    ) from None

                if not isinstance(data, dict):
                    raise RuntimeError(
                        "Ollama returned an invalid response format."
                    )

                text = data.get("response")

                if not isinstance(text, str) or not text.strip():
                    raise RuntimeError(
                        "Ollama returned an empty response."
                    )

                return model_text(text.strip())

            except httpx.TimeoutException as exc:
                check_cancel()
                if attempt < self.max_retries:
                    cancel = current_cancel()
                    if cancel is None:
                        time.sleep(self.retry_delay)
                    elif cancel.wait(self.retry_delay):
                        check_cancel()
                    continue

                raise RuntimeError(
                    "Ollama request timed out. "
                    "The local model may be busy."
                ) from None

            except httpx.HTTPStatusError as exc:
                check_cancel()
                status = exc.response.status_code

                # Retry only temporary server failures.
                if status in (502, 503, 504) and attempt < self.max_retries:
                    cancellable_wait(self.retry_delay)
                    continue

                raise RuntimeError(
                    f"Ollama HTTP error: {status}"
                ) from None

            except httpx.RequestError as exc:
                check_cancel()
                if (
                    isinstance(exc, httpx.ConnectError)
                    and attempt < self.max_retries
                ):
                    cancellable_wait(self.retry_delay)
                    continue

                raise RuntimeError(
                    "Cannot connect to Ollama. "
                    "Check that the local server is running."
                ) from None

        raise RuntimeError("Ollama generation failed.")
