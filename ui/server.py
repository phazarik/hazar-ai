#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Web UI backend
#
# Serves the browser page, styles, script, and logo on port 5000.
# API routes expose skills, memory, history, and generated downloads.
# Query requests are sent to the gateway and streamed back as SSE events.
# Only complete replies are saved to memory and the output folder.
# ----------------------------------------------------------------------------

import sys
import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs
import uuid
import requests as req_lib

## Import shared helpers by script location so startup works from any shell folder.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "lib"))
import memoryManager as mem
import skillLoader as skills
from proxyClient import streamCompletion, PROXY_HEADERS, modelInfoUrl
from tokenOptimizer import optimizeMessages, getContextLimit
from outputManager import (
    ARTIFACT_PROMPT,
    captureOutputs,
    validChatId,
    OUTPUT_DIR,
    isWithinDirectory,
)
from systemPrompt import SYSTEM_PROMPT

UI_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 5000

## Serve UI assets and API requests on port 5000 until interrupted.
## Bind port 5000 on all interfaces; this interface is for a trusted local setup.
def runServer():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"hazar-ai Web UI running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopped.")
    finally: server.server_close()

## Parse JSON and return an empty dictionary if parsing fails.
def parseJsonSafe(dataStr: str) -> dict:
    if not dataStr: return {}
    try: return json.loads(dataStr)
    except Exception: return {}

class Handler(BaseHTTPRequestHandler):

    ## Skip the usual HTTP access logs to keep the terminal readable.
    def log_message(self, fmt, *args): pass

    ## Send a JSON response with its content length and CORS header.
    ## Allow browser requests across origins; there is no separate browser login here.
    def sendJson(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    ## Open an event stream and disable response buffering.
    def sendSseHeaders(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    # --------------------------------------------------------------------
    # Write one event and flush it immediately.
    # Each frame contains an event name and one data line, followed by a
    # blank line. Token text is JSON-encoded before this method is called
    # so embedded newlines do not split the frame.
    # --------------------------------------------------------------------
    def writeSse(self, eventType: str, data: str):
        try:
            chunk = f"event: {eventType}\ndata: {data}\n\n"
            self.wfile.write(chunk.encode())
            self.wfile.flush()
        except BrokenPipeError: pass

    ## Respond to browser CORS preflight requests.
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    ## Route asset, skill, history, status, and safe artifact download requests.
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"): self.serveFile(os.path.join(UI_DIR, "index.html"), "text/html")
        elif path == "/style.css":       self.serveFile(os.path.join(UI_DIR, "style.css"), "text/css")
        elif path == "/script.js":  self.serveFile(os.path.join(UI_DIR, "script.js"), "application/javascript")
        elif path == "/api/skills": self.sendJson({"skills": skills.listSkills()})
        ## Inspection uses full text; the query path still applies the normal injection limit.
        elif path == "/api/skill":
            name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
            content = skills.loadSkill(name, fullText=True)
            if content is None: self.sendJson({"error": "Skill not found"}, 404)
            else:               self.sendJson({"name": name, "content": content})
        elif path == "/api/status": self.sendJson(mem.memoryStatus())
        elif path == "/.image/logo.png": self.serveFile(os.path.join(BASE_DIR, ".image", "logo.png"), "image/png")
        elif path == "/api/history":
            history, _ = mem.loadMemory()
            self.sendJson({"history": history})
            
        # -------------------------------------------------------------------------------
        # Decode the requested filename, then resolve links and check its final location.
        # Only files inside OUTPUT_DIR are served.
        # A sibling folder with a similar name must not pass the containment check.
        # -------------------------------------------------------------------------------
        elif path.startswith("/api/output/"):
            relative = unquote(path[len("/api/output/") :])
            target = os.path.realpath(os.path.join(OUTPUT_DIR, relative))
            if not isWithinDirectory(target, OUTPUT_DIR) or not os.path.isfile(target):
                self.sendJson({"error": "Output not found"}, 404)
                return
            self.serveFile(str(target), "application/octet-stream")
        else:
            self.send_response(404)
            self.end_headers()

    ## Validate the JSON request size and route query or memory-clear requests.
    def do_POST(self):
        path = urlparse(self.path).path
        try: length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.sendJson({"error": "Invalid length"}, 400)
            return
        ## Reject oversized payloads before reading them into memory.
        if length < 0 or length > 16 * 1024 * 1024:
            self.sendJson({"error": "Request too large"}, 413)
            return
        ## The API accepts a JSON object rather than a list, scalar, or broken JSON text.
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(body, dict): raise ValueError("Object required")
        except (ValueError, UnicodeDecodeError):
            self.sendJson({"error": "Invalid JSON object"}, 400)
            return

        if path == "/api/query":
            self.handleQuery(body)
        elif path == "/api/clear":
            mem.clearMemory()
            self.sendJson({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()

    ## Validate options, build context, stream a completion, and save successful results.
    def handleQuery(self, body: dict):
        try:
            if not isinstance(body.get("query", ""), str):  raise ValueError("Invalid query")
            if not isinstance(body.get("files", []), list): raise ValueError("Invalid files")
            ## Check attachment types and reject line breaks in delimiter filenames.
            for file in body.get("files", []):
                if (not isinstance(file, dict)
                    or not isinstance(file.get("name"), str)
                    or not isinstance(file.get("content"), str)):
                    raise ValueError("Invalid file")
                if "\n" in file["name"] or "\r" in file["name"]:
                    raise ValueError("Invalid filename")
            if not isinstance(body.get("model", "auto"), str) or not isinstance(body.get("skill", ""), str):
                raise ValueError("Invalid options")
            if body.get("maxTokens") is not None and (
                not isinstance(body["maxTokens"], int)
                or not 1 <= body["maxTokens"] <= 1000000):
                raise ValueError("Invalid Max Tokens")
            chatId = validChatId(body.get("chatId") or str(uuid.uuid4()))
        except (ValueError, TypeError, AttributeError) as error:
            self.sendJson({"error": str(error)}, 400)
            return
        
        ## After headers are sent, query progress and errors must use stream events.
        self.sendSseHeaders()
        self.writeSse("meta", json.dumps({"chatId": chatId}))
        query = body.get("query", "").strip()
        files = body.get("files", []) or []
        model = body.get("model", "auto")
        skillName = body.get("skill", "").strip() or None
        noMemory = body.get("noMemory", False)
        maxTokens = body.get("maxTokens")
        if not query:
            self.writeSse("error", "Empty query.")
            return

        ## Keep raw attachments for memory and add delimited text to the active query.
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

        ## Build the request in layers: skill, previous memory, then the active user query.
        messages = []
        if skillName:
            skillMessages = skills.buildSkillMessages(skillName)
            if skillMessages:
                self.writeSse("log", f"Injecting skill: {skillName}")
                messages.extend(skillMessages)
            else: self.writeSse("log", f"WARNING: Skill '{skillName}' not found.")

        if not noMemory:
            history, _ = mem.loadMemory()
            if history:
                chats = sum(1 for m in history if m["role"] == "user")
                self.writeSse("log", f"Loaded {chats} chat(s) from memory.")
                messages.extend(history)
            else: self.writeSse("log", "No prior memory. Starting fresh.")
        else: self.writeSse("log", "Memory disabled for this query.")
        messages.append({"role": "user", "content": query})

        ## Insert shared task rules at the front so attachment instructions cannot take over.
        systemMessage = {
            "role": "system",
            "content": SYSTEM_PROMPT + "\n" + ARTIFACT_PROMPT,
        }
        messages.insert(0, systemMessage)
        ## Shorten supported content in a request copy; saved history stays unchanged.
        if body.get("optimizeTokens"):
            before = len(json.dumps(messages))
            messages = optimizeMessages(messages)
            self.writeSse( "log",
                           f"Lossless optimization: {before - len(json.dumps(messages))} "
                           "characters saved; token savings vary by tokenizer.",)
        self.writeSse("log", f"Sending to proxy (model: {model}, messages: {len(messages)})")
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        ## Omitting max_tokens lets the provider use its default output limit.
        if maxTokens is not None: payload["max_tokens"] = int(maxTokens)
        reply = ""
        actualModel = "unknown"
        promptTokens = 0
        completionTokens = 0
        totalTokens = 0
        try:
            for data in streamCompletion(payload, lambda text: self.writeSse("log", text)):

                ## Keep the real deployment name instead of replacing it with a tier alias.
                if "model" in data and isinstance(data["model"], str):
                    reportedModel = data["model"]
                    if (reportedModel not in ("auto", "fast", "smart") and actualModel == "unknown"):
                        actualModel = reportedModel
                        self.writeSse("log", f"Model: {actualModel}")

                ## The final gateway event may carry the only token usage report.
                if "usage" in data and data["usage"]:
                    u = data["usage"]
                    promptTokens = u.get("prompt_tokens", promptTokens)
                    completionTokens = u.get("completion_tokens", completionTokens)
                    totalTokens = u.get("total_tokens", totalTokens)

                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        ## JSON encoding keeps newlines inside the text from breaking SSE frames.
                        reply += token
                        self.writeSse("token", json.dumps(token))

            ## File capture runs only after the gateway confirms a complete response.
            if reply: self.writeSse("artifacts", json.dumps(captureOutputs(reply, chatId)))

            ## Disabled memory skips saving the chat but still allows output files.
            if not noMemory and reply:
                mem.appendChat(query, reply, fileContexts if fileContexts else None)
                self.writeSse("log", "Chat saved to memory.")

            ## Use rough counts when the provider omits usage; these are not exact token totals.
            if totalTokens == 0 and reply:
                completionTokens = int(len(reply.split()) * 1.3)
                promptTokens = max(1, len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) // 4,)
                totalTokens = promptTokens + completionTokens
                
            contextLimit = getContextLimit(actualModel)
            ## The done event ends generation and updates the browser usage bar.
            self.writeSse(
                "done",
                json.dumps(
                    {
                        "model": actualModel,
                        "promptTokens": promptTokens,
                        "completionTokens": completionTokens,
                        "totalTokens": totalTokens,
                        "contextLimit": contextLimit,
                    }
                ),
            )

        ## Send failures as stream events so the browser can restore the request for retry.
        except Exception as e: self.writeSse("error", str(e))

    ## Send a local file as bytes with the requested content type.
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
