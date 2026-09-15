#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ -f core/litellm.env ]; then
  set -a
  source core/litellm.env
  set +a
fi

## setsid ensures the background process ignores terminal signals like Ctrl+C
nohup setsid litellm --config core/config.yaml --port 4000 > core/litellm.log 2>&1 &

echo "LiteLLM proxy started in background (PID $!). Tailing logs (Press Ctrl+C to exit log view, service will keep running)..."
sleep 1
tail -f core/litellm.log
