import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from offline_ai_companion.audio.diagnostics import device_inventory, input_format_check, output_format_check, stage, event
from offline_ai_companion.config import _audio_device_setting


def backend():
    instance = Mock()
    instance.default.device = (0, 1)
    instance.query_devices.return_value = [
        {"name": "personal microphone label", "hostapi": 0, "max_input_channels": 2,
         "max_output_channels": 0, "default_samplerate": 48000},
        {"name": "personal speaker label", "hostapi": 1, "max_input_channels": 0,
         "max_output_channels": 2, "default_samplerate": 44100},
    ]
    return instance


def test_device_metadata_omits_names_and_does_not_open_streams():
    audio = backend()
    report = device_inventory(backend=audio)
    assert report["status"] == "ok"
    assert report["devices"][0]["default_input"] and report["devices"][1]["default_output"]
    assert "personal" not in json.dumps(report)
    audio.InputStream.assert_not_called()
    audio.play.assert_not_called()


def test_device_names_require_opt_in():
    assert device_inventory(True, backend())["devices"][0]["name"] == "personal microphone label"


def test_device_enumeration_error_is_sanitized():
    audio = backend()
    audio.query_devices.side_effect = RuntimeError("private device name and transcript")
    assert device_inventory(backend=audio) == {"status": "error", "error_type": "RuntimeError", "devices": []}


@pytest.mark.parametrize("check,method,rate", [(input_format_check, "check_input_settings", 16000),
                                             (output_format_check, "check_output_settings", 22050)])
def test_format_checks_without_capture(check, method, rate):
    audio = backend()
    assert check(7, audio)["status"] == "ok"
    getattr(audio, method).assert_called_once_with(device=7, channels=1, samplerate=rate, dtype="float32")
    audio.InputStream.assert_not_called()
    audio.play.assert_not_called()


@pytest.mark.parametrize("check,method", [(input_format_check, "check_input_settings"),
                                         (output_format_check, "check_output_settings")])
def test_format_failure_does_not_expose_exception(check, method):
    audio = backend()
    getattr(audio, method).side_effect = RuntimeError("private error")
    report = check(7, audio)
    assert report["status"] == "error" and report["error_type"] == "RuntimeError"
    assert "private" not in json.dumps(report)


def test_default_success_diagnostics_are_silent(monkeypatch, capsys):
    monkeypatch.delenv("NOVA_AUDIO_DIAGNOSTICS", raising=False)
    with stage("capture"):
        pass
    event("stream_open")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("name", ["capture", "transcription", "processing", "synthesis", "playback"])
def test_opt_in_stage_reports_duration_without_arguments(name, monkeypatch, capsys):
    monkeypatch.setenv("NOVA_AUDIO_DIAGNOSTICS", "true")
    with stage(name):
        private_text = "never logged"
    output = capsys.readouterr().out
    assert f"stage={name}" in output and "status=ok" in output and "duration_ms=" in output
    assert private_text not in output


@pytest.mark.parametrize("error,status", [(RuntimeError("password is private"), "error"), (KeyboardInterrupt(), "interrupted")])
def test_stage_failure_always_reports_only_category(error, status, monkeypatch, capsys):
    monkeypatch.setenv("NOVA_AUDIO_DIAGNOSTICS", "false")
    with pytest.raises(type(error)):
        with stage("playback"):
            raise error
    output = capsys.readouterr().out
    assert f"status={status}" in output and type(error).__name__ in output
    assert "private" not in output and "password" not in output


def test_diagnostic_labels_are_not_free_text():
    with pytest.raises(ValueError):
        with stage("my private transcript"):
            pass
    with pytest.raises(ValueError):
        event("my private transcript")


@pytest.mark.parametrize("value,expected", [("", None), ("0", 0), ("12", 12)])
def test_device_config(value, expected, monkeypatch):
    monkeypatch.setenv("NOVA_INPUT_DEVICE", value)
    assert _audio_device_setting("NOVA_INPUT_DEVICE") == expected


@pytest.mark.parametrize("value", ["-1", "microphone", "3.5"])
def test_invalid_device_configuration(value, monkeypatch):
    monkeypatch.setenv("NOVA_INPUT_DEVICE", value)
    with pytest.raises(ValueError):
        _audio_device_setting("NOVA_INPUT_DEVICE")


def test_standalone_report_cli_saves_sanitized_json_without_models(tmp_path, monkeypatch, capsys):
    path = Path(__file__).resolve().parents[2] / "scripts" / "audio_diagnostics.py"
    spec = importlib.util.spec_from_file_location("nova_device_report_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "device_inventory", lambda names: {"status": "ok", "devices": []})
    monkeypatch.setattr(module, "input_format_check", lambda device: {"status": "ok"})
    monkeypatch.setattr(module, "output_format_check", lambda device: {"status": "ok"})
    report_path = tmp_path / "report.json"
    assert module.main(["--input-device", "2", "--output-device", "3", "--output", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["input_device"] == 2 and report["output_device"] == 3
    assert report["scope"] == "metadata_and_format_checks_only_not_physical_validation"
    assert not any("path" in key for key in report["local_files"])
    assert "metadata_and_format" in capsys.readouterr().out
