from unittest.mock import Mock

import httpx
import pytest

from offline_ai_companion.llm.ollama import OllamaLLM


@pytest.mark.parametrize("host", [
    "http://example.com:11434", "http://localhost.example.com", "http://localhost@evil.example",
    "http://user:secret@localhost", "http://192.168.1.2", "http://10.0.0.1", "http://8.8.8.8",
    "http://0.0.0.0", "http://[::]", "http://[2001:db8::1]", "http://[fe80::1]",
    "http://[::ffff:8.8.8.8]", "http://[::1%25lo0]", "http://2130706433", "http://127.1",
    "http://0x7f000001", "http://0177.0.0.1", "ftp://localhost", "http://localhost/api",
    "http://localhost?target=evil", "http://localhost#evil", "http://localhost:0",
    "http://localhost:65536", "http://localhost\n", "http://localhost\\@evil", "", None,
])
def test_nonlocal_or_ambiguous_configuration_fails_before_transmission(host):
    client = Mock(spec=httpx.Client)
    with pytest.raises(ValueError, match="loopback"):
        OllamaLLM(host=host, client=client)
    client.post.assert_not_called()


@pytest.mark.parametrize("host,expected", [
    ("http://localhost:11434/", "http://127.0.0.1:11434"),
    ("http://LOCALHOST.:11434", "http://127.0.0.1:11434"),
    ("https://127.0.0.1:11434", "https://127.0.0.1:11434"),
    ("http://127.0.0.2", "http://127.0.0.2"),
    ("http://127.255.255.254", "http://127.255.255.254"),
    ("http://[::1]:11434", "http://[::1]:11434"),
    ("http://[0:0:0:0:0:0:0:1]", "http://[::1]"),
    ("http://[::ffff:127.0.0.1]", "http://127.0.0.1"),
])
def test_legitimate_loopback_addresses_are_canonicalized(host, expected):
    assert OllamaLLM(host=host).host == expected


def test_host_mutation_is_rechecked_before_each_request():
    client = Mock(spec=httpx.Client)
    model = OllamaLLM(client=client)
    model.host = "http://evil.example"
    with pytest.raises(ValueError, match="loopback"):
        model.generate("private prompt")
    client.post.assert_not_called()


@pytest.mark.parametrize("location", ["http://evil.example", "http://192.168.1.2", "http://[2001:db8::1]", "http://127.0.0.1:9999"])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirects_never_forward_prompts_even_with_redirect_enabled_client(location, status):
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(status, headers={"location": location})

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False, follow_redirects=True) as client:
        model = OllamaLLM(client=client)
        with pytest.raises(RuntimeError, match="redirects are blocked"):
            model.generate("private prompt")
    assert len(seen) == 1
    assert seen[0].url.host == "127.0.0.1"


def test_injected_client_with_proxy_is_rejected_before_sending():
    with httpx.Client(proxy="http://proxy.example:8888", trust_env=False) as client:
        with pytest.raises(ValueError, match="proxies"):
            OllamaLLM(client=client).generate("private prompt")


@pytest.mark.parametrize("options", [
    {"trust_env": True},
    {"trust_env": False, "event_hooks": {"request": [lambda request: None]}},
    {"trust_env": False, "auth": ("user", "password")},
])
def test_injected_client_cannot_rewrite_or_proxy_requests(options):
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request)), **options) as client:
        with pytest.raises(ValueError, match="Injected Ollama clients"):
            OllamaLLM(client=client).generate("private prompt")
    assert requests == []


def test_localhost_is_pinned_and_environment_proxy_ignored(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://evil.example:8888")
    constructor = Mock()
    response = httpx.Response(200, json={"response": "ready"}, request=httpx.Request("POST", "http://127.0.0.1/api/generate"))
    constructor.return_value.__enter__ = Mock(return_value=constructor.return_value)
    constructor.return_value.__exit__ = Mock(return_value=False)
    constructor.return_value.post.return_value = response
    monkeypatch.setattr("offline_ai_companion.llm.ollama.httpx.Client", constructor)
    assert OllamaLLM().generate("synthetic prompt") == "ready"
    assert constructor.call_args.kwargs["trust_env"] is False
    assert constructor.call_args.kwargs["follow_redirects"] is False
    assert constructor.return_value.post.call_args.args[0] == "http://127.0.0.1:11434/api/generate"


def test_https_localhost_retains_tls_identity_without_dns_resolution():
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(200, json={"response": "ready"})

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        assert OllamaLLM(host="https://localhost:11434", client=client).generate("synthetic") == "ready"
    assert seen[0].url.host == "127.0.0.1"
    assert seen[0].headers["host"] == "localhost:11434"
    assert seen[0].extensions["sni_hostname"] == "localhost"
