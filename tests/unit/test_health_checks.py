
import sqlite3
from unittest.mock import Mock, patch

import httpx
import pytest

from offline_ai_companion.health.checks import HealthChecker
from offline_ai_companion.health.report import (
    HealthReport,
    HealthStatus,
)


def make_checker(tmp_path, **overrides):
    settings = {
        "host": "http://localhost:11434",
        "model": "llama3.2:1b",
        "whisper_executable": tmp_path / "whisper.exe",
        "whisper_model": tmp_path / "whisper.bin",
        "piper_executable": tmp_path / "piper.exe",
        "piper_model": tmp_path / "voice.onnx",
        "database_path": tmp_path / "companion.db",
        "storage_path": tmp_path,
        "minimum_free_mb": 0,
    }
    settings.update(overrides)
    return HealthChecker(**settings)


def test_report_ready_when_required_checks_pass():
    report = HealthReport()
    report.add("Ollama", HealthStatus.PASS, "Available")
    report.add(
        "Optional service",
        HealthStatus.WARN,
        "Disabled",
        required=False,
    )

    assert report.ready is True


def test_report_not_ready_on_required_failure():
    report = HealthReport()
    report.add("Whisper", HealthStatus.FAIL, "Missing")

    assert report.ready is False


def test_missing_required_file(tmp_path):
    checker = make_checker(tmp_path)
    report = HealthReport()

    checker.check_file(
        report,
        "Whisper",
        tmp_path / "missing.exe",
    )

    assert report.results[0].status == HealthStatus.FAIL


def test_existing_required_file(tmp_path):
    path = tmp_path / "whisper.exe"
    path.write_bytes(b"test")

    checker = make_checker(tmp_path)
    report = HealthReport()

    checker.check_file(report, "Whisper", path)

    assert report.results[0].status == HealthStatus.PASS


def test_ollama_model_available(tmp_path):
    request = httpx.Request(
        "GET",
        "http://localhost:11434/api/tags",
    )

    response = httpx.Response(
        200,
        json={
            "models": [
                {"name": "llama3.2:1b"},
            ]
        },
        request=request,
    )

    client = Mock()
    client.get.return_value = response

    checker = make_checker(
        tmp_path,
        http_client=client,
    )
    report = HealthReport()

    checker.check_ollama(report)

    assert report.results[0].status == HealthStatus.PASS


def test_ollama_model_missing(tmp_path):
    request = httpx.Request(
        "GET",
        "http://localhost:11434/api/tags",
    )

    response = httpx.Response(
        200,
        json={"models": []},
        request=request,
    )

    client = Mock()
    client.get.return_value = response

    checker = make_checker(
        tmp_path,
        http_client=client,
    )
    report = HealthReport()

    checker.check_ollama(report)

    assert report.results[0].status == HealthStatus.FAIL


def test_ollama_rejects_nonlocal_host(tmp_path):
    client = Mock()
    checker = make_checker(
        tmp_path,
        host="https://example.com",
        http_client=client,
    )

    report = HealthReport()
    checker.check_ollama(report)

    assert report.results[0].status == HealthStatus.FAIL
    client.get.assert_not_called()


def test_sqlite_required_tables_present(tmp_path):
    database_path = tmp_path / "companion.db"

    with sqlite3.connect(database_path) as connection:
        for table in ("facts", "notes", "tasks", "reminders"):
            connection.execute(
                f"CREATE TABLE {table} (id INTEGER)"
            )

    checker = make_checker(tmp_path)
    report = HealthReport()

    checker.check_database(report)

    assert report.results[0].status == HealthStatus.PASS


def test_sqlite_missing_database(tmp_path):
    checker = make_checker(tmp_path)
    report = HealthReport()

    checker.check_database(report)

    assert report.results[0].status == HealthStatus.FAIL
    assert not checker.database_path.exists()


def test_storage_available(tmp_path):
    checker = make_checker(tmp_path)
    report = HealthReport()

    checker.check_storage(report)

    assert report.results[0].status == HealthStatus.PASS


def test_storage_insufficient_space(tmp_path):
    checker = make_checker(
        tmp_path,
        minimum_free_mb=10**12,
    )
    report = HealthReport()

    checker.check_storage(report)

    assert report.results[0].status == HealthStatus.FAIL


def test_microphone_disabled(tmp_path):
    checker = make_checker(
        tmp_path,
        microphone_enabled=False,
    )
    report = HealthReport()

    with patch(
        "offline_ai_companion.health.checks.sd.query_devices"
    ) as query:
        query.return_value = {
            "name": "Test speaker",
            "max_output_channels": 2,
        }

        checker.check_audio(report)

    microphone = next(
        item for item in report.results
        if item.component == "Microphone"
    )

    assert microphone.status == HealthStatus.WARN
    assert microphone.required is False


def test_invalid_minimum_storage(tmp_path):
    with pytest.raises(ValueError):
        make_checker(
            tmp_path,
            minimum_free_mb=-1,
        )
