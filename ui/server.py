#!/usr/bin/env python3
# ------------------------------------------------------------------------------
# Local Web Interface Backend
#
# This script spins up a standard Python HTTP server. It serves static assets
# for the UI and exposes a simple REST/SSE API to communicate with the proxy.
#
# Architecture mapping:
#   GET  /            -> serves index.html
#   GET  /api/skills  -> lists available system prompts/skills
#   GET  /api/status  -> provides memory diagnostic status
#   POST /api/query   -> runs an LLM query and streams events via SSE
#   POST /api/clear   -> clears historical memory caches
# ------------------------------------------------------------------------------

import sys
import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import requests as req_lib

## Dynamically resolve the path to the 'lib' directory so custom modules 
## can be imported reliably.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "lib"))

import memoryManager as mem
import skillLoader as skills

## The proxy endpoint details. The UI server acts as a middleman, receiving
## web traffic from the browser and formatting it for the LiteLLM proxy.
# ui/server.py (Around lines 31-32)
PROXY_URL     = "http://127.0.0.1:4000/chat/completions"
PROXY_HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer sk-anything"}
UI_DIR        = os.path.dirname(os.path.abspath(__file__))
PORT          = 5000

## Initializes the HTTP server on port 5000, listening to all local interfaces.
def runServer():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"hazar-ai Web UI running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopped.")

## Safely attempts to parse a string into JSON. Returns an empty dictionary
## if the format is malformed to avoid crashing the server loop.
def parseJsonSafe(dataStr: str) -> dict:
    if not dataStr: return {}
    try: return json.loads(dataStr)
    except Exception: return {}

## The core server class that handles every incoming HTTP connection.
class Handler(BaseHTTPRequestHandler):

    ## Suppresses standard terminal access log output to keep the terminal logs
    ## readable, avoiding a wall of "GET / HTTP 200" messages.
    def log_message(self, fmt, *args): pass

    ## Helper method to format and send JSON responses back to the browser.
    ## Automatically manages headers and CORS policy to ensure the frontend accepts it.
    def sendJson(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    # --------------------------------------------------------------------------
    # Server-Sent Events (SSE) Protocol Helpers
    # --------------------------------------------------------------------------

    ## Prepares the HTTP headers to maintain an open connection for streaming data.
    ## The 'text/event-stream' type tells the browser to keep reading chunks indefinitely.
    def sendSseHeaders(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    ## Formats the event string according to SSE standards ("event: \n data: \n\n")
    ## and flushes it immediately down the socket to the client.
    def writeSse(self, eventType: str, data: str):
        try:
            chunk = f"event: {eventType}\ndata: {data}\n\n"
            self.wfile.write(chunk.encode())
            self.wfile.flush()
        except BrokenPipeError:
            ## Safely handles the scenario where a user closes the browser tab mid-stream.
            pass

    ## Handles Cross-Origin Resource Sharing (CORS) preflight requests.
    ## This prevents the browser from blocking requests made via JavaScript.
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    ## Routes incoming GET requests based on the URL path.
    ## Acts as a simple static file server for the UI elements, or responds with JSON
    ## for API read endpoints.
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"): self.serveFile(os.path.join(UI_DIR, "index.html"), "text/html")
        elif path == "/style.css":       self.serveFile(os.path.join(UI_DIR, "style.css"), "text/css")
        elif path == "/script.js":       self.serveFile(os.path.join(UI_DIR, "script.js"), "application/javascript")
        elif path == "/api/skills":      self.sendJson({"skills": skills.listSkills()})
        elif path == "/api/status":      self.sendJson(mem.memoryStatus())
        elif path == "/.image/logo.png": self.serveFile(os.path.join(BASE_DIR, ".image", "logo.png"), "image/png")

        ## Restore history on refresh
        elif path == "/api/history":
            history, _ = mem.loadMemory() 
            self.sendJson({"history": history})

        else:
            self.send_response(404)
            self.end_headers()

    ## Routes incoming POST payloads to trigger specific actions (like inference).
    def do_POST(self):
        path = urlparse(self.path).path
        
        ## Read the raw byte body from the incoming HTTP request and parse it to JSON.
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/query":
            self.handleQuery(body)
        elif path == "/api/clear":
            mem.clearMemory()
            self.sendJson({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()

    def getContextLimit(self, model_name: str) -> int:
        ## Attempts to fetch the true context window size from the LiteLLM proxy.
        limit = 8192
        try:
            resp = req_lib.get("http://127.0.0.1:4000/model/info", headers=PROXY_HEADERS, timeout=2)
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                for m in models:
                    if m.get("model_name") == model_name or m.get("id") == model_name:
                        info = m.get("model_info", {})
                        ## LiteLLM stores limits under different keys depending on the provider
                        found = info.get("max_input_tokens") or m.get("max_input_tokens") or info.get("max_tokens")
                        if found: limit = int(found)
                        break
        except Exception: pass
            
        ## Fallback if the proxy is missing the exact data
        if limit == 8192:
            lower_name = model_name.lower()
            if "gemini" in lower_name: limit = 1048576
            elif "deepseek-r1" in lower_name: limit = 128000
            elif "qwen" in lower_name: limit = 32768
            
        return limit

    # --------------------------------------------------------------------------
    # Core Proxy Passthrough Logic
    # --------------------------------------------------------------------------
    
    ## Executes the main LLM interaction. Builds the conversation context, opens a stream
    ## to the proxy server, and pipes the data chunks back to the browser in real-time.
    def handleQuery(self, body: dict):
        self.sendSseHeaders()

        ## Extract options defined by the web UI request payload.
        query     = body.get("query", "").strip()
        files     = body.get("files", []) or []
        model     = body.get("model", "auto")
        skillName = body.get("skill", "").strip() or None
        noMemory  = body.get("noMemory", False)
        maxTokens = body.get("maxTokens")

        if not query:
            self.writeSse("error", "Empty query.")
            return

        ## Step 0: Process any attached files the same way the CLI does —
        ## hash each one, note whether it's already cached in memory, and
        ## append its contents to the prompt in a clearly delimited block.
        fileContexts = {}
        if files:
            contextText = ""
            for f in files:
                name = f.get("name", "unnamed")
                content = f.get("content", "")
                sha, cached = mem.registerFile(name, content)
                label = "(cached) " if (cached and not noMemory) else "+ "
                self.writeSse("log", f"{label}{name}")
                contextText += f"\n\n--- FILE: {name} ---\n{content}\n--- END ---\n"
                fileContexts[sha] = {"path": name, "content": content}
            query += f"\n\nContext files:\n{contextText}"

        ## Step 1: Build context.
        ## Load custom skills and previous conversation memory.
        messages = []
        
        if skillName:
            skillMsgs = skills.buildSkillMessages(skillName)
            if skillMsgs:
                self.writeSse("log", f"Injecting skill: {skillName}")
                messages.extend(skillMsgs)
            else:
                self.writeSse("log", f"WARNING: Skill '{skillName}' not found.")

        if not noMemory:
            history, _ = mem.loadMemory()
            if history:
                turns = sum(1 for m in history if m["role"] == "user")
                self.writeSse("log", f"Loaded {turns} chat(s) from memory.")
                messages.extend(history)
            else: self.writeSse("log", "No prior memory. Starting fresh.")
        else: self.writeSse("log", "Memory disabled for this query.")

        ## Step 2: Append the current request and system persona instructions.
        messages.append({"role": "user", "content": query})
        
        ## Inject the overarching persona definition to stabilize the model's behavior.
        system_msg = {
            "role": "system",
            "content": "You are Morpheus. The user is Neo. "
            "You have perfect memory of all previous turns provided in this context. "
            "Format your responses cleanly in Markdown. "
            "Do not start your response with a large header."
        }
        messages.insert(0, system_msg)
        self.writeSse("log", f"Sending to proxy (model: {model}, messages: {len(messages)})")
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        
        ## Only include max_tokens if explicitly requested (not toggled off)
        if maxTokens is not None:
            payload["max_tokens"] = int(maxTokens)
        
        reply = ""
        actualModel = "unknown"
        pTok = 0
        cTok = 0
        tTok = 0

        ## Step 3: Stream data from the proxy, parse it, and pipe it down to the UI.
        try:
            ## Initiate a connection to the local LiteLLM proxy port.
            resp = req_lib.post(PROXY_URL, headers=PROXY_HEADERS, json=payload, stream=True, timeout=60)
            if resp.status_code != 200:
                self.writeSse("error", f"Upstream proxy error: {resp.status_code}")
                return

            ## Pluck the absolute model name from the initial headers to bypass the aliasing problem
            ## (e.g., displaying the real model ID instead of 'fast' or 'smart').
            actualModel = resp.headers.get("x-litellm-model-name", "unknown")
            if actualModel != "unknown": self.writeSse("log", f"Model: {actualModel}")

            ## Read the raw byte stream from the proxy line by line.
            for line in resp.iter_lines():
                if not line: continue
                lineStr = line.decode("utf-8")
                if not lineStr.startswith("data: "): continue
                dataStr = lineStr[6:]
                if dataStr == "[DONE]": break
                data = parseJsonSafe(dataStr)
                if not data: continue

                ## Fallback check if headers missed the model name.
                if "model" in data and isinstance(data["model"], str):
                    reported_model = data["model"]
                    if reported_model not in ("auto", "fast", "smart") and actualModel == "unknown":
                        actualModel = reported_model
                        self.writeSse("log", f"Model: {actualModel}")

                ## Capture token utilization metrics sent in the final stream chunk.
                if "usage" in data and data["usage"]:
                    u    = data["usage"]
                    pTok = u.get("prompt_tokens", pTok)
                    cTok = u.get("completion_tokens", cTok)
                    tTok = u.get("total_tokens", tTok)

                ## Extract the delta text fragment and forward it to the browser.
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        reply += token
                        self.writeSse("token", json.dumps(token))
            
            ## Post-generation cleanup: save the final conversation back to the memory manager.
            if not noMemory and reply:
                mem.appendTurn(query, reply, fileContexts if fileContexts else None)
                self.writeSse("log", "Chat saved to memory.")

            ## Calculate estimates if usage stats are missing from the provider API,
            ## ensuring the UI progress bar still functions roughly.
            if tTok == 0 and reply:
                cTok = int(len(reply.split()) * 1.3)
                pTok = int(len(query.split()) * 1.3)
                tTok = pTok + cTok

            ## Fetch the true context limit from the LiteLLM proxy
            context_limit = self.getContextLimit(actualModel)

            ## Finalize the stream and push statistics as a final 'done' event.
            self.writeSse("done", json.dumps({
                "model": actualModel,
                "promptTokens": pTok,
                "completionTokens": cTok,
                "totalTokens": tTok,
                "contextLimit": context_limit
            }))

        except Exception as e:
            ## Trap any socket errors or parsing failures and log them directly to the UI panel.
            self.writeSse("error", str(e))

    ## Reads a local file from disk and streams it directly to the HTTP socket.
    ## Used primarily to serve the static frontend assets (HTML, JS, CSS).
    def serveFile(self, path: str, mimeType: str):
        if not os.path.exists(path):
            self.send_response(404)
            self.end_headers()
            return
            
        with open(path, "rb") as f: data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mimeType)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

if __name__ == "__main__": runServer()
