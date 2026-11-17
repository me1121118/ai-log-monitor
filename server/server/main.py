from __future__ import annotations

import os
import signal
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from server.app.app import create_app


CONFIG_PATH = Path(os.environ.get("AI_LOG_CONFIG", Path(__file__).resolve().parent / "config.yaml"))


def _clean_config_scalar(value: str) -> str:
    cleaned = value.split("#", 1)[0].strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def load_server_config(config_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not config_path.exists():
        return values

    in_server_section = False
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith((" ", "\t")) and stripped.endswith(":"):
            in_server_section = stripped[:-1] == "server"
            continue
        if not in_server_section or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        if key in {"public_url", "bind", "port"}:
            values[key] = _clean_config_scalar(value)
    return values


SERVER_CONFIG = load_server_config(CONFIG_PATH)
DATA_DIR = Path(os.environ.get("AI_LOG_DATA_DIR", "/data"))
HOST = os.environ.get("AI_LOG_HOST", SERVER_CONFIG.get("bind", "0.0.0.0"))
PORT = int(os.environ.get("AI_LOG_PORT", SERVER_CONFIG.get("port", "8888")))
PUBLIC_URL = os.environ.get("AI_LOG_PUBLIC_URL", SERVER_CONFIG.get("public_url", f"http://{HOST}:{PORT}")).rstrip("/")
ENROLL_TOKEN = os.environ.get("ENROLL_TOKEN", "change-this-install-token")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ENFORCE_AGENT_TOKEN = os.environ.get("ENFORCE_AGENT_TOKEN", "false").lower() in {"1", "true", "yes", "on"}
GATEWAY_INTERNAL_TOKEN = os.environ.get("GATEWAY_INTERNAL_TOKEN", "")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "0") or "0")
DASHBOARD_ROUTES = {
    "/": "overview",
    "/website": "website",
    "/logs": "logs",
    "/incidents": "incidents",
    "/agents": "agents",
    "/import": "import",
    "/admin": "admin",
    "/settings": "settings",
}
STATIC_PREFIX = "/static/"


def install_shutdown_handlers(stop_event: threading.Event) -> None:
    def request_shutdown(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)


def serve_until_stopped(httpd: ThreadingHTTPServer, stop_event: threading.Event) -> None:
    httpd.timeout = 0.5
    try:
        while not stop_event.is_set():
            httpd.handle_request()
    finally:
        httpd.server_close()


def resolve_static_file_path(static_dir: Path, request_path: str) -> Path | None:
    if not request_path.startswith(STATIC_PREFIX):
        return None
    relative_path = request_path.removeprefix(STATIC_PREFIX)
    if not relative_path:
        return None
    static_root = static_dir.resolve()
    file_path = (static_root / relative_path).resolve()
    if file_path.is_file() and file_path.is_relative_to(static_root):
        return file_path
    return None


def main() -> None:
    app = create_app(
        DATA_DIR,
        enroll_token=ENROLL_TOKEN,
        admin_token=ADMIN_TOKEN,
        admin_user=ADMIN_USER,
        admin_password=ADMIN_PASSWORD,
        enforce_agent_token=ENFORCE_AGENT_TOKEN,
        public_url=PUBLIC_URL,
        gateway_internal_token=GATEWAY_INTERNAL_TOKEN,
    )
    if RETENTION_DAYS > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        app.store.purge_older_than(cutoff)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/favicon.ico":
                self._send(204, {"Content-Type": "image/x-icon"}, b"")
                return
            if parsed.path.startswith("/static/"):
                static_dir = Path(__file__).resolve().parent / "app" / "static"
                file_path = resolve_static_file_path(static_dir, parsed.path)
                if file_path:
                    content_type = "text/css" if file_path.suffix == ".css" else "application/javascript"
                    self._send(200, {"Content-Type": content_type + "; charset=utf-8"}, file_path.read_bytes())
                    return
                else:
                    self._send(404, {"Content-Type": "text/plain"}, b"Not Found")
                    return
            if parsed.path == "/login":
                self._send(200, {"Content-Type": "text/html; charset=utf-8"}, app.login_html())
                return
            if parsed.path in DASHBOARD_ROUTES:
                query = parse_qs(parsed.query)
                selected_website_id = (query.get("website_id") or [""])[0]
                selected_agent_id = (query.get("agent_id") or [""])[0]
                selected_source_id = (query.get("source_id") or [""])[0]
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
                        selected_agent_id=selected_agent_id,
                        selected_source_id=selected_source_id,
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

        def do_DELETE(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b""
            status, headers, response = app.handle_json("DELETE", self.path, dict(self.headers), body)
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
    httpd.daemon_threads = True
    stop_event = threading.Event()
    install_shutdown_handlers(stop_event)
    print(f"AI Log Monitor listening on http://{HOST}:{PORT}", flush=True)
    serve_until_stopped(httpd, stop_event)


if __name__ == "__main__":
    main()
