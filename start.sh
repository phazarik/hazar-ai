#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Service startup
#
# Starts the gateway, browser backend, and optional local model servers.
# Stops matching old services before opening their ports again.
# Modes: proxy, local, ui, all, fresh, offline. Default: all.
# Offline keeps only local routes; all/fresh keep cloud and local aliases.
# ----------------------------------------------------------------------------

set -e
cd "$(dirname "$0")" || exit 1
## Include core for callback imports; keep existing Python paths too.
export PYTHONPATH="$PWD/core:$PWD${PYTHONPATH:+:$PYTHONPATH}"
COMMAND=${1:-all}
YELLOW='\033[33m'
BOLD_YELLOW='\033[1;33m'
RESET='\033[0m'

echo ">> Killing any existing hazar-ai services first..."
bash kill.sh

## Export settings for the proxy and local clients.
if [ -f core/litellm.env ]; then
    set -a
    source core/litellm.env
    set +a
fi

## Generate a gateway key if setup has not created one yet.
if [ -z "$LITELLM_MASTER_KEY" ]; then
    echo ">> LITELLM_MASTER_KEY is not set. Generating private key in core/litellm.env..."
    umask 077
    mkdir -p core
    export LITELLM_MASTER_KEY="$(python3 -c 'import secrets; print("sk-" + secrets.token_hex(32))')"
    printf 'LITELLM_MASTER_KEY="%s"\n' "$LITELLM_MASTER_KEY" >> core/litellm.env
    chmod 600 core/litellm.env
fi

## PYTHONPATH lets LiteLLM import the routing callback from core/.
start_proxy() {
    local config_file=${1:-core/config.yaml}
    echo ">> Starting LiteLLM proxy on port 4000 (config: $config_file)..."
    # Detach the process from this terminal and write its logs under core.
    nohup setsid litellm --config "$config_file" --port 4000 > core/litellm.log 2>&1 &
    echo ">> LiteLLM proxy started (PID $!)."
}

## Start one server per GGUF file on consecutive ports from 8000.
start_local() {
    MODEL_DIR="./models"
    mkdir -p "$MODEL_DIR"
    ## An empty model folder needs an empty array, not a literal *.gguf path.
    shopt -s nullglob
    MODEL_FILES=("$MODEL_DIR"/*.gguf)
    shopt -u nullglob

    LOCAL_MODEL_COUNT=${#MODEL_FILES[@]}
    if [ "$LOCAL_MODEL_COUNT" -eq 0 ]; then
        echo ">> No .gguf models found in $MODEL_DIR. Skipping local inference server(s)."
        return
    fi

    echo ">> Found $LOCAL_MODEL_COUNT local model(s) in $MODEL_DIR. Starting one server per model..."

    local port=8000
    for model_file in "${MODEL_FILES[@]}"; do
        local model_name
        model_name=$(basename "$model_file")
        model_name="${model_name%.gguf}"

        echo ">> Starting local inference server for $model_file on port $port (alias: local:$model_name)..."
        nohup setsid python3 -m llama_cpp.server --model "$model_file" --port "$port" --host 127.0.0.1 \
            > "core/local_model_${model_name}.log" 2>&1 &
        echo ">> Local inference server started (PID $!)."

        port=$((port + 1))
    done

    ## Pass the startup file order unchanged so model ports and aliases match.
    python3 core/generateLocalConfig.py "${MODEL_FILES[@]}"
    echo ">> Generated cloud/local and offline configurations."

}

## The UI forwards completions through the authenticated gateway.
start_ui() {
    echo ">> Starting Web UI on port 5000..."
    nohup setsid python3 ui/server.py > core/ui.log 2>&1 &
    echo ">> Web UI started (PID $!)."
}

## Offline mode uses a local-only config with no cloud routing callback.
case "$COMMAND" in

    ## Fresh mode clears shared chat memory before starting services.
    fresh)
        echo ">> Starting fresh session. Clearing previous memory databases..."
        python3 query.py --clear-memory
        start_local
        if [ "${LOCAL_MODEL_COUNT:-0}" -gt 0 ]; then
            start_proxy core/config.runtime.generated.yaml
        else
            start_proxy
        fi
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
        start_local
        if [ "${LOCAL_MODEL_COUNT:-0}" -gt 0 ]; then
            start_proxy core/config.runtime.generated.yaml
        else
            start_proxy
        fi
        start_ui
        ;;

    ## Use local routes without a cloud classifier callback in this branch.
    offline)
        start_local
        if [ "${LOCAL_MODEL_COUNT:-0}" -eq 0 ]; then
            echo ">> [ERROR] No .gguf models found in ./models — nothing to run offline."
            exit 1
        fi
        start_proxy core/config.local.generated.yaml
        start_ui
        ;;
    *)
        echo "Usage: $0 {proxy|local|ui|all|fresh|offline}"
        exit 1
        ;;
esac

if [[ "$COMMAND" == "all" || "$COMMAND" == "fresh" || "$COMMAND" == "offline" ]]; then
    echo ""
    echo -e ">> Web UI is live at: ${BOLD_YELLOW}http://localhost:5000${RESET}"
    echo ">> CLI Usage Examples:"
    echo -e "   ${YELLOW}python3 query.py --query \"Write a script to parse JSON.\"${RESET}"
    echo -e "   ${YELLOW}python3 query.py --model fast --query \"Quick question...\"${RESET}"
    echo -e "   ${YELLOW}python3 query.py --query \"Long output\" --max-tokens 2000${RESET}"
    echo -e "   ${YELLOW}python3 query.py --query \"Analyze this\" --file app.py config.json --optimize-tokens${RESET}"
    echo -e "   ${YELLOW}python3 query.py --query \"With skill\" --skill prompt-master${RESET}"
    echo -e "   ${YELLOW}python3 query.py --query \"One-off question\" --no-memory${RESET}"
    echo -e "   ${YELLOW}python3 query.py --memory-status${RESET}"
    echo -e "   ${YELLOW}python3 query.py --clear-memory${RESET}"
    echo -e "   ${YELLOW}python3 query.py --list-skills${RESET}"
    echo -e "   ${YELLOW}python3 query.py --skill-inspect prompt-master${RESET}"
    if [[ "$COMMAND" == "offline" ]]; then
        echo -e "   ${YELLOW}python3 query.py --model local --query \"Fully offline query...\"${RESET}"
    fi
    echo ""
    echo ">> All services initiated. Tailing proxy logs (Press Ctrl+C to exit log view)..."
    sleep 1
    ## Ctrl+C stops this log view; kill.sh stops the background services.
    tail -f core/litellm.log
fi
