#!/usr/bin/env python3
"""
Holmes UI Application Server
Lightweight, non-root, zero-dependency web server for Holmes Web GUI.
Serves static assets and forwards /api requests to the Holmes backend service.
"""

import os
import sys
import mimetypes
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HOLMES_BACKEND_URL = os.environ.get("HOLMES_BACKEND_URL", os.environ.get("HOLMES_URL", "http://holmes:5050")).rstrip("/")
PORT = int(os.environ.get("PORT", "8080"))
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.dirname(os.path.abspath(__file__)))

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}

class HolmesUIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        sys.stdout.write(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def do_GET(self):
        # Health check
        if self.path in ("/healthz", "/readyz", "/health"):
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = b'{"status":"healthy","service":"holmes-ui"}\n'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Forward API requests to Holmes backend
        if self.path.startswith("/api/"):
            self.proxy_request()
            return

        # Serve static files
        self.serve_static()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self.proxy_request()
            return
        self.send_error(404, "Not Found")

    def do_PUT(self):
        if self.path.startswith("/api/"):
            self.proxy_request()
            return
        self.send_error(404, "Not Found")

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            self.proxy_request()
            return
        self.send_error(404, "Not Found")

    def serve_static(self):
        req_path = self.path.split("?")[0].split("#")[0]
        if req_path in ("/", ""):
            rel_file = "index.html"
        else:
            rel_file = req_path.lstrip("/")

        abs_path = os.path.abspath(os.path.join(STATIC_DIR, rel_file))
        if not abs_path.startswith(os.path.abspath(STATIC_DIR)) or not os.path.isfile(abs_path):
            abs_path = os.path.join(STATIC_DIR, "index.html")

        ext = os.path.splitext(abs_path)[1].lower()
        content_type = MIME_TYPES.get(ext, mimetypes.guess_type(abs_path)[0] or "application/octet-stream")

        try:
            with open(abs_path, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, proxy-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def proxy_request(self):
        target_url = f"{HOLMES_BACKEND_URL}{self.path}"
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        req_headers = {}
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length", "transfer-encoding", "connection"):
                req_headers[k] = v

        req = urllib.request.Request(
            url=target_url,
            data=body,
            headers=req_headers,
            method=self.command
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                status_code = resp.status
                resp_headers = resp.headers
                resp_body = resp.read()

                self.send_response(status_code)
                self.send_cors_headers()

                for k, v in resp_headers.items():
                    if k.lower() not in ("transfer-encoding", "connection", "content-length", "access-control-allow-origin"):
                        self.send_header(k, v)

                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_cors_headers()
            for k, v in e.headers.items():
                if k.lower() not in ("transfer-encoding", "connection", "content-length", "access-control-allow-origin"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            err_msg = f'{{"detail": "Failed to connect to Holmes backend at {HOLMES_BACKEND_URL}: {e}"}}'.encode("utf-8")
            self.send_response(502)
            self.send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_msg)))
            self.end_headers()
            self.wfile.write(err_msg)

def run():
    print(f"🚀 Starting Holmes UI server on port {PORT}", flush=True)
    print(f"🔗 Holmes backend configured at: {HOLMES_BACKEND_URL}", flush=True)
    print(f"📁 Serving static assets from: {STATIC_DIR}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HolmesUIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("🛑 Server stopped.", flush=True)

if __name__ == "__main__":
    run()
