#!/usr/bin/env python3
"""Local dev server with no-cache headers. Run from project root: python serve.py"""

import http.server
import os

PORT = 8081
DIRECTORY = os.path.join(os.path.dirname(__file__), "site")


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, format, *args):
        # Suppress noisy request logs; only show errors
        if args[1] not in ("200", "304"):
            super().log_message(format, *args)


if __name__ == "__main__":
    with http.server.HTTPServer(("", PORT), NoCacheHandler) as httpd:
        print(f"Serving http://localhost:{PORT}/  (Ctrl+C to stop)")
        httpd.serve_forever()
