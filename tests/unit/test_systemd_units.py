from pathlib import Path
import pytest

from offline_ai_companion.core.systemd_units import render, main

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("root", ["C:/nova", "/home/nova space", "/home/nova\nUser=root", "/tmp/%h", "/home/../root", "/"])
def test_invalid_linux_service_paths_rejected(root):
    with pytest.raises(ValueError):
        render("WorkingDirectory=@ROOT@\nUser=@USER@", root, "nova")


@pytest.mark.parametrize("user", ["root", "nova\nUser=root", "nova;command", "", "user name"])
def test_invalid_or_root_users_rejected(user):
    with pytest.raises(ValueError):
        render("User=@USER@", "/home/nova", user)


def test_rendered_units_use_headless_linux_controls_and_bounded_restart(tmp_path):
    assert main(["--root", "/home/nova/ai-companion", "--user", "nova", "--output-dir", str(tmp_path)]) == 0
    nova = (tmp_path / "nova.service").read_text()
    ollama = (tmp_path / "nova-ollama.service").read_text()
    for unit in (nova, ollama):
        assert "User=nova" in unit and "Restart=on-failure" in unit
        assert "StartLimitBurst=3" in unit and "UMask=0077" in unit
        assert "@ROOT@" not in unit and ".exe" not in unit and "powershell" not in unit.lower()
    assert "--start --headless" in nova
    assert "RestartPreventExitStatus=78" in nova
    assert "KillSignal=SIGTERM" in nova and "KillMode=mixed" in nova
    assert "TimeoutStopSec=infinity" in nova  # Accepted work is not killed by a service deadline.
    assert "SupplementaryGroups=audio gpio" in nova
    assert "nova-ollama.service" in nova
    assert "/bin/bash /home/nova/ai-companion/deployment/raspberry-pi/ollama-serve.sh" in ollama
