#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Development-container setup
#
# Installs the merged dependency list in the Python container.
# Runs the same setup helper used by a normal Linux/WSL installation.
# Provider keys still need to be filled in after setup.
# ----------------------------------------------------------------------------

# Install dependencies and create configuration inside the development container.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt
python3 setup.py
