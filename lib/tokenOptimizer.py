# ----------------------------------------------------------------------------
# Safe prompt shortening + token calculation
#
# Removes extra JSON whitespace without changing string or number text.
# Repeated file blocks can point back to their first copy in the request.
# Source code, comments, and whitespace-sensitive formats stay intact.
# The original message objects are not changed.
# ----------------------------------------------------------------------------

import hashlib
import json
import re
import requests
from proxyClient import PROXY_HEADERS, modelInfoUrl

def optimizeFile(content, name=""):
    # -----------------------------------------------------------------------
    # Remove JSON whitespace outside strings without changing values.
    # Duplicate keys prevent optimization. Number spellings, escapes, source
    # comments, and whitespace-sensitive formats remain unchanged.
    # -----------------------------------------------------------------------
    if name.lower().endswith(".json"):
        try:
            # ----------------------------------------------------------------------------------
            # Reject duplicate JSON keys before compacting whitespace. Validate JSON first,
            # then shorten the original text rather than serializing parsed values. Track string
            # boundaries and escaped quotes while walking the original characters. Whitespace
            # inside strings is data and must stay.
            # ----------------------------------------------------------------------------------
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate JSON key")
                    result[key] = value
                return result
            json.loads(content, object_pairs_hook=unique)
            result = []
            quoted = False
            escaped = False

            ## Append every string character, but skip whitespace outside strings.
            for char in content:
                if quoted or not char.isspace(): result.append(char)
                if quoted:
                    if escaped:        escaped = False
                    elif char == "\\": escaped = True
                    elif char == '"':  quoted = False
                elif char == '"':      quoted = True

            compact = "".join(result)
            if len(compact) < len(content): return compact
        except (ValueError, TypeError): pass
    return content

def optimizeMessages(messages):
    # ------------------------------------------------------------------------
    # Copy messages and shorten repeated file blocks in user text.
    # SHA-256 identifies identical content within this request. A later block
    # becomes a reference only if that reference is shorter. The first copy
    # stays in the message list. System and assistant text remain unchanged.
    # ------------------------------------------------------------------------
    seen = {}
    pattern = re.compile(r"(?ms)^--- FILE: ([^\n]+) ---\n(.*?)\n--- END ---")
    optimized = []
    
    def replace(match):
        name, raw = match.groups()
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if digest in seen:
            reference = f"[FILE {name}: identical to earlier FILE {seen[digest]}; sha256={digest[:16]}]"
            if len(reference) < len(match.group(0)): return reference
        seen[digest] = name
        return f"--- FILE: {name} ---\n{optimizeFile(raw, name)}\n--- END ---"

    ## Copy message dictionaries and change only user text; history objects stay untouched.
    for message in messages:
        copied = dict(message)
        isUserMessage = message.get("role") == "user"
        hasText = isinstance(message.get("content"), str)
        if isUserMessage and hasText: copied["content"] = pattern.sub(replace, message["content"])
        optimized.append(copied)
        
    return optimized


def getContextLimit(modelName: str) -> int | None:
    # ----------------------------------------------------------------------------
    # Reads input limits reported by the configured gateway.
    # Matches gateway aliases, deployment IDs, and provider model names.
    # Returns None when the gateway does not provide a valid limit.
    # ----------------------------------------------------------------------------
    try:
        response = requests.get(modelInfoUrl(), headers=PROXY_HEADERS, timeout=2,)
        response.raise_for_status()

        ## Match the streamed provider name as well as gateway aliases and IDs.
        for model in response.json().get("data", []):
            info = model.get("model_info") or {}
            params = model.get("litellm_params") or {}
            names = (
                model.get("model_name"),
                model.get("id"),
                info.get("id"),
                params.get("model"),
            )
            if modelName not in names: continue

            ## Missing metadata in one matching entry should not end the search.
            for value in (info.get("max_input_tokens"), model.get("max_input_tokens"),):
                if value is None or isinstance(value, bool): continue
                try:
                    limit = int(value)
                    if limit > 0: return limit
                except (TypeError, ValueError, OverflowError): continue

    ## Unavailable metadata should not interrupt a completed response.
    except (requests.RequestException, ValueError, TypeError, AttributeError): pass
    return None
