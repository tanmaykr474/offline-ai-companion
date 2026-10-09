#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
if [[ $# != 2 || ! "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ || ! "$2" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo 'Usage: install-ollama.sh VERSION TRUSTED_ARCHIVE_SHA256' >&2; exit 1
fi
NOVA_VERSION="$1"
NOVA_DIGEST="${2,,}"
NOVA_PREFIX="$NOVA_PI/ollama"
if [[ -d "$NOVA_PREFIX" ]]; then
    if [[ -f "$NOVA_PREFIX/.nova-provisioned" && "$(cat "$NOVA_PREFIX/.nova-provisioned")" == "$NOVA_VERSION $NOVA_DIGEST" && -x "$NOVA_PREFIX/bin/ollama" ]]; then
        echo 'Requested Ollama archive already installed.'; exit 0
    fi
    echo 'Existing Ollama directory differs; inspect it before replacing it.' >&2; exit 1
fi
NOVA_STAGE="$(mktemp -d "$NOVA_PI/.ollama-stage.XXXXXX")"
trap 'rm -rf -- "$NOVA_STAGE"' EXIT
# Explicit provisioning only. No install.sh, service creation, or automatic latest upgrades.
curl --fail --location --proto '=https' --proto-redir '=https' --max-time 600 --noproxy '*' \
    "https://github.com/ollama/ollama/releases/download/v$NOVA_VERSION/ollama-linux-arm64.tar.zst" -o "$NOVA_STAGE/ollama.tar.zst"
printf '%s  %s\n' "$NOVA_DIGEST" "$NOVA_STAGE/ollama.tar.zst" | sha256sum --check --status
mkdir "$NOVA_STAGE/install"
tar --zstd --extract --file "$NOVA_STAGE/ollama.tar.zst" --directory "$NOVA_STAGE/install" --no-same-owner
test -x "$NOVA_STAGE/install/bin/ollama"
printf '%s %s\n' "$NOVA_VERSION" "$NOVA_DIGEST" > "$NOVA_STAGE/install/.nova-provisioned"
mv -- "$NOVA_STAGE/install" "$NOVA_PREFIX"
echo 'Ollama unpacked locally. Validate its shared libraries on the target Pi before use.'
