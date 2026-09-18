#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Service shutdown
#
# Finds gateway, UI, and local-model processes by command-line pattern.
# Asks them to stop, waits briefly, then forces remaining matches to exit.
# Matching processes from another installation can also be stopped.
# ----------------------------------------------------------------------------

echo ">> Stopping hazar-ai services..."

## Request graceful termination, then force remaining matching processes to exit.
kill_service() {
  local pattern=$1
  local name=$2
  local pids=$(pgrep -f "$pattern") ## Several model servers can match, so keep every matching PID.
  
  if [ -n "$pids" ]; then
    echo ">> Stopping $name (PID $pids)..."
    kill $pids 2>/dev/null ## Try the normal termination signal before forcing a stop.

    ## Allow the local service to release its worker before forcing shutdown.
    for attempt in {1..24}; do
      local still_running=0
      for pid in $pids; do
        if kill -0 "$pid" 2>/dev/null; then still_running=1; fi
      done
      if [ "$still_running" -eq 0 ]; then break; fi
      sleep 0.5
    done

    ## Check again after giving each process a moment to exit.
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
kill_service "python3 core/localServer.py" "Lazy Local Model Service"
kill_service "core/localWorker.py" "Local Model Worker"
kill_service "llama_cpp.server" "Legacy Local Model Server"

echo ">> Cleanup complete."
