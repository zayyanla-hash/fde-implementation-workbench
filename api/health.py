from http.server import BaseHTTPRequestHandler

from _shared import send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        send_json(
            self,
            200,
            {
                "ok": True,
                "service": "fde-implementation-workbench",
                "mode": "deterministic-demo",
                "persistence": "browser-session-only",
            },
        )
