#!/usr/bin/env bash

# Ensure dependencies are available 
pip install requests pyfiglet rich

# Scaffold the keys file so the user can easily paste their keys
mkdir -p core
if [ ! -f core/litellm.env ]; then
    cat << 'EOF' > core/litellm.env
OPENROUTER_API_KEY=sk-or-v1-XXXXXXXXXXXX
GEMINI_API_KEY=AIzaSyXXXXXXXXXXXX
GROQ_API_KEY=gsk_XXXXXXXXXXXX
TAVILY_API_KEY=tvly-dev-XXXXXXXXXXXX
LITELLM_MASTER_KEY=sk-anything
EOF
fi

chmod +x start.sh kill.sh query.py
