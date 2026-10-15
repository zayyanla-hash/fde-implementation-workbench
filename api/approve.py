from http.server import BaseHTTPRequestHandler

from api._shared import read_json, resolve_demo, send_json


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = read_json(self)
        invoice_id = str(body.get("invoice_id") or "")
        approver = str(body.get("approver") or "").strip()
        reason = str(body.get("reason") or "").strip()
        approve = bool(body.get("approve", False))
        if not invoice_id or not approver:
            send_json(self, 400, {"error": "invoice_id and approver are required"})
            return
        try:
            result = resolve_demo(invoice_id, approve, approver, reason)
        except (KeyError, ValueError) as exc:
            send_json(self, 409, {"error": str(exc)})
            return
        send_json(self, 200, result.to_dict())
