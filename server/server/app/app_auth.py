from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
from urllib.parse import parse_qs, quote

from .utils import _bearer_token, _cookie_value, _h

class AuthMixin:
    def is_admin_authorized(
        self,
        headers: dict[str, str],
        query: dict[str, list[str]] | None = None,
    ) -> bool:
        if not self._admin_enabled():
            return True
        normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
        candidates = [
            normalized_headers.get("x-admin-token", ""),
            (query or {}).get("admin_token", [""])[0],
            _bearer_token(normalized_headers.get("authorization", "")),
            _cookie_value(normalized_headers.get("cookie", ""), "admin_token"),
        ]
        if self.admin_token and any(
            secrets.compare_digest(self.admin_token, str(candidate)) for candidate in candidates if candidate
        ):
            return True
        session = _cookie_value(normalized_headers.get("cookie", ""), "admin_session")
        return self._is_valid_session(session)

    def login_html(self, next_path: str = "/", error: str = "") -> bytes:
        error_html = f'<div class="error">{_h(error)}</div>' if error else ""
        template_path = Path(__file__).resolve().parent / "templates" / "login.html"
        html = template_path.read_text(encoding="utf-8")
        html = html.replace("{{error_html}}", error_html)
        html = html.replace("{{next_path}}", _h(next_path))
        return html.encode("utf-8")

    def login_response(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        fields = parse_qs(body.decode("utf-8"))
        token = fields.get("admin_token", [""])[0]
        user = fields.get("admin_user", [""])[0]
        password = fields.get("admin_password", [""])[0]
        next_path = fields.get("next", ["/"])[0] or "/"
        if self._is_valid_password_login(user, password):
            session = self._sign_session(user)
            return (
                302,
                {
                    "Location": next_path,
                    "Set-Cookie": f"admin_session={quote(session)}; HttpOnly; SameSite=Lax; Path=/",
                    "Content-Type": "text/plain",
                },
                b"ok",
            )
        if self.admin_token and secrets.compare_digest(self.admin_token, token):
            session_user = self.admin_user or "admin"
            return (
                302,
                {
                    "Location": next_path,
                    "Set-Cookie": f"admin_session={quote(self._sign_session(session_user))}; HttpOnly; SameSite=Lax; Path=/",
                    "Content-Type": "text/plain",
                },
                b"ok",
            )
        return (
            401,
            {"Content-Type": "text/html; charset=utf-8"},
            self.login_html(next_path=next_path, error="Invalid username or password"),
        )

    def _requires_admin(self, method: str, route: str) -> bool:
        if not self._admin_enabled():
            return False
        public_routes = {
            ("GET", "/health"),
            ("POST", "/api/agents/register"),
            ("POST", "/api/agents/heartbeat"),
            ("POST", "/api/ingest"),
            ("POST", "/api/ingest/batch"),
            ("POST", "/api/log-sources"),
            ("POST", "/api/topology-hints"),
            ("POST", "/internal/evidence"),
            ("POST", "/internal/agents/validate"),
        }
        return (method, route) not in public_routes

    def _admin_enabled(self) -> bool:
        return bool(self.admin_token or (self.admin_user and self.admin_password))

    def _session_secret(self) -> str:
        return self.admin_token or self.admin_password

    def _is_valid_password_login(self, user: str, password: str) -> bool:
        if not self.admin_user or not self.admin_password:
            return False
        return secrets.compare_digest(self.admin_user, user) and secrets.compare_digest(self.admin_password, password)

    def _sign_session(self, user: str) -> str:
        signature = hmac.new(
            self._session_secret().encode("utf-8"),
            user.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{user}:{signature}"

    def _is_valid_session(self, session: str) -> bool:
        if not session or ":" not in session or not self._session_secret():
            return False
        user, signature = session.split(":", 1)
        if self.admin_user and not secrets.compare_digest(self.admin_user, user):
            return False
        expected = self._sign_session(user).split(":", 1)[1]
        return secrets.compare_digest(expected, signature)
