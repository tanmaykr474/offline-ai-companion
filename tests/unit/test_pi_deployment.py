import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from offline_ai_companion.core import pi_deployment as pi
from offline_ai_companion.core.platform_config import project_path, runtime_defaults, optional_integer
from offline_ai_companion.core.privacy import PosixMuteConsole

ROOT = Path(__file__).resolve().parents[2]


def elf(machine=183, elf_class=2):
    data = bytearray(64)
    data[:6] = b"\x7fELF" + bytes([elf_class, 1])
    data[18:20] = machine.to_bytes(2, "little")
    return data


@pytest.fixture
def installation(tmp_path, monkeypatch):
    env_file = tmp_path / "nova.env"
    env_file.write_text((ROOT / "deployment/raspberry-pi/nova.env.example").read_text())
    defaults = runtime_defaults("Linux", "aarch64", "raspberry-pi")
    for key in ("WHISPER_EXECUTABLE", "PIPER_EXECUTABLE", "WHISPER_MODEL_PATH", "PIPER_MODEL_PATH"):
        path = tmp_path / defaults[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(elf() if key == "WHISPER_EXECUTABLE" else b"#!/bin/bash\n" if key == "PIPER_EXECUTABLE" else b"test-model")
    Path(str(tmp_path / defaults["PIPER_MODEL_PATH"]) + ".json").write_text('{"audio":{"sample_rate":22050}}')
    for directory in ("data/audio", "data/private"):
        (tmp_path / directory).mkdir(parents=True)
    # Simulate Linux ownership/modes on Windows; actual permission decisions remain exercised.
    original = Path.stat
    def stat(path, *args, **kwargs):
        result = list(original(path, *args, **kwargs))
        result[0] &= ~0o077
        result[4] = 1000
        return os.stat_result(result)
    monkeypatch.setattr(Path, "stat", stat)
    def run(**kwargs):
        return pi.preflight(tmp_path, env_file, {}, system="Linux", machine="aarch64",
                            python=(3, 13), bits=64, uid=1000,
                            executable=lambda *_: True, importer=lambda _: object(), **kwargs)
    return tmp_path, env_file, run


def statuses(report):
    return {item["check"]: item["status"] for item in report["checks"]}


def test_complete_preflight_does_not_create_database_or_audio(installation):
    root, _, run = installation
    report = run()
    assert report["ok"]
    assert "not_physical" in report["scope"]
    assert not (root / "data/private/companion.db").exists()
    assert list((root / "data/audio").iterdir()) == []


@pytest.mark.parametrize("machine", ["aarch64", "arm64"])
def test_arm64_defaults(machine):
    defaults = runtime_defaults("Linux", machine, "raspberry-pi")
    assert not defaults["WHISPER_EXECUTABLE"].endswith(".exe")
    assert defaults["PIPER_EXECUTABLE"].endswith("piper.sh")


def test_windows_defaults_unchanged():
    defaults = runtime_defaults("Windows", "AMD64")
    assert defaults["WHISPER_EXECUTABLE"] == "deployment/windows/whisper-cpp/Release/whisper-cli.exe"
    assert defaults["PIPER_EXECUTABLE"] == "deployment/windows/piper/piper.exe"


@pytest.mark.parametrize("system,machine,profile", [("Windows", "arm64", "raspberry-pi"),
    ("Linux", "x86_64", "raspberry-pi"), ("Linux", "aarch64", "unknown")])
def test_invalid_platform_profiles_rejected(system, machine, profile):
    with pytest.raises(ValueError):
        runtime_defaults(system, machine, profile)


@pytest.mark.parametrize("value", ["C:/secret/model.bin", "C:\\secret\\model.bin", "\\\\server\\models", "relative\\model.bin"])
def test_windows_paths_rejected_on_linux(tmp_path, value):
    with pytest.raises(ValueError, match="Windows paths"):
        project_path(tmp_path, value, "Linux")


def test_project_relative_and_absolute_paths(tmp_path):
    assert project_path(tmp_path, "models/model.bin", "Linux") == tmp_path / "models/model.bin"
    assert project_path(tmp_path, str(tmp_path / "absolute.bin")) == tmp_path / "absolute.bin"


@pytest.mark.parametrize("value", ["0", "17", "private credential", "1.5"])
def test_limits_fail_without_exposing_values(value):
    with pytest.raises(ValueError) as caught:
        optional_integer("WHISPER_THREADS", 1, 16, {"WHISPER_THREADS": value})
    assert value != "private credential" or value not in str(caught.value)


def test_optional_limits_preserve_unset_defaults():
    assert optional_integer("WHISPER_THREADS", 1, 16, {}) is None
    assert optional_integer("WHISPER_THREADS", 1, 16, {"WHISPER_THREADS": "2"}) == 2


def test_environment_is_data_without_interpolation_or_execution(tmp_path):
    path = tmp_path / "test.env"
    path.write_text('VALUE=${SECRET}\nOLLAMA_MODEL=from-file\nCOMMAND=$(touch should-not-exist)\n')
    env = pi.environment_file(path, {"OLLAMA_MODEL": "explicit", "SECRET": "credential"})
    assert env["VALUE"] == "${SECRET}"
    assert env["OLLAMA_MODEL"] == "explicit"
    assert not (tmp_path / "should-not-exist").exists()
    assert env["NOVA_ENV_FILE"] == str(path.resolve())


@pytest.mark.parametrize("name,value,check", [
    ("OLLAMA_HOST", "http://external.invalid", "loopback_ollama"),
    ("WHISPER_EXECUTABLE", "C:/Windows/model.exe", "whisper_executable"),
    ("PIPER_EXECUTABLE", "missing", "piper_executable"),
    ("NOVA_INPUT_DEVICE", "-1", "nova_input_device"),
    ("NOVA_OUTPUT_DEVICE", "credential-value", "nova_output_device"),
    ("WHISPER_THREADS", "100", "whisper_threads"),
    ("DATABASE_PATH", "C:/private/db", "database_path"),
])
def test_invalid_environment_reports_only_setting_names(installation, name, value, check):
    _, env_file, run = installation
    with env_file.open("a") as stream:
        stream.write(f"\n{name}={value}\n")
    report = run()
    assert not report["ok"]
    assert statuses(report)[check] == "failed"
    assert value not in json.dumps(report)


@pytest.mark.parametrize("data", [elf(62), elf(40, 1), b"MZwindows", b"", elf()[:20]])
def test_whisper_wrong_architecture_or_truncated_executable(installation, data):
    root, _, run = installation
    (root / runtime_defaults("Linux", "aarch64")["WHISPER_EXECUTABLE"]).write_bytes(data)
    assert statuses(run())["whisper_executable"] == "failed"


@pytest.mark.parametrize("key", ["WHISPER_MODEL_PATH", "PIPER_MODEL_PATH"])
def test_empty_model_rejected(installation, key):
    root, _, run = installation
    (root / runtime_defaults("Linux", "aarch64")[key]).write_bytes(b"")
    assert statuses(run())[key.lower()] == "failed"


@pytest.mark.parametrize("contents", ['not json secret', '{"audio":{}}', '{"audio":{"sample_rate":0}}', '{}'])
def test_invalid_voice_config(installation, contents):
    root, _, run = installation
    path = root / runtime_defaults("Linux", "aarch64")["PIPER_MODEL_PATH"]
    Path(str(path) + ".json").write_text(contents)
    report = run()
    assert statuses(report)["piper_voice_config"] == "failed"
    assert "not json secret" not in json.dumps(report)


def test_missing_dependency_sanitized(installation, monkeypatch):
    root, env_file, _ = installation
    def missing(module):
        if module == "onnxruntime":
            raise ImportError("private prompt and password")
        return object()
    report = pi.preflight(root, env_file, {}, system="Linux", machine="arm64", python=(3, 13), uid=1000,
                          importer=missing, executable=lambda *_: True)
    assert statuses(report)["dependency_onnxruntime"] == "failed"
    assert "password" not in json.dumps(report)


@pytest.mark.parametrize("python,bits,uid,expected", [((3, 11), 64, 1000, "python_313"),
    ((3, 14), 64, 1000, "python_313"), ((3, 13), 32, 1000, "linux_arm64"), ((3, 13), 64, 0, "unprivileged_user")])
def test_unsupported_runtime(installation, python, bits, uid, expected):
    root, env_file, _ = installation
    report = pi.preflight(root, env_file, {}, system="Linux", machine="aarch64", python=python,
                          bits=bits, uid=uid, importer=lambda _: object(), executable=lambda *_: True)
    assert statuses(report)[expected] == "failed"


def test_linux_numeric_audio_devices_and_format_failure(installation):
    _, env_file, run = installation
    with env_file.open("a") as stream:
        stream.write("\nNOVA_INPUT_DEVICE=2\nNOVA_OUTPUT_DEVICE=7\n")
    probe = Mock(return_value={"inventory": {"status": "ok"}, "input_format": {"status": "ok"}, "output_format": {"status": "failed"}})
    report = run(audio=probe)
    probe.assert_called_once_with(2, 7)
    assert statuses(report)["audio_formats"] == "failed"


def test_nonlocal_probe_never_called(installation):
    _, env_file, run = installation
    with env_file.open("a") as stream:
        stream.write("\nOLLAMA_HOST=http://external.invalid\n")
    probe = Mock()
    assert not run(model_probe=probe)["ok"]
    probe.assert_not_called()


@pytest.mark.parametrize("status,body", [(200, {"models": [{"name": "llama3.2:1b"}]}),
    (200, {"models": []}), (302, {}), (500, {})])
def test_local_inventory_probe_never_downloads_or_infers(monkeypatch, status, body):
    requests = []
    original = httpx.Client
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"location": "http://external.invalid"})
    def client(**options):
        assert options["trust_env"] is False and options["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handler), **options)
    monkeypatch.setattr(httpx, "Client", client)
    assert pi.ollama_available("http://localhost:11434", "llama3.2:1b") == (status == 200 and bool(body["models"]))
    assert len(requests) == 1 and requests[0].method == "GET"
    assert str(requests[0].url) == "http://127.0.0.1:11434/api/tags"
    assert requests[0].content == b""


def test_failed_startup_never_runs_voice(installation, monkeypatch, capsys):
    _, env_file, _ = installation
    monkeypatch.setattr(pi.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    # Avoid importing audio configuration into the existing Windows test process.
    import runpy
    monkeypatch.setattr(runpy, "run_path", lambda _: {"build_report": Mock()})
    runner = Mock()
    monkeypatch.setattr(pi.os, "environ", dict(os.environ))
    assert pi.main(["--env-file", str(env_file), "--start"], checker=lambda *a, **k: {"ok": False, "checks": []}, runner=runner) == 1
    runner.assert_not_called()
    assert "credential" not in capsys.readouterr().out


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_linux_mute_control_only_accepts_exact_control_lines():
    toggle, interrupt = Mock(), Mock()
    control = PosixMuteConsole(toggle, interrupt, Terminal("private words\nm\nM\ns\n"), lambda _: True)
    control.start()
    control.thread.join(2)
    control.stop()
    assert not control.thread.is_alive()
    assert toggle.call_count == 2
    interrupt.assert_called_once()


def test_linux_mute_rejects_noninteractive_stdin():
    with pytest.raises(RuntimeError, match="Interactive terminal"):
        PosixMuteConsole(Mock(), stream=io.StringIO())


def test_linux_idle_console_stops_without_input():
    control = PosixMuteConsole(Mock(), stream=Terminal(), ready=lambda _: False)
    control.start()
    control.stop()
    assert not control.thread.is_alive()


def test_pi_privacy_defaults():
    env = pi.environment_file(ROOT / "deployment/raspberry-pi/nova.env.example", {})
    for setting in ("MIC_ENABLED", "PASSIVE_MEMORY_ENABLED", "NOVA_ONLINE_TOOLS_ENABLED",
                    "NOVA_EXPERIMENTAL_INTERRUPTION", "NOVA_SPOKEN_INTERRUPTION", "NOVA_RUNTIME_DIAGNOSTICS"):
        assert env[setting] == "false"
    assert env["PASSIVE_MEMORY_RETENTION_DAYS"] == "0"
    assert pi.local_endpoint(env["OLLAMA_HOST"]) == "http://127.0.0.1:11434"


def test_whisper_thread_limit_reaches_cli(tmp_path, monkeypatch):
    from offline_ai_companion.stt import whisper
    paths = [tmp_path / name for name in ("whisper", "model", "input.wav")]
    for path in paths:
        path.write_bytes(b"fixture")
    run = Mock(return_value=SimpleNamespace(stdout="Nova"))
    monkeypatch.setattr(whisper, "run_owned", run)
    assert whisper.WhisperSTT(paths[0], paths[1], threads=2).transcribe(paths[2]) == "Nova"
    assert run.call_args.args[0][-2:] == ["-t", "2"]


def test_ollama_pi_options_preserve_local_request(monkeypatch):
    from offline_ai_companion.llm import ollama
    monkeypatch.setattr(ollama, "NOVA_OLLAMA_NUM_CTX", 1024)
    monkeypatch.setattr(ollama, "NOVA_OLLAMA_NUM_THREAD", 2)
    client = Mock(spec=httpx.Client)
    client.post.return_value = httpx.Response(200, json={"response": "answer"}, request=httpx.Request("POST", "http://127.0.0.1:11434/api/generate"))
    assert ollama.OllamaLLM(client=client).generate("question") == "answer"
    options = client.post.call_args.kwargs["json"]["options"]
    assert options["num_ctx"] == 1024 and options["num_thread"] == 2


@pytest.mark.parametrize("name,mode,owner", [("nova.env", 0o644, 1000), ("nova.env", 0o600, 2000),
    ("data/private", 0o755, 1000), ("data/audio", 0o700, 2000), ("data/private/companion.db", 0o644, 1000)])
def test_permissions_and_ownership_are_checked_without_rewriting(installation, monkeypatch, name, mode, owner):
    root, _, run = installation
    target = root / name
    if name.endswith(".db"):
        target.write_bytes(b"existing data preserved")
    original = Path.stat
    def insecure(path, *args, **kwargs):
        result = list(original(path, *args, **kwargs))
        if path == target:
            result[0] = (result[0] & ~0o777) | mode
            result[4] = owner
        return os.stat_result(result)
    monkeypatch.setattr(Path, "stat", insecure)
    assert not run()["ok"]
    if name.endswith(".db"):
        assert target.read_bytes() == b"existing data preserved"


@pytest.mark.parametrize("name", ["WHISPER_EXECUTABLE", "PIPER_EXECUTABLE", "WHISPER_MODEL_PATH", "PIPER_MODEL_PATH"])
def test_missing_files_fail_clearly(installation, name):
    root, _, run = installation
    (root / runtime_defaults("Linux", "arm64")[name]).unlink()
    assert statuses(run())[name.lower()] == "failed"


@pytest.mark.parametrize("data", [b"not-json credential", b'x' * 65537, b'[]'], ids=["malformed", "oversized", "wrong-shape"])
def test_inventory_malformed_or_oversized_response(monkeypatch, data):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=data)), **kw))
    # Exceptions are sanitized by preflight; oversized responses return False immediately.
    try:
        result = pi.ollama_available("http://127.0.0.1:11434", "llama3.2:1b")
    except (ValueError, AttributeError):
        result = False
    assert result is False


def test_probe_timeout_is_sanitized_by_preflight(installation):
    _, _, run = installation
    def probe(*_):
        raise httpx.ReadTimeout("private content in exception")
    report = run(model_probe=probe)
    assert statuses(report)["ollama_model_available"] == "failed"
    assert "private content" not in json.dumps(report)


def test_console_loss_mutes_without_toggle():
    toggle, mute = Mock(), Mock()
    control = PosixMuteConsole(toggle, stream=Terminal(), ready=lambda _: True, on_unavailable=mute)
    control.start()
    control.thread.join(2)
    control.stop()
    toggle.assert_not_called()
    mute.assert_called_once()


def test_console_read_error_mutes_without_logging(capsys):
    mute = Mock()
    def unavailable(_):
        raise OSError("private console data")
    control = PosixMuteConsole(Mock(), stream=Terminal(), ready=unavailable, on_unavailable=mute)
    control.start()
    control.thread.join(2)
    control.stop()
    mute.assert_called_once()
    assert capsys.readouterr().out == ""


def test_noninteractive_start_refuses_even_valid_preflight(installation, monkeypatch):
    _, env_file, _ = installation
    monkeypatch.setattr(pi.os, "environ", dict(os.environ))
    monkeypatch.setattr(pi.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    import runpy
    monkeypatch.setattr(runpy, "run_path", lambda _: {"build_report": Mock()})
    runner = Mock()
    assert pi.main(["--env-file", str(env_file), "--start"], checker=lambda *a, **k: {"ok": True, "checks": []}, runner=runner) == 1
    runner.assert_not_called()


def test_headless_preflight_validates_dependencies_without_opening_gpio(installation, monkeypatch):
    from offline_ai_companion.core import hardware
    _, env_file, run = installation
    with env_file.open("a") as stream:
        stream.write("\nNOVA_HEADLESS=true\nNOVA_GPIO_BACKEND=lgpio\n")
    monkeypatch.setattr(hardware, "validate_gpio_dependencies", lambda: True)
    opener = Mock(side_effect=AssertionError("Preflight must not acquire GPIO"))
    monkeypatch.setattr(hardware, "LGPIOBackend", opener)
    assert run()["ok"]
    opener.assert_not_called()


@pytest.mark.parametrize("backend,microphone,expected", [("none", "false", "headless_gpio_config"),
    ("mock", "false", "headless_gpio_config"), ("lgpio", "true", "muted_service_startup")])
def test_headless_preflight_rejects_unsafe_controls(installation, monkeypatch, backend, microphone, expected):
    from offline_ai_companion.core import hardware
    _, env_file, run = installation
    with env_file.open("a") as stream:
        stream.write(f"\nNOVA_HEADLESS=true\nNOVA_GPIO_BACKEND={backend}\nMIC_ENABLED={microphone}\n")
    monkeypatch.setattr(hardware, "validate_gpio_dependencies", lambda: True)
    report = run()
    assert not report["ok"] and statuses(report)[expected] == "failed"


def test_headless_start_does_not_require_stdin(installation, monkeypatch):
    _, env_file, _ = installation
    with env_file.open("a") as stream:
        stream.write("\nNOVA_GPIO_BACKEND=lgpio\n")
    import runpy
    monkeypatch.setattr(runpy, "run_path", lambda _: {"build_report": Mock()})
    monkeypatch.setattr(pi.os, "environ", dict(os.environ))
    monkeypatch.setattr(pi.os, "chdir", Mock())
    monkeypatch.setattr(pi.os, "umask", Mock())
    monkeypatch.setattr(pi.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    runner = Mock()
    assert pi.main(["--env-file", str(env_file), "--start", "--headless"],
                   checker=lambda *a, **k: {"ok": True, "checks": []}, runner=runner) == 0
    runner.assert_called_once()


@pytest.mark.parametrize("failure,code", [("configuration", 78), ("gpio_dependencies", 78),
    ("whisper_model_path", 78), ("audio_formats", 75), ("ollama_model_available", 75)])
def test_headless_start_exit_codes_distinguish_permanent_and_temporary(installation, monkeypatch, failure, code):
    _, env_file, _ = installation
    with env_file.open("a") as stream:
        stream.write("\nNOVA_GPIO_BACKEND=lgpio\n")
    import runpy
    monkeypatch.setattr(runpy, "run_path", lambda _: {"build_report": Mock()})
    monkeypatch.setattr(pi.os, "environ", dict(os.environ))
    runner = Mock()
    assert pi.main(["--env-file", str(env_file), "--start", "--headless"],
                   checker=lambda *a, **k: {"ok": False, "checks": [{"check": failure, "status": "failed"}]}, runner=runner) == code
    runner.assert_not_called()
