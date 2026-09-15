#!/usr/bin/env bash
# -------------------------------------------------------------------------
# Stops the background LiteLLM proxy running on port 4000.
# -------------------------------------------------------------------------

PORT=4000
echo ">> Searching for LiteLLM proxy on port $PORT..."

# Find PID using standard pgrep looking for our specific config
PID=$(pgrep -f "litellm.*core/config.yaml")

if [ -n "$PID" ]; then
  echo ">> Stopping LiteLLM proxy (PID $PID on port $PORT)..."
  kill "$PID"
  sleep 1
  
  if kill -0 "$PID" 2>/dev/null; then
    echo ">> Process did not exit gracefully, forcing termination..."
    kill -9 "$PID"
  fi
  echo ">> LiteLLM stopped."
else
  echo ">> No process found on port $PORT. Falling back to pkill..."
  pkill -f "litellm.*config.yaml" && echo ">> LiteLLM processes terminated." || echo ">> No running LiteLLM process found."
fi
