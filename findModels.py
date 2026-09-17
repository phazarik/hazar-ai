#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Reads provider API keys from core/litellm.env.
# Fetches model names from Groq, OpenRouter, and Gemini.
# The --search flag keeps only names matching the supplied keyword.
# Tavily is listed as a search tool rather than a completion model provider.
# ----------------------------------------------------------------------------

import requests
import os
import sys
import argparse

YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    parser = argparse.ArgumentParser(description="Find available models across your AI providers.")
    parser.add_argument("--search", type=str, help="Filter models by keyword (e.g., 'llama')")
    args = parser.parse_args()
    foundKeys = loadEnv()

    for keyName in foundKeys:
        provider = API_PROVIDERS.get(keyName)
        if not provider: continue
        apiKey = os.environ.get(keyName)
        if not apiKey: continue

        pType = provider["type"]
        if   pType == "openai": fetchOpenaiCompatible(provider["url"], apiKey, provider["name"], args.search)
        elif pType == "gemini": fetchGemini(provider["url"], apiKey, args.search)
        elif pType == "tool":
            print(f"\n{YELLOW}{BOLD}=== {provider['name']} ==={RESET}")
            print("API key loaded. This provider is used for tools/agents, not LLM completion.")
    print("\n")

## Each provider needs its own endpoint and response format.
API_PROVIDERS = {
    "GROQ_API_KEY": {
        "name": "Groq",
        "type": "openai",
        "url": "https://api.groq.com/openai/v1/models",
    },
    "OPENROUTER_API_KEY": {
        "name": "OpenRouter",
        "type": "openai",
        "url": "https://openrouter.ai/api/v1/models",
    },
    "GEMINI_API_KEY": {
        "name": "Gemini",
        "type": "gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
    },
    "TAVILY_API_KEY": {"name": "Tavily (Search)", "type": "tool", "url": None},
}

## Load configured provider keys from the environment file.
def loadEnv() -> list:
    envFile = os.path.join(BASE_DIR, "core", "litellm.env")
    if not os.path.exists(envFile):
        print(f"{RED}[ERROR] Could not find {envFile}{RESET}")
        sys.exit(1)
    foundKeys = []

    ## Read assignments from the local key file; comment and blank lines are skipped.
    with open(envFile, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                os.environ[key] = val.strip("\"'")
                foundKeys.append(key)
    return foundKeys

## Fetch models from an OpenAI-compatible provider and apply the optional filter.
## OpenAI-compatible providers accept the key as a Bearer credential.
def fetchOpenaiCompatible(url: str, key: str, providerName: str, searchTerm: str):
    print(f"\n{YELLOW}{BOLD}=== {providerName} Models ==={RESET}")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"{RED}Failed to fetch: {response.text}{RESET}")
            return
        models = response.json().get("data", [])
        printModels([m.get("id") for m in models], searchTerm)
    except requests.exceptions.RequestException as e:
        print(f"{RED}Error connecting to {providerName}: {e}{RESET}")

## Fetch Gemini model names and apply the optional filter.
## Gemini uses the key in the request URL for this model-list endpoint.
def fetchGemini(url: str, key: str, searchTerm: str):
    print(f"\n{YELLOW}{BOLD}=== Gemini Models ==={RESET}")
    fullUrl = f"{url}?key={key}"
    try:
        response = requests.get(fullUrl, timeout=10)
        if response.status_code != 200:
            print(f"{RED}Failed to fetch: {response.text}{RESET}")
            return
        models = response.json().get("models", [])
        modelNames = [m.get("name").replace("models/", "") for m in models]
        printModels(modelNames, searchTerm)
    except requests.exceptions.RequestException as e:
        print(f"{RED}Error connecting to Gemini: {e}{RESET}")

## Print matching model names and the number of results.
def printModels(modelList: list, searchTerm: str):
    count = 0
    for m in modelList:
        if not m: continue
        if not searchTerm or searchTerm.lower() in m.lower():
            print(f" - {m}")
            count += 1
    if count == 0: print(f"{RED}No models matched '{searchTerm}'.{RESET}")
    else:          print(f"{YELLOW}Total found: {count}{RESET}")

if __name__ == "__main__": main()
