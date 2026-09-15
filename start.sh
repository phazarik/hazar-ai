#!/usr/bin/env bash
# -------------------------------------------------------------------------
# Unified startup script for Prachu-GPT services.
# Usage: ./start.sh [proxy|local|ui|all|fresh]
# -------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1
COMMAND=${1:-all}

BOLD_YELLOW='\033[1;33m'
RESET='\033[0m'

## Securely load API keys and environment variables into the shell session.
## 'set -a' exports all variables defined in the sourced file automatically.
if [ -f core/litellm.env ]; then
    set -a
    source core/litellm.env
    set +a
fi

## Safeguard against a missing master key. The proxy requires this to authenticate
## incoming local requests. If missing, a default is injected.
if [ -z "$LITELLM_MASTER_KEY" ]; then
    echo ">> LITELLM_MASTER_KEY is not set. Injecting default key into core/litellm.env..."
    echo 'LITELLM_MASTER_KEY="sk-anything"' >> core/litellm.env
    export LITELLM_MASTER_KEY="sk-anything"
fi

## Boots the core LiteLLM proxy in the background on port 4000.
## All standard AI traffic is routed here first.
start_proxy() {
    echo ">> Starting LiteLLM proxy on port 4000..."
    nohup setsid litellm --config core/config.yaml --port 4000 > core/litellm.log 2>&1 &
    echo ">> LiteLLM proxy started (PID $!)."
}

## Checks for a native .gguf model file in the local directory.
## If found, boots a dedicated local inference server on port 8000.
start_local() {
    MODEL_DIR="./model"
    MODEL_FILE=$(ls "$MODEL_DIR"/*.gguf 2>/dev/null | head -n 1)
    
    if [ -z "$MODEL_FILE" ]; then
        echo ">> No .gguf model found in $MODEL_DIR. Skipping local inference server."
    else
        echo ">> Starting local inference server for $MODEL_FILE on port 8000..."
        nohup setsid python3 -m llama_cpp.server --model "$MODEL_FILE" --port 8000 --host 127.0.0.1 > core/local_model.log 2>&1 &
        echo ">> Local inference server started (PID $!)."
    fi
}

## Boots the local Python web server to host the browser UI.
start_ui() {
    echo ">> Starting Web UI on port 5000..."
    nohup setsid python3 ui/server.py > core/ui.log 2>&1 &
    echo ">> Web UI started (PID $!)."
}

# -------------------------------------------------------------------------
# Execution Routing
# -------------------------------------------------------------------------
case "$COMMAND" in
    # The 'fresh' argument wipes previous memory caches before starting
    fresh)
        echo ">> Starting fresh session. Clearing previous memory databases..."
        python3 query.py --clear-memory
        start_proxy
        start_local
        start_ui
        ;;
    proxy) 
        start_proxy 
        ;;
    local) 
        start_local 
        ;;
    ui)    
        start_ui 
        ;;
    all)
        start_proxy
        start_local
        start_ui
        ;;
    *)
        echo "Usage: $0 {proxy|local|ui|all|fresh}"
        exit 1
        ;;
esac

## Provide helpful CLI feedback and tail the proxy logs for live monitoring
if [[ "$COMMAND" == "all" || "$COMMAND" == "fresh" ]]; then
    echo ""
    echo -e ">> Web UI is live at: ${BOLD_YELLOW}http://localhost:5000${RESET}"
    echo ">> CLI Usage Examples:"
    echo "   python3 query.py --query \"Write a script to parse JSON.\""
    echo "   python3 query.py --model fast --query \"Quick question...\""
    echo ""
    echo ">> All services initiated. Tailing proxy logs (Press Ctrl+C to exit log view)..."
    sleep 1
    tail -f core/litellm.log
fi
