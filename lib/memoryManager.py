#!/usr/bin/env python3
# ------------------------------------------------------------------------------
# This module manages the persistent conversation memory for the AI.
# It maintains a rolling window of recent messages, automatically summarizes
# older messages to save context space, and keeps a deduplicated file cache.
# ------------------------------------------------------------------------------

import os, json, hashlib, requests
from datetime import datetime
from typing import Any

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR   = os.path.join(BASE_DIR, "memory")
GRAPH_FILE   = os.path.join(MEMORY_DIR, "graph.json")
SUMMARY_FILE = os.path.join(MEMORY_DIR, "summary.txt")
FILES_FILE   = os.path.join(MEMORY_DIR, "files.json")

WINDOW_SIZE  = 20    # Maximum turns to keep before compressing
COMPACT_KEEP = 10    # Number of recent turns to keep exactly as they are

PROXY_URL     = "http://127.0.0.1:4000/chat/completions"
PROXY_HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer sk-anything"}

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
# Internal file helpers
# ------------------------------------------------------------------------------
     
# Safely reads a JSON file and returns a default value if it fails or is missing
def readJson(path: str, defaultVal: Any) -> Any:
    if not os.path.exists(path): return defaultVal
    with open(path) as f: return json.load(f)

# Safely writes data to a JSON file and creates the directory if needed
def writeJson(path: str, data: Any):
    if not os.path.exists(MEMORY_DIR): os.makedirs(MEMORY_DIR)
    with open(path, "w") as f: json.dump(data, f, indent=2)

# ------------------------------------------------------------------------------
# Data loading & saving
# ------------------------------------------------------------------------------

# Loads the recent conversation turns
def loadGraph() -> list:
    return readJson(GRAPH_FILE, [])

# Saves the recent conversation turns
def saveGraph(turns: list):
    writeJson(GRAPH_FILE, turns)

# Loads the hashed files cache
def loadFiles() -> dict:
    return readJson(FILES_FILE, {})

# Saves the hashed files cache
def saveFiles(files: dict):
    writeJson(FILES_FILE, files)

# Loads the long-term memory summary text
def loadSummary() -> str:
    if not os.path.exists(SUMMARY_FILE): return ""
    with open(SUMMARY_FILE) as f: return f.read().strip()

# Saves the long-term memory summary text
def saveSummary(text: str):
    if not os.path.exists(MEMORY_DIR): os.makedirs(MEMORY_DIR)
    with open(SUMMARY_FILE, "w") as f: f.write(text)

# Creates a short hash of the file content so we do not save duplicates
def hashContent(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]

# Summarizes older conversation turns through the API to save context space
def compactTurns(turns: list) -> list:
    oldTurns  = turns[:-COMPACT_KEEP]
    keepTurns = turns[-COMPACT_KEEP:]
    flat      = "\n\n".join(f"[{t['role'].upper()}] {t['content']}" for t in oldTurns)
    existing  = loadSummary()
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

# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

# Retrieves the full memory (summary + recent turns) and the cached files
def loadMemory() -> tuple[list, dict]:
    graph     = loadGraph()
    summary   = loadSummary()
    fileCache = loadFiles()
    messages  = []
    
    if summary:
        messages.append({"role": "user", "content": f"[MEMORY CONTEXT]\n{summary}"})
        messages.append({"role": "assistant", "content": "Understood, I have the context from our previous sessions."})
        
    messages.extend(graph)
    return messages, fileCache

# Saves a new interaction and triggers compression if the history gets too long
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

# Hashes file content and checks if it is already known in the cache
def registerFile(path: str, content: str) -> tuple[str, bool]:
    sha   = hashContent(content)
    cache = loadFiles()
    return sha, (sha in cache)

# Deletes all saved memory and cache files
def clearMemory():
    for f in [GRAPH_FILE, SUMMARY_FILE, FILES_FILE]:
        if os.path.exists(f): os.remove(f)
    print(">> Memory cleared.")

# Returns statistics about the current memory usage
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
