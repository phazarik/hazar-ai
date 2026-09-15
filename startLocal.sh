#!/usr/bin/env bash
# -------------------------------------------------------------------------
# Starts a local OpenAI-compatible inference server for local GGUF models.
# Requires: pip install llama-cpp-python[server]
# -------------------------------------------------------------------------

## Dynamically locate the model directory relative to this script
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$BASE_DIR/model"

## Find the first .gguf file in the model/ directory
MODEL_FILE=$(ls "$MODEL_DIR"/*.gguf 2>/dev/null | head -n 1)

if [ -z "$MODEL_FILE" ]; then
  echo ">> No .gguf model found in $MODEL_DIR"
  exit 1
fi

echo ">> Starting local inference server for $MODEL_FILE on port 8000..."
python3 -m llama_cpp.server --model "$MODEL_FILE" --port 8000 --host 127.0.0.1
