from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from server.app.app import create_app


DATA_DIR = Path(os.environ.get("AI_LOG_DATA_DIR", "/data"))
HOST = os.environ.get("AI_LOG_HOST", "0.0.0.0")
PORT = int(os.environ.get("AI_LOG_PORT", "8888"))
ENROLL_TOKEN = os.environ.get("ENROLL_TOKEN", "change-this-install-token")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ENFORCE_AGENT_TOKEN = os.environ.get("ENFORCE_AGENT_TOKEN", "false").lower() in {"1", "true", "yes", "on"}
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "0") or "0")
DASHBOARD_ROUTES = {
    "/": "overview",
    "/logs": "logs",
    "/incidents": "incidents",
    "/agents": "agents",
    "/import": "import",
    "/admin": "admin",
}


def main() -> None:
    app = create_app(
        DATA_DIR,
        enroll_token=ENROLL_TOKEN,
        admin_token=ADMIN_TOKEN,
        admin_user=ADMIN_USER,
        admin_password=ADMIN_PASSWORD,
        enforce_agent_token=ENFORCE_AGENT_TOKEN,
    )
    if RETENTION_DAYS > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        app.store.purge_older_than(cutoff)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/login":
                self._send(200, {"Content-Type": "text/html; charset=utf-8"}, app.login_html())
                return
            if parsed.path in DASHBOARD_ROUTES:
                query = parse_qs(parsed.query)
                selected_website_id = (query.get("website_id") or [""])[0]
                log_page = (query.get("log_page") or ["1"])[0]
                if not app.is_admin_authorized(dict(self.headers), query):
                    self._send(
                        200,
                        {"Content-Type": "text/html; charset=utf-8"},
                        app.login_html(next_path=self.path),
                    )
                    return
                self._send(
                    200,
                    {"Content-Type": "text/html; charset=utf-8"},
                    app.dashboard_html(
                        selected_website_id=selected_website_id,
                        log_page=log_page,
                        page=DASHBOARD_ROUTES[parsed.path],
                    ),
                )
                return
            status, headers, body = app.handle_json("GET", self.path, dict(self.headers), b"")
            self._send(status, headers, body)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if self.path == "/login":
                status, headers, response = app.login_response(body)
                self._send(status, headers, response)
                return
            status, headers, response = app.handle_json("POST", self.path, dict(self.headers), body)
            self._send(status, headers, response)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"AI Log Monitor listening on http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
