"""Authenticated loopback transport between the Tk host and MCP/CLI clients.

This is an internal transport. The public MCP transport is stdio in aura_mcp.
Only the Tk thread executes commands; HTTP threads enqueue work and read jobs.
"""
import hmac
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_MESSAGE = 4 * 1024 * 1024


def endpoint_path():
    override = os.environ.get('AURA_MCP_ENDPOINT_FILE')
    if override:
        return Path(override).resolve()
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AURA-Photo' / 'mcp' / 'endpoint.json'


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


class HostBridge:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.instance = secrets.token_hex(12)
        self.queue = queue.Queue(maxsize=128)
        self.lock = threading.Lock()
        self.jobs = {}
        self.closed = False
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, data):
                body = encode(data)
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                # A browser origin has no reason to use the private host bridge.
                if self.headers.get('Origin'):
                    self.reply(403, {'error': 'Browser origins are not accepted.'}); return
                if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + bridge.token):
                    self.reply(401, {'error': 'Authentication required.'}); return
                if self.path != '/rpc':
                    self.reply(404, {'error': 'Unknown endpoint.'}); return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= MAX_MESSAGE:
                        raise ValueError('Invalid message size.')
                    request = json.loads(self.rfile.read(length))
                    if not isinstance(request, dict):
                        raise ValueError('Expected an object.')
                    method = request.get('method')
                    if method == 'job':
                        ident = request.get('id')
                        with bridge.lock:
                            result = dict(bridge.jobs[ident]) if ident in bridge.jobs else None
                        if result is None:
                            self.reply(404, {'error': 'Unknown or expired job.'}); return
                    elif method == 'cancel':
                        with bridge.lock:
                            job = bridge.jobs.get(request.get('id'))
                            if job is None: raise ValueError('Unknown job.')
                            job['cancel_requested'] = True
                        result = {'accepted': True}
                    elif method == 'submit':
                        operation = request.get('operation')
                        arguments = request.get('arguments', {})
                        if not isinstance(operation, str) or not isinstance(arguments, dict):
                            raise ValueError('Invalid command.')
                        ident = secrets.token_hex(12)
                        with bridge.lock:
                            # Keep active jobs, prune only completed older jobs.
                            old = [k for k, v in bridge.jobs.items() if v['state'] in ('done', 'failed', 'cancelled')]
                            for k in old[:-192]: bridge.jobs.pop(k, None)
                            bridge.jobs[ident] = dict(id=ident, operation=operation, state='queued', created=time.time(), cancel_requested=False)
                        try: bridge.queue.put_nowait((ident, operation, arguments))
                        except queue.Full:
                            with bridge.lock: bridge.jobs.pop(ident, None)
                            raise ValueError('Command queue is full.')
                        result = {'job_id': ident, 'instance': bridge.instance}
                    else:
                        raise ValueError('Unknown bridge method.')
                    self.reply(200, result)
                except (ValueError, TypeError, KeyError) as error:
                    self.reply(400, {'error': str(error)})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.timeout = 1
        self.path = endpoint_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = dict(schema=1, pid=os.getpid(), instance=self.instance,
                          url=f'http://127.0.0.1:{self.server.server_port}/rpc', token=self.token)
        temp = self.path.with_name(self.path.name + '.' + self.instance + '.tmp')
        temp.write_bytes(encode(descriptor)); os.chmod(temp, 0o600); os.replace(temp, self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='AURA-local-bridge')
        self.thread.start()

    def update(self, ident, **values):
        with self.lock:
            if ident in self.jobs: self.jobs[ident].update(values)

    def close(self):
        if self.closed: return
        self.closed = True
        # shutdown must not stall the Tk event loop.
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        try:
            if json.loads(self.path.read_text(encoding='utf-8')).get('instance') == self.instance:
                self.path.unlink()
        except (OSError, ValueError): pass


class BridgeClient:
    def __init__(self, path=None):
        self.path = Path(path) if path else endpoint_path()

    def request(self, method, **values):
        try: descriptor = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise RuntimeError('AURA 尚未开启本地控制接口。请启动更新后的 AURA。') from error
        url = descriptor.get('url', '')
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path != '/rpc':
            raise RuntimeError('Invalid local AURA endpoint.')
        request = urllib.request.Request(url, data=encode(dict(method=method, **values)),
                  headers={'Authorization': 'Bearer ' + descriptor['token'], 'Content-Type': 'application/json'})
        # Do not send the private token through a system proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=15) as response:
                return json.loads(response.read(MAX_MESSAGE * 4))
        except OSError as error:
            raise RuntimeError('AURA 本地连接失败；请确认更新后的 AURA 正在运行。') from error

    def call(self, operation, arguments=None, wait=True, timeout=60):
        result = self.request('submit', operation=operation, arguments=arguments or {})
        if not wait: return result
        return self.wait(result['job_id'], timeout)

    def wait(self, ident, timeout=60):
        deadline = time.monotonic() + min(300, max(0, float(timeout)))
        while True:
            job = self.request('job', id=ident)
            if job['state'] in ('done', 'failed', 'cancelled'): return job
            if time.monotonic() >= deadline: return job
            time.sleep(.1)
