"""Only public UI assets; all data continues through scoped authenticated API routes."""
from pathlib import Path

ASSETS = {'/panel/': ('index.html', 'text/html; charset=utf-8'),
          '/panel/panel.css': ('panel.css', 'text/css; charset=utf-8'),
          '/panel/panel.js': ('panel.js', 'text/javascript; charset=utf-8'),
          '/panel/fg-machines.svg': ('fg-machines.svg', 'image/svg+xml')}


def asset(path, method, start):
    if method not in {'GET', 'HEAD'} or path not in ASSETS:
        return None
    name, mime = ASSETS[path]
    data = (Path(__file__).with_name('web') / name).read_bytes()
    start('200 OK', [('Content-Type', mime), ('Content-Length', str(len(data))),
        ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
        ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'),
        ('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
        ('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')])
    return [data if method == 'GET' else b'']
