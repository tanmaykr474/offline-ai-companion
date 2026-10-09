#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
if [[ "${1:-}" == --system-deps && $# == 1 ]]; then
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-dev build-essential cmake git curl zstd pkg-config portaudio19-dev libportaudio2 libsndfile1 alsa-utils
elif [[ $# != 0 ]]; then
    echo 'Usage: setup.sh [--system-deps]' >&2; exit 1
fi
python3 -c 'import sys; assert sys.version_info[:2] == (3,13), "Nova requires Python 3.13; do not reuse a Bookworm Python 3.11 environment."'
cd "$NOVA_ROOT"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,13)'
# Fail if a compatible binary wheel is missing rather than silently building a model runtime.
.venv/bin/python -m pip install --only-binary=:all: -r "$NOVA_PI/requirements.txt"
.venv/bin/python -m pip install -e .
mkdir -p data/private data/audio
chmod 700 data/private data/audio
if [[ ! -e "$NOVA_PI/nova.env" ]]; then
    install -m 600 "$NOVA_PI/nova.env.example" "$NOVA_PI/nova.env"
fi
chmod 600 "$NOVA_PI/nova.env"
chmod 755 "$NOVA_PI/piper.sh"
echo 'Environment prepared. Models and Ollama must be explicitly provisioned next.'
