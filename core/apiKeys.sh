#!/usr/bin/env bash
# -------------------------------------------------------------------------
# This script loads AI API keys into the terminal's environment.
#
# Note: The background LiteLLM service does NOT use this file.
# It reads directly from litellm.env.
#
# This script exists solely so the CLI tools (aider, llm, curl, etc.)
# have access to the keys and know how to route traffic to the local proxy.
# --------------------------------------------------------------------------

# Dynamically find the root directory of this setup
SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load the raw API keys from the environment file.
# 'set -a' forces bash to automatically export every variable it reads,
# and 'set +a' turns that behavior back off.
if [ -f "$SETUP_DIR/core/litellm.env" ]; then
  set -a
  source "$SETUP_DIR/core/litellm.env"
  set +a
fi

# Redirect standard OpenAI-compatible tools to the local proxy.
# Whenever a tool asks for an OpenAI key, it will use the master key
# and send the request to localhost:4000 instead of OpenAI's servers.
export OPENAI_API_BASE="http://localhost:4000"
export OPENAI_API_KEY="$LITELLM_MASTER_KEY"
