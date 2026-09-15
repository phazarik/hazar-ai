#!/usr/bin/env python3
# ------------------------------------------------------------------------------
# ui/server.py
#
# Local web interface for PrachuGPT.
# Run:  python3 ui/server.py
# Open: http://localhost:5000
#
# Architecture:
#   GET  /            -> serve index.html
#   GET  /api/skills  -> list available skills
#   GET  /api/status  -> memory status
#   POST /api/query   -> run a query, stream events via SSE
#   POST /api/clear   -> clear memory
#
# The /api/query endpoint returns an SSE stream with these event types:
#   log    -> status/diagnostic lines (shown in the log pane)
#   token  -> a single streamed token from the model
#   done   -> query complete (carries usage stats as JSON)
#   error  -> something went wrong
# ------------------------------------------------------------------------------

import sys, os, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Resolve the lib directory to import our custom modules
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "lib"))
import memoryManager as mem
import skillLoader   as skills
import requests as req_lib

PROXY_URL     = "http://127.0.0.1:4000/chat/completions"
PROXY_HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer sk-anything"}
UI_DIR        = os.path.dirname(os.path.abspath(__file__))
PORT          = 5000

def runServer():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"PrachuGPT Web UI running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopped.")

# Safely tries to parse a JSON string, returning an empty dictionary on failure
def parseJsonSafe(dataStr: str) -> dict:
    if not dataStr: return {}
    try: return json.loads(dataStr)
    except Exception: return {}

# ------------------------------------------------------------------------------
# Server HTTP handler
# ------------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):

    # Suppress default terminal access log noise
    def log_message(self, fmt, *args): pass

    # Sends a python dictionary as a standard JSON HTTP response
    def _sendJson(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    # Sets up the HTTP connection for Server-Sent Events (live streaming)
    def _sendSseHeaders(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    # Formats and sends a single SSE stream chunk to the web UI
    def _writeSse(self, eventType: str, data: str):
        try:
            chunk = f"event: {eventType}\ndata: {data}\n\n"
            self.wfile.write(chunk.encode())
            self.wfile.flush()
        except BrokenPipeError:
            # The user closed the browser tab before the stream finished
            pass

    # Handles CORS preflight checks from the browser
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # Handles page loads and simple read-only API requests
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"): self._serveFile(os.path.join(UI_DIR, "index.html"), "text/html")
        elif path == "/api/skills":      self._sendJson({"skills": skills.listSkills()})
        elif path == "/api/status":      self._sendJson(mem.memoryStatus())
        else:
            self.send_response(404)
            self.end_headers()

    # Handles AI queries and clear-memory actions
    def do_POST(self):
        path   = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/query":
            self._handleQuery(body)
        elif path == "/api/clear":
            mem.clearMemory()
            self._sendJson({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()

    # --------------------------------------------------------------------------
    # Query & stream logic
    # --------------------------------------------------------------------------
    # Connects to the LLM, builds context, and streams the response to the UI
    def _handleQuery(self, body: dict):
        self._sendSseHeaders()

        # Helper to quickly send status messages to the UI's log panel
        def logStream(msg: str): self._writeSse("log", msg)

        query     = body.get("query", "").strip()
        model     = body.get("model", "auto")
        skillName = body.get("skill", "").strip() or None
        noMemory  = body.get("noMemory", False)
        maxTokens = int(body.get("maxTokens", 900))

        if not query:
            self._writeSse("error", "Empty query.")
            return

        # Build the conversation history and inject skills
        messages = []
        if skillName:
            skillMsgs = skills.buildSkillMessages(skillName)
            if skillMsgs:
                logStream(f"Injecting skill: {skillName}")
                messages.extend(skillMsgs)
            else: logStream(f"WARNING: Skill '{skillName}' not found.")

        if not noMemory:
            history, _ = mem.loadMemory()
            if history:
                turns = sum(1 for m in history if m["role"] == "user")
                logStream(f"Loaded {turns} turn(s) from memory.")
                messages.extend(history)
            else: logStream("No prior memory. Starting fresh.")
        else: logStream("Memory disabled for this query.")

        messages.append({"role": "user", "content": query})
        logStream(f"Sending to proxy (model: {model}, messages: {len(messages)})")
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": maxTokens,
        }
        
        reply       = ""
        actualModel = "unknown"
        pTok = cTok = tTok = 0

        # Send the request and process the streaming chunks
        try:
            resp = req_lib.post(PROXY_URL, headers=PROXY_HEADERS, json=payload, stream=True, timeout=60)
            if resp.status_code != 200:
                self._writeSse("error", f"Upstream proxy error: {resp.status_code}")
                return

            for line in resp.iter_lines():
                if not line: continue
                lineStr = line.decode("utf-8")

                if not lineStr.startswith("data: "): continue
                dataStr = lineStr[6:]
                if dataStr == "[DONE]": break

                data = parseJsonSafe(dataStr)
                if not data: continue

                if actualModel == "unknown" and "model" in data:
                    actualModel = data["model"]
                    logStream(f"Model: {actualModel}")

                if "usage" in data and data["usage"]:
                    u    = data["usage"]
                    pTok = u.get("prompt_tokens", pTok)
                    cTok = u.get("completion_tokens", cTok)
                    tTok = u.get("total_tokens", tTok)

                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        reply += token
                        self._writeSse("token", token)

            # Save to memory after completion
            if not noMemory and reply:
                mem.appendTurn(query, reply)
                logStream("Turn saved to memory.")

            # Fallback token estimation if the API did not provide usage stats
            if tTok == 0 and reply:
                cTok = int(len(reply.split()) * 1.3)
                pTok = int(len(query.split()) * 1.3)
                tTok = pTok + cTok

            # Signal completion to the frontend with final usage statistics
            self._writeSse("done", json.dumps({
                "model": actualModel,
                "promptTokens": pTok,
                "completionTokens": cTok,
                "totalTokens": tTok,
                "maxTokens": maxTokens,
            }))

        except Exception as e: self._writeSse("error", str(e))

    # Reads a file from disk and sends it directly to the browser
    def _serveFile(self, path: str, mimeType: str):
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
