"""Read-only, bounded server-side connectivity checks against fixed public targets."""
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from threading import Lock


class Diagnostics:
    cache_seconds = 15

    def __init__(self):
        self.lock = Lock()
        self.cached = None
        self.finished = 0

    def run(self, service):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('DIAGNOSTICS_BUSY')
        try:
            if self.cached is not None and time.monotonic() - self.finished < self.cache_seconds:
                return {**self.cached, 'cached': True}
            checks = []
            for key, target, probe in [
                ('database', 'PostgreSQL', lambda: self.database(service)),
                ('dns', 'example.com', self.dns),
                ('tcp', '1.1.1.1:443', self.tcp),
                ('tls', 'cloudflare-dns.com via 1.1.1.1:443', self.tls),
            ]:
                started = time.monotonic()
                try:
                    probe()
                    state = 'passed'
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    state = 'failed'
                except Exception:
                    state = 'failed'  # Never expose internal DB/network exception text.
                checks.append(dict(key=key, target=target, state=state,
                                   elapsed_ms=round((time.monotonic()-started)*1000)))
            self.cached = dict(source='server', checked_at=datetime.now(timezone.utc).isoformat(),
                               checks=checks, cached=False)
            self.finished = time.monotonic()
            return self.cached
        finally:
            self.lock.release()

    @staticmethod
    def database(service):
        with service.connect() as db:
            db.execute("SET LOCAL statement_timeout = '2000ms'")
            db.execute('SELECT 1').fetchone()

    @staticmethod
    def dns():
        # A killed child bounds libc resolver hangs without leaking resolver threads.
        subprocess.run([sys.executable, '-c',
                        "import socket; assert socket.getaddrinfo('example.com',443,type=socket.SOCK_STREAM)"],
                       timeout=2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @staticmethod
    def tcp():
        with socket.create_connection(('1.1.1.1', 443), timeout=2):
            pass

    @staticmethod
    def tls():
        context = ssl.create_default_context()
        with socket.create_connection(('1.1.1.1', 443), timeout=2) as connection:
            with context.wrap_socket(connection, server_hostname='cloudflare-dns.com'):
                pass
