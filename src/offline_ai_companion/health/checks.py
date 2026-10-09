
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import sounddevice as sd

from offline_ai_companion import config
from offline_ai_companion.health.report import (
    HealthReport,
    HealthStatus,
)


class HealthChecker:
    """Perform offline-first application readiness checks."""

    def __init__(
        self,
        host: str = config.OLLAMA_HOST,
        model: str = config.OLLAMA_MODEL,
        whisper_executable: Path = config.WHISPER_EXECUTABLE,
        whisper_model: Path = config.WHISPER_MODEL_PATH,
        piper_executable: Path = config.PIPER_EXECUTABLE,
        piper_model: Path = config.PIPER_MODEL_PATH,
        database_path: Path = config.DATABASE_PATH,
        microphone_enabled: bool = config.MIC_ENABLED,
        storage_path: Path = config.PROJECT_ROOT,
        minimum_free_mb: int = 100,
        http_client: httpx.Client | None = None,
    ) -> None:
        if minimum_free_mb < 0:
            raise ValueError(
                "Minimum free storage cannot be negative."
            )

        self.host = host.rstrip("/")
        self.model = model
        self.whisper_executable = Path(whisper_executable)
        self.whisper_model = Path(whisper_model)
        self.piper_executable = Path(piper_executable)
        self.piper_model = Path(piper_model)
        self.database_path = Path(database_path)
        self.microphone_enabled = microphone_enabled
        self.storage_path = Path(storage_path)
        self.minimum_free_mb = minimum_free_mb
        self.http_client = http_client

    def check_ollama(self, report: HealthReport) -> None:
        """Check the local Ollama server and configured model."""

        parsed = urlsplit(self.host)

        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            report.add(
                "Ollama",
                HealthStatus.FAIL,
                "Health checks require a loopback Ollama URL.",
            )
            return

        try:
            if self.http_client is not None:
                response = self.http_client.get(
                    f"{self.host}/api/tags",
                    timeout=3.0,
                )
            else:
                with httpx.Client(
                    timeout=3.0,
                    trust_env=False,
                ) as client:
                    response = client.get(
                        f"{self.host}/api/tags"
                    )

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Invalid Ollama response.")

            models = data.get("models")

            if not isinstance(models, list):
                raise ValueError("Missing model list.")

            available = [
                item.get("name")
                for item in models
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
            ]

            if self.model in available:
                report.add(
                    "Ollama",
                    HealthStatus.PASS,
                    f"Server reachable; model {self.model} available.",
                )
            else:
                report.add(
                    "Ollama",
                    HealthStatus.FAIL,
                    f"Configured model {self.model} not found.",
                )

        except (
            httpx.HTTPError,
            ValueError,
            OSError,
        ) as exc:
            report.add(
                "Ollama",
                HealthStatus.FAIL,
                f"Local server check failed: {exc}",
            )

    def check_file(
        self,
        report: HealthReport,
        name: str,
        path: Path,
    ) -> None:
        """Check that a required file exists and is readable."""

        try:
            if not path.is_file():
                report.add(
                    name,
                    HealthStatus.FAIL,
                    f"File not found: {path}",
                )
                return

            with path.open("rb") as file:
                file.read(1)

            report.add(
                name,
                HealthStatus.PASS,
                f"Found: {path}",
            )

        except OSError as exc:
            report.add(
                name,
                HealthStatus.FAIL,
                f"Cannot read file: {exc}",
            )

    def check_audio(self, report: HealthReport) -> None:
        """Check availability of default audio devices."""

        if not self.microphone_enabled:
            report.add(
                "Microphone",
                HealthStatus.WARN,
                "Microphone disabled in configuration.",
                required=False,
            )
        else:
            try:
                device = sd.query_devices(kind="input")
                channels = int(device["max_input_channels"])

                if channels < 1:
                    raise RuntimeError(
                        "No input channels available."
                    )

                sd.check_input_settings(
                    samplerate=16000,
                    channels=1,
                    dtype="float32",
                )

                report.add(
                    "Microphone",
                    HealthStatus.PASS,
                    f"Available: {device['name']}",
                )

            except (sd.PortAudioError, ValueError, RuntimeError) as exc:
                report.add(
                    "Microphone",
                    HealthStatus.FAIL,
                    str(exc),
                )

        try:
            device = sd.query_devices(kind="output")

            if int(device["max_output_channels"]) < 1:
                raise RuntimeError(
                    "No output channels available."
                )

            report.add(
                "Speaker",
                HealthStatus.PASS,
                f"Available: {device['name']}",
            )

        except (sd.PortAudioError, ValueError, RuntimeError) as exc:
            report.add(
                "Speaker",
                HealthStatus.FAIL,
                str(exc),
            )

    def check_database(self, report: HealthReport) -> None:
        """Check SQLite accessibility without modifying stored data."""

        path = self.database_path

        if not path.is_file():
            report.add(
                "SQLite",
                HealthStatus.FAIL,
                f"Database does not exist: {path}",
            )
            return

        try:
            connection = sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=3,
            )

            try:
                connection.execute("SELECT 1").fetchone()

                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table'"
                    )
                }

                required_tables = {
                    "facts",
                    "notes",
                    "tasks",
                    "reminders",
                }

                missing = required_tables - tables

                if missing:
                    report.add(
                        "SQLite",
                        HealthStatus.FAIL,
                        "Missing tables: "
                        + ", ".join(sorted(missing)),
                    )
                else:
                    report.add(
                        "SQLite",
                        HealthStatus.PASS,
                        "Database readable; required tables present.",
                    )
            finally:
                connection.close()

        except (sqlite3.Error, OSError, ValueError) as exc:
            report.add(
                "SQLite",
                HealthStatus.FAIL,
                f"Database check failed: {exc}",
            )

    def check_storage(self, report: HealthReport) -> None:
        """Check disk capacity and directory writability."""

        try:
            if not self.storage_path.is_dir():
                raise OSError(
                    f"Storage directory missing: {self.storage_path}"
                )

            free_mb = (
                shutil.disk_usage(self.storage_path).free
                / (1024 * 1024)
            )

            if free_mb < self.minimum_free_mb:
                report.add(
                    "Storage",
                    HealthStatus.FAIL,
                    f"Only {free_mb:.1f} MB available.",
                )
                return

            with tempfile.TemporaryFile(
                dir=self.storage_path
            ) as file:
                file.write(b"health-check")
                file.flush()

            report.add(
                "Storage",
                HealthStatus.PASS,
                f"{free_mb:.1f} MB free; directory writable.",
            )

        except OSError as exc:
            report.add(
                "Storage",
                HealthStatus.FAIL,
                f"Storage check failed: {exc}",
            )

    def run(self) -> HealthReport:
        """Execute all application health checks."""

        report = HealthReport()

        self.check_ollama(report)

        self.check_file(
            report,
            "Whisper executable",
            self.whisper_executable,
        )
        self.check_file(
            report,
            "Whisper model",
            self.whisper_model,
        )
        self.check_file(
            report,
            "Piper executable",
            self.piper_executable,
        )
        self.check_file(
            report,
            "Piper model",
            self.piper_model,
        )

        self.check_audio(report)
        self.check_database(report)
        self.check_storage(report)

        return report
