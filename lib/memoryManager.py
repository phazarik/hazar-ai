#!/usr/bin/env python3
# ------------------------------------------------------------------------------
# Memory manager module
#
# This module maintains the persistent conversation memory for the workspace.
# It uses a rolling window approach: keeping recent messages intact while
# summarizing older messages to conserve token space. Cached files are hashed
# to prevent duplicate context loading.
# ------------------------------------------------------------------------------

import os
import json
import hashlib
import requests
from datetime import datetime
from typing import Any

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR   = os.path.join(BASE_DIR, "memory")
GRAPH_FILE   = os.path.join(MEMORY_DIR, "graph.json")
SUMMARY_FILE = os.path.join(MEMORY_DIR, "summary.txt")
FILES_FILE   = os.path.join(MEMORY_DIR, "files.json")

## WINDOW_SIZE defines the max turns before triggering summarization.
## COMPACT_KEEP defines how many recent turns remain untouched after a summary.
WINDOW_SIZE  = 20
COMPACT_KEEP = 10

PROXY_URL     = "http://127.0.0.1:4000/chat/completions"
PROXY_HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer sk-anything"}

## A strict, concatenated string prompt to instruct the model on how to compress memory.
## Implicit string concatenation is used to avoid problematic multi-line string syntax.
COMPACT_PROMPT = (
    "You are a memory compressor for an ongoing AI coding session. "
    "Produce a dense, structured summary that preserves:\n"
    "- Every decision made and why\n"
    "- Every file mentioned or modified\n"
    "- Every error and how it was resolved\n"
    "- Current state of any ongoing task\n"
    "- User preferences or constraints\n\n"
    "Be terse. Use bullet points. Omit pleasantries.\n\nConversation:\n{conversation}"
)

# ------------------------------------------------------------------------------
# Core I/O Helpers
# ------------------------------------------------------------------------------

## Safely reads a JSON file. Employs the os module to verify existence
## rather than relying on exception handling.
def readJson(path: str, defaultVal: Any) -> Any:
    if not os.path.exists(path): return defaultVal
    with open(path) as f:        return json.load(f)

## Ensures the destination directory exists via the os module, then writes JSON.
def writeJson(path: str, data: Any):
    if not os.path.exists(MEMORY_DIR): os.makedirs(MEMORY_DIR)
    with open(path, "w") as f:    json.dump(data, f, indent=2)

def loadGraph() -> list:
    return readJson(GRAPH_FILE, [])

def saveGraph(turns: list):
    writeJson(GRAPH_FILE, turns)

def loadFiles() -> dict:
    return readJson(FILES_FILE, {})

def saveFiles(files: dict):
    writeJson(FILES_FILE, files)

def loadSummary() -> str:
    if not os.path.exists(SUMMARY_FILE): return ""
    with open(SUMMARY_FILE) as f:        return f.read().strip()

def saveSummary(text: str):
    if not os.path.exists(MEMORY_DIR): os.makedirs(MEMORY_DIR)
    with open(SUMMARY_FILE, "w") as f: f.write(text)

## Generates a short SHA-256 hash for raw text to track file duplications.
def hashContent(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]

# ------------------------------------------------------------------------------
# Compression Logic
# ------------------------------------------------------------------------------

## When the history gets too large, this function slices the oldest turns,
## formats them, and asks the local proxy (fast model) to summarize them.
def compactTurns(turns: list) -> list:
    oldTurns  = turns[:-COMPACT_KEEP]
    keepTurns = turns[-COMPACT_KEEP:]
    
    ## Flatten the old dialogue into a single readable string
    flat = "\n\n".join(f"[{t['role'].upper()}] {t['content']}" for t in oldTurns)
    existing = loadSummary()
    if existing: flat = f"[PREVIOUS SUMMARY]\n{existing}\n\n[NEW TURNS]\n{flat}"

    print(">> Compacting memory...")
    payload = {
        "model": "fast",
        "messages": [{"role": "user", "content": COMPACT_PROMPT.format(conversation=flat)}],
        "max_tokens": 600,
        "stream": False,
    }
    
    resp = requests.post(PROXY_URL, headers=PROXY_HEADERS, json=payload, timeout=30)
    if resp.status_code == 200:
        summary = resp.json()["choices"][0]["message"]["content"].strip()
        saveSummary(summary)
        print(f">> Compacted. Summary: {len(summary)} chars.")
        return keepTurns
        
    print(">> Compaction failed. Keeping full history.")
    return turns

# ------------------------------------------------------------------------------
# Public Interface
# ------------------------------------------------------------------------------

## Retrieves active context. Long-term memory is injected as a 'system' role
## to take advantage of prompt caching on the provider side.
def loadMemory() -> tuple[list, dict]:
    graph     = loadGraph()
    summary   = loadSummary()
    fileCache = loadFiles()
    messages  = []
    if summary: messages.append({"role": "system", "content": f"[LONG-TERM MEMORY CONTEXT]\n{summary}"})
    clean_graph = [{"role": m["role"], "content": m["content"]} for m in graph]
    messages.extend(clean_graph)
    return messages, fileCache

## Logs a new back-and-forth interaction. Triggers compression if limits are hit.
def appendTurn(userContent: str, assistantContent: str, filesUsed: dict | None = None):
    graph = loadGraph()
    graph.append({"role": "user", "content": userContent, "ts": datetime.utcnow().isoformat()})
    graph.append({"role": "assistant", "content": assistantContent})
    if len(graph) > WINDOW_SIZE * 2: graph = compactTurns(graph)
    saveGraph(graph)
    if filesUsed:
        existing = loadFiles()
        existing.update(filesUsed)
        saveFiles(existing)

def registerFile(path: str, content: str) -> tuple[str, bool]:
    sha   = hashContent(content)
    cache = loadFiles()
    return sha, (sha in cache)

## Iterates through expected memory files and purges them via the os module.
def clearMemory():
    for f in [GRAPH_FILE, SUMMARY_FILE, FILES_FILE]:
        if os.path.exists(f): os.remove(f)
    print(">> Memory cleared.")

def memoryStatus() -> dict:
    graph   = loadGraph()
    summary = loadSummary()
    files   = loadFiles()
    return {
        "turns":        len(graph) // 2,
        "summaryChars": len(summary),
        "cachedFiles":  len(files),
        "fileList":     [v.get("path", "?") for v in list(files.values())[:5]],
    }