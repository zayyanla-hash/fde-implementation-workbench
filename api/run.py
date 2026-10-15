from http.server import BaseHTTPRequestHandler

from api._shared import read_json, run_demo, send_json


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = read_json(self)
        scenario = str(body.get("scenario") or "vendor_payments_v1")
        try:
            result, _ = run_demo(scenario)
        except KeyError as exc:
            send_json(self, 400, {"error": str(exc)})
            return
        send_json(self, 201, result.to_dict())
