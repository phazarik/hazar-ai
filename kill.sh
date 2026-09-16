#!/usr/bin/env bash
# -------------------------------------------------------------------------
# Stops all background hazar-ai services (Proxy, UI, and Local Model(s)).
# -------------------------------------------------------------------------

echo ">> Stopping hazar-ai services..."

## Helper function to gracefully kill a process by pattern
kill_service() {
  local pattern=$1
  local name=$2
  
  ## Find PID using standard pgrep
  local pids=$(pgrep -f "$pattern")
  
  if [ -n "$pids" ]; then
    echo ">> Stopping $name (PID $pids)..."
    kill $pids 2>/dev/null
    sleep 1
    
    ## Force kill if still running
    for pid in $pids; do
      if kill -0 "$pid" 2>/dev/null; then
        echo ">> $name did not exit gracefully, forcing termination..."
        kill -9 "$pid" 2>/dev/null
      fi
    done
  else
    echo ">> $name is not running."
  fi
}

kill_service "litellm --config" "LiteLLM Proxy"
kill_service "python3 ui/server.py" "Web UI"
kill_service "llama_cpp.server" "Local Model Server"

echo ">> Cleanup complete."