# ----------------------------------------------------------------------------
# Gateway client
#
# Reads the gateway URL and key from the local env file or process settings.
# Streams OpenAI-style events and retries temporary failures.
# Tier fallback is allowed before output starts.
# Partial replies are never replayed automatically.
# ----------------------------------------------------------------------------

import os, sys
import json
import time
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import shlex
import requests

## Import shared helpers by script location so startup works from any shell folder.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "lib"))
from localModels import isLocal, LOCAL_URL

## Read gateway values from the local environment file, then apply environment overrides.
def gatewaySettings():
    values = {}
    ## Find the key file relative to this module, not the current working folder.
    env_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
        "core",
        "litellm.env",
    )
    if os.path.isfile(env_file):
        with open(env_file, encoding="utf-8") as envFile: envLines = envFile.read().splitlines()
        for line in envLines:
            line = line.strip().removeprefix("export ")
            key, separator, raw = line.partition("=")
            key = key.strip()
            if separator and key in {"HAZAR_PROXY_URL", "HAZAR_PROXY_KEY", "LITELLM_MASTER_KEY",}:
                try:
                    ## Handle quoted values and trailing shell comments without executing the file.
                    parsed = shlex.split(raw, comments=True)
                    if len(parsed) == 1: values[key] = parsed[0]
                except ValueError: pass

    ## Process settings override file settings, which helps with alternate gateways.
    values.update(
        {
            key: os.environ[key]
            for key in ("HAZAR_PROXY_URL", "HAZAR_PROXY_KEY", "LITELLM_MASTER_KEY")
            if key in os.environ
        }
    )
    return values

SETTINGS = gatewaySettings()
PROXY_URL = SETTINGS.get("HAZAR_PROXY_URL", "http://127.0.0.1:4000/chat/completions")
PROXY_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Bearer "
    + SETTINGS.get(
        "HAZAR_PROXY_KEY", SETTINGS.get("LITELLM_MASTER_KEY", "sk-anything")
    ),
}
## These HTTP statuses can indicate a temporary limit or gateway failure.
RETRYABLE = {408, 429, 500, 502, 503, 504}

## Read Retry-After as seconds or an HTTP date; use two seconds for invalid values.
def retryDelay(value):
    try: return max(0, float(value))
    except (ValueError, TypeError):
        try: return max(0,(parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds(),)
        except (ValueError, TypeError, OverflowError): return 2

## Build the gateway model-information endpoint from its configured origin.
def modelInfoUrl():
    parts = urlsplit(PROXY_URL)
    return parts.scheme + "://" + parts.netloc + "/model/info"

def streamCompletion(payload, log=lambda message: None):
    # -------------------------------------------------------------------------
    # Stream gateway events with bounded retries and tier fallback.
    # Events before the first content delta are buffered. A failed connection
    # can retry while no output has reached the client. After content, tool
    # calls, or reasoning starts, replay is disabled to avoid duplicate output.
    # A length cutoff or content filter raises an error before memory and
    # artifacts are saved. Explicit model names keep the requested route.
    # -------------------------------------------------------------------------

    ## Named provider models stay on one route; only tier aliases get tier fallbacks.
    model = payload.get("model", "auto")
    ## Local requests use the shared inference service without provider routing.
    local = isLocal(model)
    endpoint = LOCAL_URL if local else PROXY_URL
    if local: log("Local inference: no provider quota; context and output limits still apply.")
    aliases = {
        "auto": ["auto", "fast", "smart"],
        "fast": ["fast", "smart"],
        "smart": ["smart", "fast"],
    }.get(model, [model])

    ## Try the last route once more after the available fallback routes are exhausted.
    ## Local failures are returned directly; cloud requests retain their retry chain.
    attempts = aliases if local else aliases + [aliases[-1]]
    wait = 0
    for index, alias in enumerate(attempts):
        if wait:
            log(f"Gateway backoff: retry in {wait:.1f}s.")
            time.sleep(wait)
        emitted = False
        try:
            ## The timeouts cover connection setup and waiting for streamed response bytes.
            with requests.post(endpoint, headers=PROXY_HEADERS,
                               json=dict(payload, model=alias), stream=True, timeout=(10, 180),
                               ) as response:
                if response.status_code != 200:
                    if response.status_code not in RETRYABLE:
                        raise RuntimeError(f"Gateway rejected request (HTTP {response.status_code}); "
                                           "check authentication/model configuration")

                    # -----------------------------------------------------------------------------------
                    # Retry-After can be a seconds value or a date from the gateway.
                    # A long cooldown on the final same-route retry stops here instead of retrying early.
                    # Switching to another tier waits at most 10 seconds plus a small random delay.
                    # -----------------------------------------------------------------------------------
                    delay = retryDelay(response.headers.get("Retry-After"))
                    if (index + 1 < len(attempts) and attempts[index + 1] == alias and delay > 10):
                        raise RuntimeError(f"Gateway quota cooldown ({delay:.0f}s); retry later")
                    
                    ## Exponential backoff applies if this successful connection later breaks before output.
                    wait = min(delay, 10) + random.uniform(0, 0.5)
                    raise requests.exceptions.ConnectionError(f"HTTP {response.status_code}")

                # ----------------------------------------------------------------------------------
                # Buffer early metadata events until meaningful output starts.
                # If the route fails before that point, the buffered events can be discarded safely.
                # Text, tool calls, and reasoning all count as output and disable replay.
                # ----------------------------------------------------------------------------------
                wait = min(2**index, 8) + random.uniform(0, 0.5)
                finished = False
                finish_reason = None
                pending = []
                text_received = False

                ## SSE events use data: lines; empty lines and other fields can be skipped.
                for line in response.iter_lines():
                    if not line: continue
                    text = line.decode("utf-8")
                    if not text.startswith("data:"):continue
                    raw = text[5:].strip()
                    if raw == "[DONE]":
                        finished = True
                        break
                    try: data = json.loads(raw)
                    except ValueError: raise RuntimeError("Malformed gateway stream")
                    if not isinstance(data, dict): raise RuntimeError("Malformed gateway event")

                    ## An HTTP 200 stream can still contain an error event, including rate limits.
                    if data.get("error"):
                        error = data["error"]
                        code = (str(error.get("code", error.get("status", ""))) if isinstance(error, dict) else "")
                        message = (str(error.get("message", "")) if isinstance(error, dict) else str(error))
                        if (code in {str(s) for s in RETRYABLE}
                            or "rate" in code.lower()
                            or "429" in message
                            or "rate limit" in message.lower()):
                            raise requests.exceptions.ConnectionError("Retryable gateway stream error")
                        ## Show actionable local loader/context errors to the caller.
                        raise RuntimeError(message if local else "Gateway stream error; check gateway logs")

                    choices = data.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        if (delta.get("content")
                            or delta.get("tool_calls")
                            or delta.get("reasoning_content")):
                            emitted = True
                        if delta.get("content"): text_received = True
                        finish_reason = choices[0].get("finish_reason") or finish_reason

                    ## Prefer the gateway header when it reports the real deployment name.
                    actual = response.headers.get("x-litellm-model-name")
                    if actual: data["model"] = actual

                    ## Flush buffered metadata once output begins, then forward later events directly.
                    if emitted:
                        yield from pending
                        pending.clear()
                        yield data
                    else:
                        pending.append(data)
                        if len(pending) > 100: raise RuntimeError("Gateway sent excessive empty events")

                ## Require a completion marker or finish reason before treating the stream as complete.
                if not finished and not finish_reason:
                    raise requests.exceptions.ConnectionError("Gateway stream ended before completion")
                ## A cutoff or filter must not be saved as a complete response.
                if finish_reason in ("length", "content_filter"):
                    raise RuntimeError(f"Incomplete response ({finish_reason}); "
                                       "increase Max Tokens or revise request. "
                                       "No artifacts or memory saved")
                if not text_received:
                    raise RuntimeError("Gateway returned no text; "
                                       "tool execution requires a separate integration")
                return

        except (requests.exceptions.RequestException, RuntimeError) as error:
            ## Retry only before output; replaying after a partial reply could duplicate content.
            retryable = isinstance(error, requests.exceptions.RequestException)
            if emitted or not retryable or index == len(attempts) - 1:
                raise RuntimeError(
                    f"{error}. "
                    + (
                        "Partial output retained on screen; automatic replay disabled."
                        if emitted
                        else "Gateway request failed."
                    )
                ) from error
            log(
                f"Route {alias} unavailable ({error}); trying {attempts[index+1]} ({index+2}/{len(attempts)})."
            )
