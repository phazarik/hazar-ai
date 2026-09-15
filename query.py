#!/usr/bin/env python3
# ------------------------------------------------------------------------------
# CLI tool to query the local LiteLLM Smart Proxy.
#
# Usage:
#   python3 query.py --query "Your prompt"
#   python3 query.py --model fast --query "Write a quick loop"
#   python3 query.py --file script.py --query "Review this"
#   python3 query.py --skill prompt-master --query "Improve: ..."
#   python3 query.py --no-memory --query "Fresh question"
#   python3 query.py --clear-memory
#   python3 query.py --memory-status
#   python3 query.py --list-skills
#   python3 query.py --skill-inspect prompt-master
# ------------------------------------------------------------------------------

import argparse, requests, json, sys, os
import pyfiglet
from rich.text import Text
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown

LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
sys.path.insert(0, LIB_DIR)
import memoryManager as mem
import skillLoader   as skills

YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"
RESET  = "\033[0m";  BOLD = "\033[1m"
PROXY_URL     = "http://127.0.0.1:4000/chat/completions"
PROXY_HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer sk-anything"}

# ------------------------------------------------------------------------------
# Main execution
# ------------------------------------------------------------------------------
def main():
    args = parseArguments()
    if handleUtilityCommands(args): return
    if not args.query:
        print(f"{RED}[ERROR] --query is required{RESET}")
        sys.exit(1)

    fileContexts = {}
    contextText  = ""
    if args.file: fileContexts, contextText = prepareFileContext(args.file, args.no_memory)
    else: print(">> No context files attached.")

    finalQuery = args.query
    if contextText: finalQuery += f"\n\nContext files:\n{contextText}"
    messages = buildMessages(finalQuery, args.skill, args.no_memory)
    streamResponse(args, messages, finalQuery, fileContexts)

# ------------------------------------------------------------------------------
# Core logic
# ------------------------------------------------------------------------------

## Sets up the argument parser and all available flags
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

## Handles quick commands that just print info or manage memory, then exit
def handleUtilityCommands(args: argparse.Namespace) -> bool:
    if args.clear_memory: 
        mem.clearMemory()
        return True

    if args.memory_status:
        s = mem.memoryStatus()
        print(f"Turns in graph   : {s['turns']}")
        print(f"Summary          : {s['summaryChars']} chars")
        print(f"Cached files     : {s['cachedFiles']}")
        for p in s['fileList']: print(f"  {p}")
        return True

    if args.list_skills:
        found = skills.listSkills()
        print("Available skills:" if found else "No skills found in ~/.claude/skills/")
        for s in found: print(f"  - {s}")
        return True

    if args.skill_inspect:
        text = skills.loadSkill(args.skill_inspect, fullText=True)
        print(text if text else f"Skill '{args.skill_inspect}' not found.")
        return True
    
    return False

## Reads local files, saves them to the file cache, and formats them for the prompt
def prepareFileContext(filepaths: list, no_memory: bool) -> tuple[dict, str]:
    fileContexts = {}
    contextText  = ""
    
    print(">> Loading attached files...")
    for filepath in filepaths:
        if not os.path.exists(filepath): 
            print(f"{RED}[ERROR] File not found: {filepath}{RESET}")
            sys.exit(1)
            
        with open(filepath) as f: raw = f.read()
        sha, cached = mem.registerFile(filepath, raw)
        
        label = f"{CYAN}(cached){RESET} " if (cached and not no_memory) else "+ "
        print(f"  {label}{filepath}")
        
        contextText += f"\n\n--- FILE: {filepath} ---\n{optimizeTokens(raw)}\n--- END ---\n"
        fileContexts[sha] = {"path": filepath, "content": raw}
        
    return fileContexts, contextText

## Pulls together skills, previous memory history, and the new query into the final message list
def buildMessages(finalQuery: str, skill: str, no_memory: bool) -> list:
    messages = []

    if skill:
        skillMsgs = skills.buildSkillMessages(skill)
        if skillMsgs:
            print(f">> Injecting skill: {skill}")
            messages.extend(skillMsgs)
        else:
            avail = skills.listSkills()
            print(f"{YELLOW}>> Skill '{skill}' not found.{RESET}")
            if avail: print(f"   Available: {', '.join(avail)}")

    if not no_memory:
        history, _ = mem.loadMemory()
        if history:
            turns = sum(1 for m in history if m["role"] == "user")
            print(f">> Loaded {turns} turn(s) from memory.")
            messages.extend(history)
        else: print(">> No prior memory. Starting fresh.")
    else: print(">> Memory disabled (--no-memory).")
    
    messages.append({"role": "user", "content": finalQuery})
    return messages

## Connects to the LLM API, parses the streaming text chunks, and updates the console UI
def streamResponse(args: argparse.Namespace, messages: list, finalQuery: str, fileContexts: dict):
    print(f">> Sending to proxy (model: {args.model}, messages: {len(messages)})")
    
    payload = {
        "model": args.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": args.max_tokens,
    }

    try:
        resp = requests.post(PROXY_URL, headers=PROXY_HEADERS, json=payload, stream=True)
        resp.raise_for_status()
        console     = Console()
        reply       = ""
        actualModel = "unknown"
        pTok = cTok = tTok = 0
        print(">> Stream starting...\n")
        displayLogo(console)

        with Live(buildPanel(reply, "[Connecting...]"), console=console, refresh_per_second=15) as live:
            for line in resp.iter_lines():
                if not line: continue
                lineStr = line.decode("utf-8")
                if not lineStr.startswith("data: "): continue
                dataStr = lineStr[6:]
                
                if dataStr == "[DONE]": 
                    live.update(buildPanel(reply, f"[Done] {actualModel}"))
                    break

                data = parseJsonSafe(dataStr)
                if not data: continue

                if actualModel == "unknown" and "model" in data:
                    actualModel = data["model"]
                    if args.model not in ("auto", actualModel):
                        print(f"{RED}>> Preferred '{args.model}' exhausted; fallback:{RESET} {YELLOW}{BOLD}{actualModel}{RESET}")
                    else: print(f"{YELLOW}>> Model: {BOLD}{actualModel}{RESET}")

                if "usage" in data and data["usage"]:
                    u    = data["usage"]
                    pTok = u.get("prompt_tokens", pTok)
                    cTok = u.get("completion_tokens", cTok)
                    tTok = u.get("total_tokens", tTok)

                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if "content" in delta: reply += delta["content"]

                live.update(buildPanel(reply, f"[Generating] {actualModel}"))

        if not args.no_memory and reply:
            mem.appendTurn(finalQuery, reply, fileContexts if fileContexts else None)
            print("\n>> Turn saved to memory.")
            
        if tTok == 0 and reply:
            cTok = int(len(reply.split()) * 1.3)
            pTok = int(len(finalQuery.split()) * 1.3)
            tTok = pTok + cTok
            
        print(f"\n{formatUsage(pTok, cTok, tTok, args.max_tokens)}\n")

    except KeyboardInterrupt: 
        print(f"\n{YELLOW}>> Stopped.{RESET}")
        sys.exit(0)
    except requests.exceptions.RequestException as e: 
        print(f"\n{RED}[ERROR] Proxy request failed: {e}{RESET}")
        
# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

## Removes empty lines and spaces from file content to save context tokens
def optimizeTokens(content: str) -> str:
    return "\n".join(line.rstrip() for line in content.splitlines() if line.strip())

## Prints the stylish ASCII art title to the terminal
def displayLogo(console: Console):
    console.print(Text(pyfiglet.figlet_format("Prachu GPT", font="slant"), style="bold magenta"))

## Wraps the streaming text inside a nice-looking bordered box
def buildPanel(text: str, title: str) -> Panel:
    if text.count("```") % 2 != 0: text += "\n```"
    return Panel(Markdown(text, code_theme="bw"), title=title, border_style="green", width=110)

## Calculates and formats a progress bar showing how many tokens were used
def formatUsage(pTok: int, cTok: int, tTok: int, maxTok: int) -> str:
    pct    = (cTok / maxTok * 100) if maxTok > 0 else 0
    filled = min(100, int(100 * cTok / maxTok)) if maxTok > 0 else 0
    bar    = "█" * filled + "░" * (100 - filled)
    return (
        f"Tokens — prompt: {pTok} + completion: {cTok} = total: {tTok}\n"
        f"{bar} {YELLOW}{BOLD}{pct:.1f}%{RESET} of {maxTok}"
    )

## Safely tries to parse a JSON string, returning an empty dictionary on failure
def parseJsonSafe(dataStr: str) -> dict:
    try: return json.loads(dataStr)
    except Exception: return {}

if __name__ == "__main__": main()
