#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
python3 -c 'import sys; assert sys.version_info[:2] == (3,13)'
test -x "$NOVA_ROOT/.venv/bin/python"
sudo apt-get update
sudo apt-get install -y python3-gpiozero python3-lgpio gpiod
getent group gpio >/dev/null
getent group audio >/dev/null
sudo usermod -a -G gpio,audio "$(id -un)"
# Explicitly expose distro-built Python 3.13 ARM64 lgpio to this existing venv.
# Venv packages retain precedence; no existing Python package is upgraded here.
"$NOVA_ROOT/.venv/bin/python" - "$NOVA_ROOT/.venv/pyvenv.cfg" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
lines = path.read_text().splitlines()
assert any(line.startswith('include-system-site-packages') for line in lines)
lines = ['include-system-site-packages = true' if line.startswith('include-system-site-packages') else line for line in lines]
path.write_text('\n'.join(lines) + '\n')
PY
"$NOVA_ROOT/.venv/bin/python" -c 'from offline_ai_companion.core.hardware import validate_gpio_dependencies; assert validate_gpio_dependencies(), "Unsupported GPIO dependencies"'
echo 'GPIO dependencies installed. Re-login for group membership; inspect chip and wiring before enabling.'
