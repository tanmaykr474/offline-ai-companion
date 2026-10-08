
from unittest.mock import Mock

import httpx
import pytest

from offline_ai_companion.llm.ollama import OllamaLLM


def make_client(status=200, body=None):
    client = Mock(spec=httpx.Client)
    response = Mock(spec=httpx.Response)
    response.status_code = status
    response.json.return_value = body
    response.raise_for_status.side_effect = (
        httpx.HTTPStatusError(
            "HTTP error",
            request=httpx.Request(
                "POST",
                "http://localhost:11434/api/generate",
            ),
            response=httpx.Response(status),
        )
        if status >= 400
        else None
    )
    client.post.return_value = response
    return client


def test_successful_generation():
    client = make_client(
        body={"response": "Hello from local AI!"}
    )

    llm = OllamaLLM(client=client)
    result = llm.generate("Hello")

    assert result == "Hello from local AI!"
    assert client.post.call_args.kwargs["json"]["stream"] is False


def test_empty_prompt():
    client = make_client()
    llm = OllamaLLM(client=client)

    with pytest.raises(ValueError):
        llm.generate("   ")

    client.post.assert_not_called()


def test_empty_model_response():
    client = make_client(body={"response": ""})
    llm = OllamaLLM(client=client)

    with pytest.raises(RuntimeError, match="empty response"):
        llm.generate("Hello")


def test_http_error():
    client = make_client(status=500)
    llm = OllamaLLM(client=client)

    with pytest.raises(RuntimeError, match="HTTP error"):
        llm.generate("Hello")


def test_connection_error():
    client = make_client()
    client.post.side_effect = httpx.ConnectError(
        "Connection refused"
    )

    llm = OllamaLLM(client=client)

    with pytest.raises(
        RuntimeError,
        match="Cannot connect",
    ):
        llm.generate("Hello")
