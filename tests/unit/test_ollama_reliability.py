
from unittest.mock import Mock, patch

import httpx
import pytest

from offline_ai_companion.llm.ollama import OllamaLLM


def make_client():
    return Mock(spec=httpx.Client)


def make_success_response(text="Hello"):
    response = Mock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {"response": text}
    response.raise_for_status.return_value = None
    return response


def test_retries_after_timeout():
    client = make_client()

    client.post.side_effect = [
        httpx.ReadTimeout("Request timed out"),
        make_success_response("Recovered"),
    ]

    llm = OllamaLLM(
        client=client,
        max_retries=1,
        retry_delay=0,
    )

    assert llm.generate("Hello") == "Recovered"
    assert client.post.call_count == 2


def test_timeout_after_retries_exhausted():
    client = make_client()

    client.post.side_effect = httpx.ReadTimeout(
        "Request timed out"
    )

    llm = OllamaLLM(
        client=client,
        max_retries=1,
        retry_delay=0,
    )

    with pytest.raises(RuntimeError, match="timed out"):
        llm.generate("Hello")

    assert client.post.call_count == 2


def test_connection_recovery():
    client = make_client()

    client.post.side_effect = [
        httpx.ConnectError("Connection refused"),
        make_success_response("Connected"),
    ]

    llm = OllamaLLM(
        client=client,
        max_retries=1,
        retry_delay=0,
    )

    assert llm.generate("Hello") == "Connected"


def test_invalid_json():
    client = make_client()

    response = make_success_response()
    response.json.side_effect = ValueError("Invalid JSON")

    client.post.return_value = response

    llm = OllamaLLM(
        client=client,
        retry_delay=0,
    )

    with pytest.raises(RuntimeError, match="invalid JSON"):
        llm.generate("Hello")


def test_invalid_response_format():
    client = make_client()

    response = make_success_response()
    response.json.return_value = ["unexpected"]

    client.post.return_value = response

    llm = OllamaLLM(
        client=client,
        retry_delay=0,
    )

    with pytest.raises(
        RuntimeError,
        match="invalid response format",
    ):
        llm.generate("Hello")


def test_no_retry_on_client_error():
    client = make_client()

    response = Mock(spec=httpx.Response)
    response.status_code = 400

    response.raise_for_status.side_effect = (
        httpx.HTTPStatusError(
            "Bad request",
            request=httpx.Request(
                "POST",
                "http://localhost:11434/api/generate",
            ),
            response=httpx.Response(400),
        )
    )

    client.post.return_value = response

    llm = OllamaLLM(
        client=client,
        max_retries=2,
        retry_delay=0,
    )

    with pytest.raises(RuntimeError, match="HTTP error: 400"):
        llm.generate("Hello")

    assert client.post.call_count == 1


def test_invalid_retry_configuration():
    with pytest.raises(ValueError):
        OllamaLLM(max_retries=-1)

    with pytest.raises(ValueError):
        OllamaLLM(timeout=0)

    with pytest.raises(ValueError):
        OllamaLLM(retry_delay=-1)
