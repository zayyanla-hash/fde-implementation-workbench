"""Vercel entry point; the browser owns its demo snapshot, Python validates it."""
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workbench.hosted import handle


class handler(BaseHTTPRequestHandler):
    do_GET = handle
    do_POST = handle
    do_PATCH = handle
    do_DELETE = handle
    do_OPTIONS = handle
