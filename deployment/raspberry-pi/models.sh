#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
if [[ $# != 1 || "$1" != --provision ]]; then
    echo 'Usage: models.sh --provision (explicit model downloads; requires Internet)' >&2; exit 1
fi
NOVA_WHISPER="$NOVA_PI/whisper.cpp"
NOVA_REF=v1.7.6
if [[ ! -d "$NOVA_WHISPER" ]]; then
    git clone --depth 1 --branch "$NOVA_REF" https://github.com/ggml-org/whisper.cpp.git "$NOVA_WHISPER"
fi
test "$(git -C "$NOVA_WHISPER" remote get-url origin)" = https://github.com/ggml-org/whisper.cpp.git
test "$(git -C "$NOVA_WHISPER" rev-parse HEAD)" = "$(git -C "$NOVA_WHISPER" rev-parse "$NOVA_REF^{commit}")"
test -z "$(git -C "$NOVA_WHISPER" status --porcelain --untracked-files=no)"
cmake -S "$NOVA_WHISPER" -B "$NOVA_WHISPER/build" -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DWHISPER_BUILD_TESTS=OFF
cmake --build "$NOVA_WHISPER/build" --config Release -j 2
mkdir -p "$NOVA_ROOT/deployment/models/piper"
if [[ ! -s "$NOVA_ROOT/deployment/models/ggml-tiny.en.bin" ]]; then
    if [[ -e "$NOVA_ROOT/deployment/models/ggml-tiny.en.bin" ]]; then
        echo 'Empty Whisper model exists; inspect it before retrying provisioning.' >&2; exit 1
    fi
    NOVA_DOWNLOAD="$(mktemp -d "$NOVA_PI/.model-stage.XXXXXX")"
    trap 'rm -rf -- "$NOVA_DOWNLOAD"' EXIT
    bash "$NOVA_WHISPER/models/download-ggml-model.sh" tiny.en "$NOVA_DOWNLOAD"
    test -s "$NOVA_DOWNLOAD/ggml-tiny.en.bin"
    mv -- "$NOVA_DOWNLOAD/ggml-tiny.en.bin" "$NOVA_ROOT/deployment/models/ggml-tiny.en.bin"
fi
if [[ ! -s "$NOVA_ROOT/deployment/models/piper/en_US-lessac-medium.onnx" || ! -s "$NOVA_ROOT/deployment/models/piper/en_US-lessac-medium.onnx.json" ]]; then
    if [[ -e "$NOVA_ROOT/deployment/models/piper/en_US-lessac-medium.onnx" || -e "$NOVA_ROOT/deployment/models/piper/en_US-lessac-medium.onnx.json" ]]; then
        echo 'Partial Piper voice exists; inspect the matching model/config pair before retrying.' >&2; exit 1
    fi
    "$NOVA_ROOT/.venv/bin/python" -m piper.download_voices --data-dir "$NOVA_ROOT/deployment/models/piper" en_US-lessac-medium
fi
export OLLAMA_HOST=127.0.0.1:11434
if ! "$NOVA_PI/ollama/bin/ollama" show llama3.2:1b >/dev/null 2>&1; then
    "$NOVA_PI/ollama/bin/ollama" pull llama3.2:1b
fi
# Public model fingerprints aid reproduction; no transcript or database access.
sha256sum "$NOVA_ROOT/deployment/models/ggml-tiny.en.bin" \
    "$NOVA_ROOT/deployment/models/piper/en_US-lessac-medium.onnx" \
    "$NOVA_ROOT/deployment/models/piper/en_US-lessac-medium.onnx.json" > "$NOVA_PI/model-checksums.txt"
echo 'Models provisioned. Run the preflight and physical validation checklist.'
