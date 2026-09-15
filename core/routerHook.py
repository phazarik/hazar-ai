# --------------------------------------------------------------
# This file decides which model tier a request should go to,
# "fast" or "smart", instead of hardcoding it in every call.
#
# How it works:
#   1. A request comes in asking for model "auto"
#   2. The last message from the request gets pulled out
#   3. That message gets sent to a small, fast, free model
#      (groq qwen3.6 27b) with a one-word classification prompt
#   4. Whatever comes back ("FAST" or "SMART") decides the real
#      model tier, which gets written back into the request
#   5. If that classification call fails for any reason, a basic
#      keyword check is used instead, just so the request still
#      goes somewhere
#
# LiteLLM requires callbacks to be an object with an
# async_pre_call_hook method on it (not a plain function), so
# there's a tiny wrapper class at the bottom. Everything that
# actually matters lives in the function above it.
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

CLASSIFIER_MODEL = "groq/qwen/qwen3.6-27b"
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

    ## dig out the most recent message sent by the user, since that's the
    ## actual task being asked for, not the system prompt or old history
    messages = data.get("messages", [])
    last_user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    text = last_user_msg if isinstance(last_user_msg, str) else str(last_user_msg)

    ## cap the size sent to the classifier,
    ## just enough to get the gist of what's being asked
    snippet = text[:2000]

    try:
        ## ask the small model for a one-word verdict
        print(f"{YELLOW}[ROUTER] Asking {CLASSIFIER_MODEL} for classification verdict...{RESET}")
        resp = await litellm.acompletion(
            model=CLASSIFIER_MODEL,
            api_key=os.environ.get("GROQ_API_KEY", ""),
            messages=[{"role": "user", "content": CLASSIFIER_PROMPT.format(prompt=snippet)}],
            max_tokens=5,
            temperature=0,
            timeout=5,
        )
        verdict = resp.choices[0].message.content.strip().upper()
        print(f"{YELLOW}[ROUTER] Classifier responded with: '{verdict}'{RESET}")

        if "SMART" in verdict:
            print(f"{GREEN}[ROUTER] ➔ Routing request to SMART tier.{RESET}")
            data["model"] = "smart"
            return data
        if "FAST" in verdict:
            print(f"{GREEN}[ROUTER] ➔ Routing request to FAST tier.{RESET}")
            data["model"] = "fast"
            return data

        print(f"{RED}[ROUTER] Unexpected verdict format. Falling back to keyword search.{RESET}")

    except Exception as e:
        err_msg = str(e)
        if "401" in err_msg or "invalid_api_key" in err_msg.lower():      print(f"{RED}{BOLD}[ROUTER AUTH ERROR] GROQ_API_KEY is invalid or expired.{RESET}")
        elif "429" in err_msg or "rate_limit" in err_msg.lower():         print(f"{YELLOW}{BOLD}[ROUTER LIMIT ALERT] Groq classifier rate limited.{RESET}")
        elif "402" in err_msg or "insufficient_quota" in err_msg.lower(): print(f"{RED}{BOLD}[ROUTER BILLING ALERT] Groq quota exhausted.{RESET}")
        elif "404" in err_msg or "model_not_found" in err_msg.lower():    print(f"{RED}{BOLD}[ROUTER MODEL ERROR] Classifier model {CLASSIFIER_MODEL} not found.{RESET}")
        else: print(f"{RED}[ROUTER] Classifier call failed: {e}{RESET}")
        print(f"{YELLOW}[ROUTER] Falling back to keyword evaluation.{RESET}")

    is_smart = any(k in text.lower() for k in FALLBACK_KEYWORDS)
    if is_smart:
        print(f"{GREEN}[ROUTER] Keyword match found. ➔ Routing to SMART tier.{RESET}")
        data["model"] = "smart"
    else:
        print(f"{GREEN}[ROUTER] No keyword match. ➔ Routing to FAST tier.{RESET}")
        data["model"] = "fast"
    return data

## thin wrapper so LiteLLM has an object to call - required by its plugin
## system, doesn't do anything on its own besides hand off to the function above
class TaskRouter(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        return await pick_model_tier(data)

router_hook_instance = TaskRouter()
