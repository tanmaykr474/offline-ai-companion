#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
NOVA_STAGE="$(mktemp -d "$NOVA_PI/.service-stage.XXXXXX")"
trap 'rm -rf -- "$NOVA_STAGE"' EXIT
"$NOVA_ROOT/.venv/bin/python" -m offline_ai_companion.core.systemd_units \
    --root "$NOVA_ROOT" --user "$(id -un)" --output-dir "$NOVA_STAGE"
# Parser validation is mandatory on the actual Linux host before installation.
systemd-analyze verify "$NOVA_STAGE/nova-ollama.service" "$NOVA_STAGE/nova.service"
sudo install -m 644 "$NOVA_STAGE/nova.service" /etc/systemd/system/nova.service
sudo install -m 644 "$NOVA_STAGE/nova-ollama.service" /etc/systemd/system/nova-ollama.service
sudo systemctl daemon-reload
echo 'Units installed but not enabled or started. Follow the physical validation checklist first.'
