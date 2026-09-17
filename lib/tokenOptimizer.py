# ----------------------------------------------------------------------------
# Safe prompt shortening
#
# Removes extra JSON whitespace without changing string or number text.
# Repeated file blocks can point back to their first copy in the request.
# Source code, comments, and whitespace-sensitive formats stay intact.
# The original message objects are not changed.
# ----------------------------------------------------------------------------

import hashlib
import json
import re

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
