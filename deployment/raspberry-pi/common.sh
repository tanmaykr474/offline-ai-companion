#!/usr/bin/env bash
set -euo pipefail
umask 077
NOVA_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
NOVA_PI="$NOVA_ROOT/deployment/raspberry-pi"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != aarch64 ]]; then
    echo 'This provisioning command requires Linux ARM64.' >&2
    exit 1
fi
if [[ "$(id -u)" == 0 ]]; then
    echo 'Run as the intended Nova user; use sudo only for system packages.' >&2
    exit 1
fi
