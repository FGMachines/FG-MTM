"""Bounded loopback HTTP runner; an idle connection cannot block other clients."""
from socketserver import ThreadingMixIn
from threading import BoundedSemaphore
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler


class BoundedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    max_connections = 16

    def __init__(self, *args, **kwargs):
        self.slots = BoundedSemaphore(self.max_connections)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(WSGIRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # Never log URLs, credentials or request bodies.
