#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Local inference service
#
# Exposes authenticated OpenAI-style model and completion endpoints on loopback.
# Loads one selected model into a worker process and reuses it between requests.
# Releases the old worker before switching models or after the idle timeout.
# Sends SSE replies and keepalive events without loading weights in this process.
# ----------------------------------------------------------------------------

import atexit
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

## Import shared discovery and credentials relative to this script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from localModels import publicModels, resolveModel
from proxyClient import PROXY_HEADERS

## Own the single worker and serialize inference, switching, and idle cleanup.
class Manager:
    ## Keep timeouts and process state lightweight until the first model request.
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.spec = None
        self.context = None
        self.last = time.monotonic()
        self.idle = max(0, int(os.getenv('HAZAR_LOCAL_IDLE_SECONDS', '300')))
        self.timeout = max(30, int(os.getenv('HAZAR_LOCAL_TIMEOUT', '600')))

    ## Wait for worker exit before allowing another model allocation.
    def unload(self):
        # Process exit releases tensor memory, native allocators, and CUDA caches.
        if self.process:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
        self.process = self.spec = self.context = None

    ## Read one worker event while keeping the HTTP stream alive during slow work.
    def read(self, handler):
        started = time.monotonic()
        while True:
            try:
                line = self.events.get(timeout=10)
                if line is None: raise RuntimeError('Local worker exited; check core/local.log.')
                return json.loads(line)
            except queue.Empty:
                if time.monotonic() - started > self.timeout:
                    raise RuntimeError('Local inference timed out.')
                handler.wfile.write(b': loading or generating\n\n')
                handler.wfile.flush()

    ## Reuse a matching worker; otherwise release it before starting the replacement.
    def load(self, spec, handler):
        if self.spec == spec and self.process and self.process.poll() is None: return
        self.unload()
        self.events = queue.Queue(maxsize=128)
        self.process = subprocess.Popen(
            [sys.executable, '-u', str(Path(__file__).with_name('localWorker.py')), json.dumps(spec)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8',
            env=dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1'))
        ## Drain the pipe in a background thread so requests can emit keepalives.
        process, events = self.process, self.events
        def pump():
            try:
                for line in process.stdout:
                    while True:
                        try:
                            events.put(line, timeout=0.5)
                            break
                        except queue.Full:
                            if process.poll() is not None: return
                events.put(None, timeout=0.5)
            except (ValueError, OSError, queue.Full): pass
        threading.Thread(target=pump, daemon=True).start()
        ## Register the model only after its loader reports successful initialization.
        event = self.read(handler)
        if not event.get('ready'): raise RuntimeError(event.get('error', {}).get('message', 'Local worker failed to load.'))
        self.spec, self.context = spec, event['contextLimit']

    ## Idle cleanup skips busy workers and never interrupts active inference.
    def reap(self):
        while True:
            time.sleep(5)
            if self.idle and self.lock.acquire(blocking=False):
                try:
                    if time.monotonic() - self.last >= self.idle: self.unload()
                finally: self.lock.release()

## Reuse one manager across HTTP requests and clean up on normal interpreter exit.
manager = Manager()
atexit.register(manager.unload)

## Keep discovery responsive while a worker handles a serialized completion request.
class Handler(BaseHTTPRequestHandler):
    ## Keep HTTP access noise out of the model service log.
    def log_message(self, *args): pass

    ## Share the existing gateway credential instead of introducing another key file.
    def authorized(self):
        if self.headers.get('Authorization') == PROXY_HEADERS['Authorization']: return True
        self.send_error(401, 'Invalid local service credential')
        return False

    ## Return health and current model choices without loading any inference libraries.
    def do_GET(self):
        if not self.authorized(): return
        if self.path not in ('/health', '/v1/models'):
            self.send_error(404)
            return
        models = [dict(model, object='model', created=0, owned_by='local') for model in publicModels()]
        body = json.dumps({'object': 'list', 'data': models, 'loaded': manager.spec and manager.spec['id'],
                           'contextLimit': manager.context}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    ## Add OpenAI-style event metadata and encode token text safely inside SSE frames.
    def event(self, data):
        if not data.get('error'):
            data.setdefault('id', self.requestId)
            data.setdefault('created', int(time.time()))
            data.setdefault('object', 'chat.completion.chunk')
        self.wfile.write(('data: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode())
        self.wfile.flush()

    ## Validate text-only requests before acquiring the exclusive inference lock.
    def do_POST(self):
        if not self.authorized(): return
        if self.path != '/v1/chat/completions':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16000000: raise ValueError('Request size invalid')
            payload = json.loads(self.rfile.read(length))
            spec = resolveModel(payload.get('model', 'local'))
            if payload.get('stream') is not True: raise ValueError('This service requires stream=true')
            messages = payload['messages']
            if not isinstance(messages, list) or not messages: raise ValueError('messages must be a nonempty list')
            for message in messages:
                if message.get('role') not in ('system', 'user', 'assistant') or not isinstance(message.get('content'), str):
                    raise ValueError('Only text system/user/assistant messages are supported')
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.send_error(400, str(error))
            return
        # Reject overlap instead of queueing multiple model allocations.
        if not manager.lock.acquire(blocking=False):
            self.send_error(409, 'Local model busy; retry after the current request')
            return
        try:
            self.requestId = 'chatcmpl-' + uuid.uuid4().hex
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            ## Start or reuse the selected worker, then forward its JSON-line events.
            manager.load(spec, self)
            manager.process.stdin.write(json.dumps(payload) + '\n')
            manager.process.stdin.flush()
            while True:
                event = manager.read(self)
                if event.get('done'): break
                self.event(event)
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        ## A disconnected client or worker failure releases the current allocation.
        except (BrokenPipeError, ConnectionResetError): manager.unload()
        except Exception as error:
            manager.unload()
            try: self.event({'error': {'message': str(error)}})
            except OSError: pass
        finally:
            manager.last = time.monotonic()
            manager.lock.release()

if __name__ == '__main__':
    ## Start the loopback service and its idle watcher; shutdown releases the worker.
    ## Bash shutdown sends SIGTERM to the service, which also stops its child worker.
    def stop(*args):
        manager.unload()
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    threading.Thread(target=manager.reap, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', 8000), Handler)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        manager.unload()
