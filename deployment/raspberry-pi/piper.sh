#!/usr/bin/env bash
set -euo pipefail
NOVA_ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
# exec preserves timeout/cancellation ownership of the real Piper subprocess.
exec "$NOVA_ROOT/.venv/bin/python" -m piper "$@"
