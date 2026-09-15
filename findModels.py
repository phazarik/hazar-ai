#!/usr/bin/env python3
# ------------------------------------------------------------------------------
# Helper script to list available models for the API keys found in litellm.env.
# ------------------------------------------------------------------------------

import requests
import os
import sys
import argparse
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

## Main execution logic
def main():
    parser = argparse.ArgumentParser(description="Find available models across your AI providers.")
    parser.add_argument("--search", type=str, help="Filter models by keyword (e.g., 'llama')")
    args = parser.parse_args()
    foundKeys = loadEnv()
    
    ## Process only the API keys actually found in the environment file.
    for keyName in foundKeys:
        provider = API_PROVIDERS.get(keyName)
        if not provider: continue
        apiKey = os.environ.get(keyName)
        if not apiKey: continue
        pType = provider["type"]
        if pType == "openai":   fetchOpenaiCompatible(provider["url"], apiKey, provider["name"], args.search)
        elif pType == "gemini": fetchGemini(provider["url"], apiKey, args.search)
        elif pType == "tool":
            print(f"\n{YELLOW}{BOLD}=== {provider['name']} ==={RESET}")
            print(f"API key loaded. This provider is used for tools/agents, not LLM completion.")
    print("\n")
    
## Defines how to handle different APIs discovered in the environment file.
## Tavily does not have a URL here because it is a search tool, not a model provider.
API_PROVIDERS = {
    "GROQ_API_KEY": {
        "name": "Groq", 
        "type": "openai", 
        "url": "https://api.groq.com/openai/v1/models"
    },
    "OPENROUTER_API_KEY": {
        "name": "OpenRouter", 
        "type": "openai", 
        "url": "https://openrouter.ai/api/v1/models"
    },
    "GEMINI_API_KEY": {
        "name": "Gemini", 
        "type": "gemini", 
        "url": "https://generativelanguage.googleapis.com/v1beta/models"
    },
    "TAVILY_API_KEY": {
        "name": "Tavily (Search)", 
        "type": "tool", 
        "url": None
    }
}

## Safely reads the environment file and returns a list of the API keys it finds.
def loadEnv() -> list:
    envFile = os.path.join(BASE_DIR, "core", "litellm.env")
    if not os.path.exists(envFile):
        print(f"{RED}[ERROR] Could not find {envFile}{RESET}")
        sys.exit(1)
    foundKeys = []
    with open(envFile, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                os.environ[key] = val.strip("\"'")
                foundKeys.append(key)
    return foundKeys

## Connects to standard OpenAI-compatible endpoints to fetch and print the model list.
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

## Connects to Google's specific Gemini endpoint format to fetch and print available models.
def fetchGemini(url: str, key: str, searchTerm: str):
    print(f"\n{YELLOW}{BOLD}=== Gemini Models ==={RESET}")
    fullUrl = f"{url}?key={key}"
    
    try:
        response = requests.get(fullUrl, timeout=10)
        if response.status_code != 200:
            print(f"{RED}Failed to fetch: {response.text}{RESET}")
            return
            
        models = response.json().get("models", [])
        
        ## Gemini model IDs look like 'models/gemini-1.5-flash', so prefix is striped.
        modelNames = [m.get("name").replace("models/", "") for m in models]
        printModels(modelNames, searchTerm)
        
    except requests.exceptions.RequestException as e:
        print(f"{RED}Error connecting to Gemini: {e}{RESET}")

## Filters the raw model list against the user's search term and prints the results.
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
