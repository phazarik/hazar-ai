# ----------------------------------------------------------------------------
# Automatic model tier routing
#
# Rewrites auto requests to fast or smart before the gateway calls a model.
# Keyword and request-length checks run locally by default.
# Provider classification is available through HAZAR_LLM_CLASSIFIER=1.
# Explicit model names bypass classification and keep their requested route.
# ----------------------------------------------------------------------------

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

## Provider classification tries these models in order when explicitly enabled.
CLASSIFIER_MODELS = [
    {"model": "gemini/gemini-3.5-flash-lite", "key_env": "GEMINI_API_KEY"},
    {"model": "groq/qwen/qwen3.8-27b", "key_env": "GROQ_API_KEY"},
    {"model": "openrouter/google/gemma-4-31b-it:free", "key_env": "OPENROUTER_API_KEY"},
]
CLASSIFIER_PROMPT = (
    "Classify the coding request below as exactly one word: FAST or SMART.\n\n"
    "FAST = quick lookups, simple edits, explaining a snippet, single-function fixes, boilerplate.\n"
    "SMART = multi-file refactors, architecture/design decisions, debugging a non-obvious bug,\n"
    "        security review, performance optimization, anything needing multi-step reasoning.\n\n"
    "Reply with just one word: FAST or SMART.\n\n"
    "Request:\n{prompt}"
)
FALLBACK_KEYWORDS = [
    "refactor",
    "architecture",
    "debug",
    "why does",
    "migrate",
    "security",
]

async def pick_model_tier(data: dict) -> dict:
    # ---------------------------------------------------------------------
    # Route auto requests to fast or smart; preserve explicit model names.
    # Keyword and length checks run locally by default. Setting
    # HAZAR_LLM_CLASSIFIER=1 enables provider classification with backups.
    # If those calls fail, keyword routing remains available.
    # ---------------------------------------------------------------------
    
    ## A requested tier or exact model name does not need automatic classification.
    if data.get("model") != "auto":
        print(f"{BLUE}[ROUTER] Requested: '{data.get('model')}'. Bypassing auto-classifier.{RESET}")
        return data
    print(f"\n{MAGENTA}[ROUTER] Intercepted 'auto' request. Analyzing complexity...{RESET}")
    messages = data.get("messages", [])

    ## Classify the latest user request instead of system rules or an assistant reply.
    last_user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    text = last_user_msg if isinstance(last_user_msg, str) else str(last_user_msg)
    snippet = text[:2000]

    ## The default check is local and spends no provider quota on classification.
    if os.getenv("HAZAR_LLM_CLASSIFIER", "0") != "1":
        data["model"] = ("smart" if len(text) > 4000 or
                         any(k in text.lower() for k in FALLBACK_KEYWORDS) else "fast")
        return data

    ## Skip missing keys and move to a backup if a classifier is unavailable.
    for classifier in CLASSIFIER_MODELS:
        modelName = classifier["model"]
        api_key = os.environ.get(classifier["key_env"], "")
        if not api_key:
            print(f"{YELLOW}[ROUTER] Skipping {modelName} (No API key found).{RESET}")
            continue
        try:
            print(f"{YELLOW}[ROUTER] Asking {modelName} for classification verdict...{RESET}")
            resp = await litellm.acompletion(
                model=modelName,
                api_key=api_key,
                messages=[
                    {
                        "role": "user",
                        "content": CLASSIFIER_PROMPT.format(prompt=snippet),
                    }
                ],
                max_tokens=5,
                temperature=0,
                timeout=5,
            )
            ## Use the short FAST/SMART answer to rewrite the gateway model alias.
            verdict = resp.choices[0].message.content.strip().upper()
            print(f"{YELLOW}[ROUTER] {modelName} responded with: '{verdict}'{RESET}")

            if "SMART" in verdict:
                print(f"{GREEN}[ROUTER] ➔ Routing request to SMART tier.{RESET}")
                data["model"] = "smart"
                return data
            if "FAST" in verdict:
                print(f"{GREEN}[ROUTER] ➔ Routing request to FAST tier.{RESET}")
                data["model"] = "fast"
                return data
            print(f"{RED}[ROUTER] Unexpected verdict format from {modelName}. Trying backup...{RESET}")

        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "rate_limit" in err_msg.lower():
                print(f"{YELLOW}{BOLD}[ROUTER] {modelName} rate limited. Trying backup...{RESET}")
            else: print(f"{RED}[ROUTER] {modelName} call failed: {e}. Trying backup...{RESET}")

    print(f"{YELLOW}[ROUTER] All classifier models exhausted. Falling back to keyword evaluation.{RESET}")

    ## If every classifier fails, keyword routing still gives the request a tier.
    is_smart = any(k in text.lower() for k in FALLBACK_KEYWORDS)
    if is_smart:
        print(f"{GREEN}[ROUTER] Keyword match found. ➔ Routing to SMART tier.{RESET}")
        data["model"] = "smart"
    else:
        print(f"{GREEN}[ROUTER] No keyword match. ➔ Routing to FAST tier.{RESET}")
        data["model"] = "fast"

    return data

## LiteLLM loads this callback object and calls the hook before completion.
class TaskRouter(CustomLogger):
    ## Apply tier selection before the proxy sends the request.
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        return await pick_model_tier(data)
    
router_hook_instance = TaskRouter()
