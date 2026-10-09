"""Verify bootstrap behavior in fresh processes, before configuration imports."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("settings", [
    {"NOVA_EXPERIMENTAL_INTERRUPTION": "true", "NOVA_SPOKEN_INTERRUPTION": "true"},
    {"NOVA_PROFILE": "raspberry-pi", "WHISPER_THREADS": "invalid", "MIC_ENABLED": "false"},
    {"NOVA_ONLINE_TOOLS_ENABLED": "true", "PASSIVE_MEMORY_ENABLED": "true",
     "OLLAMA_HOST": "http://external.invalid", "NEWS_API_KEY": "test-credential"},
])
def test_fresh_test_process_ignores_inherited_runtime_settings(tmp_path, settings):
    live = tmp_path / "live.env"
    live.write_text("NOVA_EXPERIMENTAL_INTERRUPTION=true\nMIC_ENABLED=false\nNEWS_API_KEY=test-secret\n")
    environment = dict(os.environ, **settings, NOVA_ENV_FILE=str(live), DATABASE_PATH=str(tmp_path / "live.db"))
    environment["PYTHONPATH"] = str(ROOT / "src")
    code = '''
import json, runpy
bootstrap = runpy.run_path("tests/conftest.py")
from offline_ai_companion import config
from offline_ai_companion.tools.online_tools import OnlineConfig
print(json.dumps({"experimental": config.NOVA_EXPERIMENTAL_INTERRUPTION,
                  "spoken": config.NOVA_SPOKEN_INTERRUPTION,
                  "passive": config.PASSIVE_MEMORY_ENABLED,
                  "microphone": config.MIC_ENABLED,
                  "online": OnlineConfig.from_env().enabled,
                  "key": config.NEWS_API_KEY,
                  "database": str(config.DATABASE_PATH)}))
bootstrap["pytest_unconfigure"](None)
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert not any(report[key] for key in ("experimental", "spoken", "passive", "online"))
    assert report["microphone"] is True
    assert report["key"] == ""
    assert Path(report["database"]) != tmp_path / "live.db"
    assert not (tmp_path / "live.db").exists()
    assert live.read_text().startswith("NOVA_EXPERIMENTAL_INTERRUPTION=true")


def test_original_failure_passes_with_interruption_exported():
    environment = dict(os.environ, NOVA_EXPERIMENTAL_INTERRUPTION="true", NOVA_SPOKEN_INTERRUPTION="true")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q",
        "tests/integration/test_software_mute.py::test_microphone_disabled_configuration_initializes_muted_application"],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
