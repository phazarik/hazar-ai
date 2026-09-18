#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# CLI query tool
#
# Sends terminal requests through the local LiteLLM gateway.
# Files, optional skills, and saved chats can be added to the prompt.
# Streams Markdown as it arrives, then saves complete replies and files.
# Utility flags can inspect skills or manage memory without an LLM call.
# ----------------------------------------------------------------------------

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
import uuid

## Use a path based on this script so the CLI also works from another folder.
LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
sys.path.insert(0, LIB_DIR)
import memoryManager as mem
import skillLoader as skills
from proxyClient import streamCompletion, PROXY_HEADERS, modelInfoUrl
from tokenOptimizer import optimizeFile, optimizeMessages, getContextLimit
from outputManager import ARTIFACT_PROMPT, captureOutputs
from systemPrompt import SYSTEM_PROMPT
from localModels import isLocal, publicModels

YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"
BOLD = "\033[1m"

def main():
    args = parseArguments()
    if handleUtilityCommands(args): return
    if not args.query:
        print(f"{RED}[ERROR] --query is required{RESET}")
        sys.exit(1)

    ## Keep raw attachments for memory and build a separate prompt text block.
    fileContexts = {}
    contextText = ""
    if args.file: fileContexts, contextText = prepareFileContext(args.file, args.no_memory, args.optimize_tokens)
    else: print(">> No context files attached.")
    finalQuery = args.query
    if contextText: finalQuery += f"\n\nContext files:\n{contextText}"
    messages = buildMessages(finalQuery, args.skill, args.no_memory)

    ## Put artifact rules first so attachment text cannot replace the active task.
    ## Shorten only supported JSON and repeated file blocks.
    systemMessage = {
        "role": "system",
        "content": SYSTEM_PROMPT + "\n" + ARTIFACT_PROMPT,
    }
    messages.insert(0, systemMessage)
    if args.optimize_tokens: messages = optimizeMessages(messages)
    streamResponse(args, messages, finalQuery, fileContexts)

# ----------------
#    Utilities
# ----------------

## Define the CLI model, file, skill, memory, and token options.
def parseArguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the local LiteLLM Smart Proxy.")
    parser.add_argument("--model", default="auto", help="Tier alias or exact local model ID from --list-models")
    parser.add_argument("--list-models", action="store_true", help="Scan local models, without loading weights")
    parser.add_argument("--query", default=None)
    parser.add_argument("--file", nargs="*")
    parser.add_argument("--max-tokens", type=int, default=900)
    parser.add_argument("--skill", default=None, help="Skill to inject (e.g. prompt-master)")
    parser.add_argument("--skill-inspect", default=None, metavar="NAME", help="Print full skill text and exit")
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument("--clear-memory", action="store_true")
    parser.add_argument("--memory-status", action="store_true")
    parser.add_argument("--list-skills", action="store_true")
    parser.add_argument("--optimize-tokens", action="store_true", help="Lossless file deduplication and JSON compaction")
    return parser.parse_args()

## Run inspection or memory commands; return True when no completion is needed.
def handleUtilityCommands(args: argparse.Namespace) -> bool:

    ## List local model choices without starting an inference worker.
    if args.list_models:
        models = publicModels()
        print("Local models:" if models else "No supported local models found in models/.")
        for model in models: print(f"  - {model['id']} [{model['format']}]")
        return True
    
    if args.clear_memory:
        mem.clearMemory()
        return True

    ## One chat is a user message plus its assistant reply.
    if args.memory_status:
        s = mem.memoryStatus()
        print(f"Chats in memory   : {s['chats']}")
        print(f"Summary          : {s['summaryChars']} chars")
        print(f"Cached files     : {s['cachedFiles']}")
        for p in s["fileList"]:
            print(f"  - {p}")
        return True

    if args.list_skills:
        found = skills.listSkills()
        print("Available skills:" if found else "No skills found in ~/.claude/skills/")
        for s in found:
            print(f"  - {s}")
        return True

    if args.skill_inspect:
        text = skills.loadSkill(args.skill_inspect, fullText=True)
        print(text if text else f"Skill '{args.skill_inspect}' not found.")
        return True

    return False

## Read UTF-8 attachments and build delimited reference blocks for the prompt.
def prepareFileContext(filePaths: list, noMemory: bool, optimize: bool) -> tuple[dict, str]:
    fileContexts = {}
    contextText = ""
    print(">> Loading attached files...")
    for filePath in filePaths:
        if not os.path.exists(filePath):
            print(f"{RED}[ERROR] File not found: {filePath}{RESET}")
            sys.exit(1)

        ## Read text as UTF-8 so file contents stay consistent across clients.
        with open(filePath, encoding="utf-8") as f: raw = f.read()
        
        ## A matching hash changes the cache label; this step does not save memory yet.
        sha, cached = mem.registerFile(filePath, raw)
        label = f"{CYAN}(cached){RESET} " if (cached and not noMemory) else "+ "
        print(f"  {label}{filePath}")

        contentToUse = optimizeFile(raw, filePath) if optimize else raw
        contextText += f"\n\n--- FILE: {filePath} ---\n{contentToUse}\n--- END ---\n"
        fileContexts[sha] = {"path": filePath, "content": raw}

    return fileContexts, contextText

## Combine optional skill instructions, saved history, and the active request.
def buildMessages(finalQuery: str, skill: str, noMemory: bool) -> list:
    messages = []

    ## Add the selected installed skill before the conversation history.
    if skill:
        skillMessages = skills.buildSkillMessages(skill)
        if skillMessages:
            print(f">> Injecting skill: {skill}")
            messages.extend(skillMessages)
        else:
            avail = skills.listSkills()
            print(f"{YELLOW}>> Skill '{skill}' not found.{RESET}")
            if avail: print(f"   Available: {', '.join(avail)}")

    ## Skip both the summary and old messages when memory is disabled.
    if not noMemory:
        history, _ = mem.loadMemory()
        if history:
            chats = sum(1 for m in history if m["role"] == "user")
            print(f">> Loaded {chats} chat(s) from memory.")
            messages.extend(history)
        else: print(">> No prior memory. Starting fresh.")
    else: print(">> Memory disabled (--no-memory).")

    ## Keep the active user request last, after skills and previous messages.
    messages.append({"role": "user", "content": finalQuery})
    return messages

## Render streamed Markdown, then save complete output and optional memory.
def streamResponse(args: argparse.Namespace, messages: list, finalQuery: str, fileContexts: dict):
    print(f">> Sending to proxy (model: {args.model}, messages: {len(messages)})")

    ## Ask for streaming text and token usage through the same gateway endpoint.
    payload = {
        "model": args.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": args.max_tokens,
    }
    try:
        actualModel = "unknown"
        runtimeContext = None ## Read local context metadata from the worker that loaded the model.
        console = Console()
        reply = ""
        promptTokens = 0
        completionTokens = 0
        totalTokens = 0

        print(">> Stream starting...\n")
        if actualModel != "unknown": print(f"{YELLOW}>> Model: {BOLD}{actualModel}{RESET}\n")
        displayLogo(console)

        ## Rich redraws the Markdown panel as text arrives; reply keeps the full text.
        with Live(
            buildPanel(reply, f"[Connecting...] {actualModel}"),
            console=console,
            refresh_per_second=15,
        ) as live:

            for data in streamCompletion(payload, lambda text: print(f">> {text}")):

                ## Ignore tier aliases when looking for the actual provider model name.
                if actualModel == "unknown" and "model" in data:
                    reported = data["model"]
                    if reported not in ("auto", "fast", "smart"): actualModel = reported

                ## Local context comes from the worker rather than cloud metadata.
                if data.get("contextLimit"):
                    runtimeContext = data["contextLimit"]

                ## Some providers send usage only in the final event.
                if "usage" in data and data["usage"]:
                    u = data["usage"]
                    promptTokens = u.get("prompt_tokens", promptTokens)
                    completionTokens = u.get("completion_tokens", completionTokens)
                    totalTokens = u.get("total_tokens", totalTokens)

                ## Each content delta is only a fragment, so append it to the running reply.
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if "content" in delta: reply += delta["content"]

                live.update(buildPanel(reply, f"[Generating] {actualModel}"))

        ## The stream must finish successfully before response files are captured.
        if reply:
            manifest = captureOutputs(reply, str(uuid.uuid4()))
            if manifest["artifacts"]:
                print(f"\n>> Outputs: output/{manifest['chatId']}/{manifest['requestId']}")

        ## Store the chat only after the same successful completion check.
        if not args.no_memory and reply:
            mem.appendChat(query, reply, fileContexts if fileContexts else None, allowCompaction=not isLocal(model))
            print("\n>> Chat saved to memory.")

        ## Missing usage gets a rough estimate; this is not an exact tokenizer count.
        if totalTokens == 0 and reply:
            completionTokens = int(len(reply.split()) * 1.3)
            promptTokens = max(1, len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) // 4)
            print(">> Token counts are estimates; backend did not supply usage.")
            totalTokens = promptTokens + completionTokens

        ## Local inference has no provider quota, but context remains finite.
        local = isLocal(args.model)
        contextLimit = runtimeContext if local else getContextLimit(actualModel)
        if local: print(">> Local model: no provider token quota. Context includes prompt + reply.")
        print(f"\n{formatUsage(promptTokens, completionTokens, totalTokens, contextLimit, local)}\n")

    except KeyboardInterrupt:
        print(f"\n{YELLOW}>> Stopped.{RESET}")
        sys.exit(0)
    except (requests.exceptions.RequestException, RuntimeError) as e:
        print(f"\n{RED}[ERROR] Proxy request failed: {e}{RESET}")
        sys.exit(1)

## Apply safe file optimization without removing source whitespace.
def optimizeTokens(content: str) -> str:
    return optimizeFile(content)

## Print the terminal title without line wrapping.
def displayLogo(console: Console):
    ascii_art = pyfiglet.figlet_format("hazar-ai", font="slant")
    console.print(Text(ascii_art, style="bold green"), no_wrap=True)

## Wrap Markdown in a panel and close an unfinished code fence for display.
def buildPanel(text: str, title: str) -> Panel:
    ## Close an open fence only for display; the saved reply stays unchanged.
    if text.count("```") % 2 != 0: text += "\n```"
    return Panel(Markdown(text, code_theme="bw"), title=title, border_style="green", width=110)

## Show token counts against local context or the provider's reported input limit.
def formatUsage(promptTokens: int, completionTokens: int, totalTokens: int,
    contextLimit: int | None, local: bool = False) -> str:
    
    usage = (
        f"Tokens — prompt: {promptTokens} + completion: "
        f"{completionTokens} = total: {totalTokens}\n"
    )
    label = "Context window" if local else "Input-token limit"

    ## Missing metadata stays unknown rather than becoming an infinite limit.
    if contextLimit is None or contextLimit <= 0: return usage + label + ": unknown"

    ## Local prompt and reply occupy the same context window.
    usedTokens = promptTokens + completionTokens if local else promptTokens
    pct = usedTokens / contextLimit * 100
    filled = max(0, min(100, int(pct)))
    bar = "█" * filled + "░" * (100 - filled)
    units = "context tokens" if local else "reported input tokens"

    return (
        usage
        + f"{bar} {YELLOW}{BOLD}{pct:.2f}%{RESET} "
        + f"of {contextLimit:,} {units}"
    )

## Parse JSON and return an empty dictionary if parsing fails.
def parseJsonSafe(dataStr: str) -> dict:
    try: return json.loads(dataStr)
    except Exception: return {}

if __name__ == "__main__": main()
