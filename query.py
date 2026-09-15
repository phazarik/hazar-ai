#!/usr/bin/env python3
# ------------------------------------------------------------------------------
# CLI Query Tool
#
# Connects to the local LiteLLM Smart Proxy to run terminal-based inferences.
# Supports file context attachments, skill injection, and memory management.
# ------------------------------------------------------------------------------

import argparse
import requests
import json
import sys
import os
import pyfiglet
from rich.text import Text
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown

## Dynamically resolve the path to the 'lib' directory so custom modules 
## can be imported regardless of where the script is executed from.
LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
sys.path.insert(0, LIB_DIR)
import memoryManager as mem
import skillLoader as skills

## Terminal color constants for formatted output
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET  = "\033[0m"
BOLD = "\033[1m"

## The local proxy endpoint and the required authentication header.
PROXY_URL     = "http://127.0.0.1:4000/chat/completions"
PROXY_HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer sk-anything"}

# ------------------------------------------------------------------------------
# Main execution
# ------------------------------------------------------------------------------
def main():
    args = parseArguments()
    
    ## Check if the user requested a utility command (like checking memory).
    ## If a utility command was handled, exit early to prevent a full API call.
    if handleUtilityCommands(args): return
        
    ## Ensure a valid query string is present for inference.
    if not args.query:
        print(f"{RED}[ERROR] --query is required{RESET}")
        sys.exit(1)

    ##  Process any local files attached via the --file flag.
    ## The file contents are merged into a single context string.
    fileContexts = {}
    contextText  = ""
    if args.file: fileContexts, contextText = prepareFileContext(args.file, args.no_memory)
    else: print(">> No context files attached.")

    ## Append the loaded file contents to the actual prompt.
    finalQuery = args.query
    if contextText: finalQuery += f"\n\nContext files:\n{contextText}"
        
    ## Construct the final array of message dictionaries (System -> History -> User).
    messages = buildMessages(finalQuery, args.skill, args.no_memory)
    
    ## Send the payload to the proxy and stream the response to the terminal.
    streamResponse(args, messages, finalQuery, fileContexts)

# ------------------------------------------------------------------------------
# Core logic
# ------------------------------------------------------------------------------

## Sets up the argument parser and all available terminal flags.
## This defines exactly what inputs the script accepts from the command line.
def parseArguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the local LiteLLM Smart Proxy.")
    parser.add_argument("--model",          default="auto")
    parser.add_argument("--query",          default=None)
    parser.add_argument("--file",           nargs="*")
    parser.add_argument("--max-tokens",     type=int, default=900)
    parser.add_argument("--skill",          default=None, help="Skill to inject (e.g. prompt-master)")
    parser.add_argument("--skill-inspect",  default=None, metavar="NAME", help="Print full skill text and exit")
    parser.add_argument("--no-memory",      action="store_true")
    parser.add_argument("--clear-memory",   action="store_true")
    parser.add_argument("--memory-status",  action="store_true")
    parser.add_argument("--list-skills",    action="store_true")
    return parser.parse_args()

## Handles quick commands that just print info or manage memory, then exit.
## Returns True if a utility command was executed, indicating the main script should stop.
def handleUtilityCommands(args: argparse.Namespace) -> bool:

    ## Triggers the memory manager to delete cache and history files.
    if args.clear_memory: 
        mem.clearMemory()
        return True

    ## Fetches memory metrics (token count, cached file paths) and prints them.
    if args.memory_status:
        s = mem.memoryStatus()
        print(f"Turns in graph   : {s['turns']}")
        print(f"Summary          : {s['summaryChars']} chars")
        print(f"Cached files     : {s['cachedFiles']}")
        for p in s['fileList']: print(f"  - {p}")
        return True

    ## Scans the local skills directory and lists available system prompts.
    if args.list_skills:
        found = skills.listSkills()
        print("Available skills:" if found else "No skills found in ~/.claude/skills/")
        for s in found: print(f"  - {s}")
        return True

    ## Prints the raw markdown text of a specific skill for debugging.
    if args.skill_inspect:
        text = skills.loadSkill(args.skill_inspect, fullText=True)
        print(text if text else f"Skill '{args.skill_inspect}' not found.")
        return True
    
    return False

## Reads local files, saves them to the file cache, and formats them for the prompt.
## Returns a dictionary tracking file metadata and a concatenated string of their contents.
def prepareFileContext(filepaths: list, no_memory: bool) -> tuple[dict, str]:
    fileContexts = {}
    contextText  = ""
    
    print(">> Loading attached files...")
    for filepath in filepaths:
        if not os.path.exists(filepath): 
            print(f"{RED}[ERROR] File not found: {filepath}{RESET}")
            sys.exit(1)
            
        ## Read the file and pass it to the memory manager.
        ## The manager hashes the content to prevent storing duplicates.
        with open(filepath) as f: raw = f.read()
        sha, cached = mem.registerFile(filepath, raw)
        label = f"{CYAN}(cached){RESET} " if (cached and not no_memory) else "+ "
        print(f"  {label}{filepath}")
        
        ## Append the file contents into a clearly separated format for the LLM.
        ## optimizeTokens strips empty lines to save context window space.
        contextText += f"\n\n--- FILE: {filepath} ---\n{optimizeTokens(raw)}\n--- END ---\n"
        fileContexts[sha] = {"path": filepath, "content": raw}
        
    return fileContexts, contextText

## Pulls together skills, previous memory history, and the new query into the final message list.
## This prepares the exact JSON structure expected by the OpenAI-compatible proxy endpoint.
def buildMessages(finalQuery: str, skill: str, no_memory: bool) -> list:
    messages = []

    # Inject skill instructions as early messages to set the behavior.
    if skill:
        skillMsgs = skills.buildSkillMessages(skill)
        if skillMsgs:
            print(f">> Injecting skill: {skill}")
            messages.extend(skillMsgs)
        else:
            avail = skills.listSkills()
            print(f"{YELLOW}>> Skill '{skill}' not found.{RESET}")
            if avail: print(f"   Available: {', '.join(avail)}")

    ## Inject prior conversation history unless the --no-memory flag was passed.
    if not no_memory:
        history, _ = mem.loadMemory()
        if history:
            turns = sum(1 for m in history if m["role"] == "user")
            print(f">> Loaded {turns} turn(s) from memory.")
            messages.extend(history)
        else: print(">> No prior memory. Starting fresh.")
    else: print(">> Memory disabled (--no-memory).")
    
    ## Finally, attach the active user prompt at the very end of the list.
    messages.append({"role": "user", "content": finalQuery})
    return messages

## Connects to the LLM API, parses the streaming text chunks, and updates the console UI.
## This function handles the network connection, renders the Markdown via the Rich library,
## and captures the final token usage.
def streamResponse(args: argparse.Namespace, messages: list, finalQuery: str, fileContexts: dict):
    print(f">> Sending to proxy (model: {args.model}, messages: {len(messages)})")
    
    ## Construct the JSON payload for the proxy.
    payload = {
        "model": args.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": args.max_tokens,
    }

    try:
        ## Establish the streaming connection to the local LiteLLM server.
        resp = requests.post(PROXY_URL, headers=PROXY_HEADERS, json=payload, stream=True)
        resp.raise_for_status()
        
        ## Intercept the actual model name directly from the HTTP headers.
        ## This bypasses the alias grouping problem where 'fast' or 'smart' gets echoed
        ## instead of the exact provider model ID.
        actualModel = resp.headers.get("x-litellm-model-name", "unknown")
        
        console = Console()
        reply   = ""
        pTok = 0
        cTok = 0
        tTok = 0
        
        print(">> Stream starting...\n")
        if actualModel != "unknown": print(f"{YELLOW}>> Model: {BOLD}{actualModel}{RESET}\n")
        displayLogo(console)

        ## Utilize the Rich Live rendering context to draw and redraw the Markdown panel
        ## rapidly as chunks stream in from the server.
        with Live(buildPanel(reply, f"[Connecting...] {actualModel}"), console=console, refresh_per_second=15) as live:
            
            ## Read the byte stream from the HTTP socket line by line.
            for line in resp.iter_lines():
                if not line: continue
                lineStr = line.decode("utf-8")

                ## Check for standard Server-Sent Events (SSE) data formatting.
                if not lineStr.startswith("data: "): continue
                dataStr = lineStr[6:]
                if dataStr == "[DONE]": 
                    live.update(buildPanel(reply, f"[Done] {actualModel}"))
                    break
                data = parseJsonSafe(dataStr)
                if not data: continue

                ## Fallback check in case the HTTP header was omitted by the provider.
                ## Avoid overwriting a valid model name with an alias.
                if actualModel == "unknown" and "model" in data:
                    reported = data["model"]
                    if reported not in ("auto", "fast", "smart"): actualModel = reported

                ## Extract token usage statistics if included in the stream chunk.
                if "usage" in data and data["usage"]:
                    u    = data["usage"]
                    pTok = u.get("prompt_tokens", pTok)
                    cTok = u.get("completion_tokens", cTok)
                    tTok = u.get("total_tokens", tTok)

                ## Extract the text fragment and append it to the complete reply string.
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if "content" in delta: reply += delta["content"]

                ## Force a UI redraw with the newly appended text.
                live.update(buildPanel(reply, f"[Generating] {actualModel}"))

        ## Post-processing: save the interaction to persistent memory.
        if not args.no_memory and reply:
            mem.appendTurn(finalQuery, reply, fileContexts if fileContexts else None)
            print("\n>> Turn saved to memory.")
            
        ## If the API provider did not supply exact token usage, estimate it based
        ## on word counts to populate the progress bar anyway.
        if tTok == 0 and reply:
            cTok = int(len(reply.split()) * 1.3)
            pTok = int(len(finalQuery.split()) * 1.3)
            tTok = pTok + cTok
            
        ## Display the final usage metrics to the terminal.
        print(f"\n{formatUsage(pTok, cTok, tTok, args.max_tokens)}\n")

    except KeyboardInterrupt: 
        print(f"\n{YELLOW}>> Stopped.{RESET}")
        sys.exit(0)
    except requests.exceptions.RequestException as e: 
        print(f"\n{RED}[ERROR] Proxy request failed: {e}{RESET}")
        
# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

## Removes empty lines and spaces from file content to save context tokens.
def optimizeTokens(content: str) -> str:
    return "\n".join(line.rstrip() for line in content.splitlines() if line.strip())

## Prints the stylish ASCII art title using a compact block font to prevent wrapping.
def displayLogo(console: Console):
    ascii_art = pyfiglet.figlet_format("Prachu-GPT", font="slant")
    console.print(Text(ascii_art, style="bold green"), no_wrap=True)
    
## Wraps the streaming text inside a bordered box.
## If a code block is open (odd number of ```), temporarily closes it
## to prevent rendering glitches mid-stream.
def buildPanel(text: str, title: str) -> Panel:
    if text.count("```") % 2 != 0: text += "\n```"
    return Panel(Markdown(text, code_theme="bw"), title=title, border_style="green", width=110)

## Calculates and formats an ASCII progress bar showing how many tokens were used.
def formatUsage(pTok: int, cTok: int, tTok: int, maxTok: int) -> str:
    pct    = (cTok / maxTok * 100) if maxTok > 0 else 0
    filled = min(100, int(100 * cTok / maxTok)) if maxTok > 0 else 0
    bar    = "█" * filled + "░" * (100 - filled)
    return (
        f"Tokens — prompt: {pTok} + completion: {cTok} = total: {tTok}\n"
        f"{bar} {YELLOW}{BOLD}{pct:.1f}%{RESET} of {maxTok}"
    )

## Safely tries to parse a JSON string, returning an empty dictionary on failure
## to prevent catastrophic crashes on corrupted network chunks.
def parseJsonSafe(dataStr: str) -> dict:
    try: return json.loads(dataStr)
    except Exception:  return {}

if __name__ == "__main__": main()
