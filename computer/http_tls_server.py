"""Bound the complete connection lifetime and independent authenticated RPC lanes."""
from contextlib import contextmanager
from functools import wraps
import hmac
import ssl
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit


def bounded_request(method):
    @wraps(method)
    def dispatch(handler, *args, **kwargs):
        server = handler.server
        if not hasattr(server, 'request_lane'):
            return method(handler, *args, **kwargs)
        path = urlsplit(handler.path).path
        authorization = handler.headers.get('Authorization', '')
        trusted = path.startswith('/v1/') and any(
            token and hmac.compare_digest(authorization.encode(), ('Bearer ' + token).encode())
            for token in getattr(handler, '_rpc_tokens', ()))
        lane = 'rpc' if trusted else 'events' if path in ('/home/events', '/home/alerts') else 'desktop' if path == '/home/api/desktop/ws' else 'web'
        with server.request_lane(lane) as admitted:
            if admitted:
                return method(handler, *args, **kwargs)
            handler.close_connection = True
            body = b'{"ok":false,"error":"server_busy"}'
            handler.send_response(503)
            handler.send_header('Content-Type', 'application/json')
            handler.send_header('Content-Length', str(len(body)))
            handler.send_header('Connection', 'close')
            handler.send_header('Retry-After', '1')
            handler.end_headers()
            handler.wfile.write(body)
    return dispatch


class ThreadedTLSServer(ThreadingHTTPServer):
    request_queue_size = 32
    handshake_timeout = 4
    connection_limit = 64
    lane_limits = {'rpc': 16, 'web': 20, 'events': 20, 'desktop': 8}

    def __init__(self, *args, **kwargs):
        self.tls_context = None
        self._handshakes = threading.BoundedSemaphore(8)
        self._connections = threading.BoundedSemaphore(self.connection_limit)
        self._lanes = {name: threading.BoundedSemaphore(count) for name, count in self.lane_limits.items()}
        super().__init__(*args, **kwargs)

    @contextmanager
    def request_lane(self, name):
        gate = self._lanes[name]
        admitted = gate.acquire(blocking=False)
        try:
            yield admitted
        finally:
            if admitted:
                gate.release()

    def process_request(self, request, client_address):
        if not self._connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        if self.tls_context and not self._handshakes.acquire(blocking=False):
            self._connections.release()
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connections.release()
            if self.tls_context:
                self._handshakes.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            if self.tls_context:
                try:
                    request.settimeout(self.handshake_timeout)
                    request = self.tls_context.wrap_socket(request, server_side=True)
                    request.settimeout(15)
                except (OSError, ssl.SSLError):
                    self.shutdown_request(request)
                    return
                finally:
                    self._handshakes.release()
            else:
                request.settimeout(15)
            super().process_request_thread(request, client_address)
        finally:
            self._connections.release()
