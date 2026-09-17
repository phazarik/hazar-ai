#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Terminal gateway settings
#
# Loads this installation's core/litellm.env into the current shell.
# Points compatible terminal tools at the local LiteLLM gateway.
# Source this script to keep these settings in the current terminal.
# ----------------------------------------------------------------------------

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

## Export the settings from this installation.
if [ -f "$SETUP_DIR/core/litellm.env" ]; then
  set -a
  source "$SETUP_DIR/core/litellm.env"
  set +a
fi

## Point compatible CLI tools to the local gateway using its shared credential.
export OPENAI_API_BASE="http://localhost:4000"
export OPENAI_API_KEY="$LITELLM_MASTER_KEY"
