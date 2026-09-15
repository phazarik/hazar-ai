# --------------------------------------------------------------
# This file decides which model tier a request should go to,
# "fast" or "smart", instead of hardcoding it in every call.
#
# How it works:
#   1. A request comes in asking for model "auto"
#   2. The last message from the request gets pulled out
#   3. That message gets sent to a small, fast, free model
#      with a one-word classification prompt
#   4. Whatever comes back ("FAST" or "SMART") decides the real
#      model tier, which gets written back into the request
#   5. If that classification call fails (e.g. rate limit), it 
#      tries the next backup model in the list.
#   6. If all models fail, a basic keyword check is used instead.
# --------------------------------------------------------------

import os
import litellm
from litellm.integrations.custom_logger import CustomLogger

BLUE = "\033[94m"
MAGENTA = "\033[95m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Cascading list of classifier models (Primary -> Backups)
CLASSIFIER_MODELS = [
    {"model": "groq/qwen/qwen3.8-27b", "key_env": "GROQ_API_KEY"},
    {"model": "gemini/gemini-3.5-flash-lite", "key_env": "GEMINI_API_KEY"},
    {"model": "openrouter/google/gemma-4-31b-it:free", "key_env": "OPENROUTER_API_KEY"}
]

CLASSIFIER_PROMPT = (
    "Classify the coding request below as exactly one word: FAST or SMART.\n\n"
    "FAST = quick lookups, simple edits, explaining a snippet, single-function fixes, boilerplate.\n"
    "SMART = multi-file refactors, architecture/design decisions, debugging a non-obvious bug,\n"
    "        security review, performance optimization, anything needing multi-step reasoning.\n\n"
    "Reply with just one word: FAST or SMART.\n\n"
    "Request:\n{prompt}"
)

FALLBACK_KEYWORDS = ["refactor", "architecture", "debug", "why does", "migrate", "security"]

async def pick_model_tier(data: dict) -> dict:

    ## if a specific model was asked for already (not "auto"), leave it alone
    if data.get("model") != "auto":
        print(f"{BLUE}[ROUTER] Client requested specific model '{data.get('model')}'. Bypassing auto-classifier.{RESET}")
        return data

    print(f"\n{MAGENTA}[ROUTER] Intercepted 'auto' request. Analyzing complexity...{RESET}")

    messages = data.get("messages", [])
    last_user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    text = last_user_msg if isinstance(last_user_msg, str) else str(last_user_msg)
    snippet = text[:2000]

    # Attempt to classify using the cascading model list
    for classifier in CLASSIFIER_MODELS:
        model_name = classifier["model"]
        api_key = os.environ.get(classifier["key_env"], "")
        
        if not api_key:
            print(f"{YELLOW}[ROUTER] Skipping {model_name} (No API key found).{RESET}")
            continue

        try:
            print(f"{YELLOW}[ROUTER] Asking {model_name} for classification verdict...{RESET}")
            resp = await litellm.acompletion(
                model=model_name,
                api_key=api_key,
                messages=[{"role": "user", "content": CLASSIFIER_PROMPT.format(prompt=snippet)}],
                max_tokens=5,
                temperature=0,
                timeout=5,
            )
            verdict = resp.choices[0].message.content.strip().upper()
            print(f"{YELLOW}[ROUTER] {model_name} responded with: '{verdict}'{RESET}")

            if "SMART" in verdict:
                print(f"{GREEN}[ROUTER] ➔ Routing request to SMART tier.{RESET}")
                data["model"] = "smart"
                return data
            if "FAST" in verdict:
                print(f"{GREEN}[ROUTER] ➔ Routing request to FAST tier.{RESET}")
                data["model"] = "fast"
                return data

            print(f"{RED}[ROUTER] Unexpected verdict format from {model_name}. Trying backup...{RESET}")

        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "rate_limit" in err_msg.lower():
                print(f"{YELLOW}{BOLD}[ROUTER] {model_name} rate limited. Trying backup...{RESET}")
            else:
                print(f"{RED}[ROUTER] {model_name} call failed: {e}. Trying backup...{RESET}")

    # Fallback if every API call in the list fails
    print(f"{YELLOW}[ROUTER] All classifier models exhausted. Falling back to keyword evaluation.{RESET}")
    is_smart = any(k in text.lower() for k in FALLBACK_KEYWORDS)
    if is_smart:
        print(f"{GREEN}[ROUTER] Keyword match found. ➔ Routing to SMART tier.{RESET}")
        data["model"] = "smart"
    else:
        print(f"{GREEN}[ROUTER] No keyword match. ➔ Routing to FAST tier.{RESET}")
        data["model"] = "fast"
    
    return data

class TaskRouter(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        return await pick_model_tier(data)

router_hook_instance = TaskRouter()
