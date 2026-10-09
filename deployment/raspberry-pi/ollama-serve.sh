#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
mkdir -p "$NOVA_ROOT/data/private/ollama"
chmod 700 "$NOVA_ROOT/data/private" "$NOVA_ROOT/data/private/ollama"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$NOVA_ROOT/data/private/ollama"
export OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_MAX_QUEUE=2
export OLLAMA_CONTEXT_LENGTH=1024 OLLAMA_KEEP_ALIVE=0
exec "$NOVA_PI/ollama/bin/ollama" serve
