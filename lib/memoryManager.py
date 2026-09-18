#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Shared chat memory
#
# Keeps conversation messages, a rolling summary, and attached-file metadata.
# Both clients use the memory folder beside the setup scripts.
# Older chats are summarized after the window fills up.
# If summarizing fails, the full history stays available.
# ----------------------------------------------------------------------------

import os
import json
import hashlib
import requests
from datetime import datetime
from typing import Any
from proxyClient import PROXY_URL, PROXY_HEADERS
import tempfile

## All memory files stay together beside the setup, not in the current shell folder.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
GRAPH_FILE = os.path.join(MEMORY_DIR, "graph.json")
SUMMARY_FILE = os.path.join(MEMORY_DIR, "summary.txt")
FILES_FILE = os.path.join(MEMORY_DIR, "files.json")

## Both limits count complete user/assistant chat pairs.
WINDOW_SIZE = 20
COMPACT_KEEP = 10

## The summary asks for decisions and task state, not just a shorter transcript.
COMPACT_PROMPT = (
    "Compress memory for an ongoing AI coding session. "
    "Produce a dense, structured summary that preserves:\n"
    "- Every decision made and why\n"
    "- Every file mentioned or modified\n"
    "- Every error and how it was resolved\n"
    "- Current state of any ongoing task\n"
    "- User preferences or constraints\n\n"
    "Be terse. Use bullet points. Omit pleasantries.\n\nConversation:\n{conversation}"
)

## Read a saved JSON value; use the default if the file is missing.
def readJson(path: str, defaultVal: Any) -> Any:
    if not os.path.exists(path): return defaultVal
    with open(path, encoding="utf-8") as f: return json.load(f)

def writeJson(path: str, data: Any):
    # ----------------------------------------------------------------------
    # Write JSON to a temporary file, then replace the target.
    # The temporary file is in the memory directory so replacement stays on
    # the same filesystem. The final file is not exposed half-written.
    # ----------------------------------------------------------------------
    if not os.path.exists(MEMORY_DIR): os.makedirs(MEMORY_DIR)
    ## Write beside the target so the final replacement stays on one filesystem.
    fd, temp = tempfile.mkstemp(dir=MEMORY_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp, path)
        
    finally: ## Remove any leftover temporary file if writing or replacement fails.
        if os.path.exists(temp): os.remove(temp)

## Read the stored user and assistant messages.
def loadGraph() -> list: return readJson(GRAPH_FILE, [])

## Save the message history as JSON.
def saveGraph(messages: list): writeJson(GRAPH_FILE, messages)

## Read the cached file metadata.
def loadFiles() -> dict: return readJson(FILES_FILE, {})

## Save the cached file metadata.
def saveFiles(files: dict): writeJson(FILES_FILE, files)

## Read the memory summary, or return empty text if it is missing.
def loadSummary() -> str:
    if not os.path.exists(SUMMARY_FILE): return ""
    with open(SUMMARY_FILE, encoding="utf-8") as f: return f.read().strip()

## Write the memory summary as UTF-8 text.
def saveSummary(text: str):
    if not os.path.exists(MEMORY_DIR): os.makedirs(MEMORY_DIR)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f: f.write(text)

## Create a short content hash for the file cache.
def hashContent(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]

def compactChats(messages: list) -> list:
    # ------------------------------------------------------------------------
    # Summarize older messages and retain the recent message pairs.
    # COMPACT_KEEP counts complete user/assistant pairs. Existing summary
    # text is included in the next summary request. A failed or empty summary
    # leaves the full message history in place.
    # ------------------------------------------------------------------------
    
    ## Each chat has two messages, so retaining 10 chats means retaining 20 messages.
    oldMessages = messages[: -(COMPACT_KEEP * 2)]
    recentMessages = messages[-(COMPACT_KEEP * 2) :]
    flat = "\n\n".join(f"[{t['role'].upper()}] {t['content']}" for t in oldMessages)

    ## Carry the previous summary into the next one so earlier context is not dropped.
    existing = loadSummary()
    if existing: flat = f"[PREVIOUS SUMMARY]\n{existing}\n\n[NEW CHATS]\n{flat}"

    ## Summarizing is a separate non-streaming request to the fast route.
    print(">> Compacting memory...")
    payload = {
        "model": "fast",
        "messages": [
            {"role": "user", "content": COMPACT_PROMPT.format(conversation=flat)}
        ],
        "max_tokens": 600,
        "stream": False,
    }
    try:  resp = requests.post(PROXY_URL, headers=PROXY_HEADERS, json=payload, timeout=30)
    except requests.exceptions.RequestException:
        print(">> Compaction unavailable. Keeping full history.")
        return messages

    ## Only a non-empty, readable summary can replace the older messages.
    if resp.status_code == 200:
        try:
            summary = resp.json()["choices"][0]["message"]["content"].strip()
            if not summary: return messages
        except (ValueError, KeyError, IndexError, TypeError, AttributeError): return messages
        saveSummary(summary)
        print(f">> Compacted. Summary: {len(summary)} chars.")
        return recentMessages

    print(">> Compaction failed. Keeping full history.")
    return messages

## Build context from the summary and saved messages; return the file cache separately.
def loadMemory() -> tuple[list, dict]:
    graph = loadGraph()
    summary = loadSummary()
    fileCache = loadFiles()
    messages = []

    ## Place the summary before recent messages; stored timestamps are not prompt text.
    if summary: messages.append({"role": "system", "content": f"[LONG-TERM MEMORY CONTEXT]\n{summary}"})
    historyMessages = [{"role": m["role"], "content": m["content"]} for m in graph]
    messages.extend(historyMessages)
    return messages, fileCache

## Save one user/assistant pair and compact history when the chat limit is exceeded.
def appendChat(userContent: str, assistantContent: str, filesUsed: dict | None = None, allowCompaction: bool = True,):
    graph = loadGraph()
    graph.append({"role": "user", "content": userContent, "ts": datetime.utcnow().isoformat()})
    graph.append({"role": "assistant", "content": assistantContent})
    
    ## Check the window in message pairs, then save the updated history.
    ## Local chats must not trigger the cloud-backed summary request.
    if allowCompaction and len(graph) > WINDOW_SIZE * 2: graph = compactChats(graph)
    saveGraph(graph)
    if filesUsed: ## Save attachment metadata only after the chat has completed.
        existing = loadFiles()
        existing.update(filesUsed)
        saveFiles(existing)

## Report the content hash and whether that content is already cached.
def registerFile(path: str, content: str) -> tuple[str, bool]:
    ## This lookup reports cache status without changing the saved cache.
    sha = hashContent(content)
    cache = loadFiles()
    return sha, (sha in cache)

## Remove the saved history, summary, and file cache.
def clearMemory():
    for f in [GRAPH_FILE, SUMMARY_FILE, FILES_FILE]:
        if os.path.exists(f): os.remove(f)
    print(">> Memory cleared.")

## Return chat counts, summary length, and up to five cached file paths.
def memoryStatus() -> dict:
    graph = loadGraph()
    summary = loadSummary()
    files = loadFiles()
    return {
        "chats": len(graph) // 2,
        "summaryChars": len(summary),
        "cachedFiles": len(files),
        "fileList": [v.get("path", "?") for v in list(files.values())[:5]],
    }
