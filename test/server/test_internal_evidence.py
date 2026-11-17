import json
import tempfile
import unittest
from pathlib import Path

from server.app.app import create_app

GATEWAY_TOKEN = "gateway-secret-token"


def evidence_payload(**overrides):
    payload = {
        "website_id": "website_1",
        "agent_id": "db1",
        "agent_role": "db",
        "source_id": "src_mariadb_error",
        "file_path": "/host/var/log/mysql/error.log",
        "timestamp": "2026-07-31T10:00:00+00:00",
        "message": "Too many connections",
        "severity": "problem",
        "category": "db_too_many_connections",
        "fingerprint": "fp_db_too_many_connections",
        "signal_type": "database",
        "classification": {"rule_id": "db.connection_limit.v1", "confidence": 0.98},
    }
    payload.update(overrides)
    return payload


class InternalEvidenceTests(unittest.TestCase):
    def _post(self, app, headers=None, payload=None):
        return app.handle_json(
            "POST",
            "/internal/evidence",
            headers or {},
            json.dumps(payload if payload is not None else evidence_payload()).encode("utf-8"),
        )

    def test_missing_token_returns_401(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            status, _headers, body = self._post(app)
            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 401)
            self.assertEqual(response["error"], "invalid gateway token")

    def test_empty_configured_token_rejects_even_with_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            status, _headers, _body = self._post(app, {"X-Gateway-Token": GATEWAY_TOKEN})
            self.assertEqual(status, 401)

    def test_wrong_token_returns_401(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            status, _headers, _body = self._post(app, {"X-Gateway-Token": "wrong-token"})
            self.assertEqual(status, 401)

    def test_token_fallbacks_are_never_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            query_status, _query_headers, _query_body = app.handle_json(
                "GET", "/internal/evidence?x_gateway_token=gateway-secret-token", {}, b""
            )
            cookie_status, _cookie_headers, _cookie_body = app.handle_json(
                "POST",
                "/internal/evidence",
                {"Cookie": f"x_gateway_token={GATEWAY_TOKEN}"},
                json.dumps(evidence_payload()).encode("utf-8"),
            )
            bearer_status, _bearer_headers, _bearer_body = app.handle_json(
                "POST",
                "/internal/evidence",
                {"Authorization": f"Bearer {GATEWAY_TOKEN}"},
                json.dumps(evidence_payload()).encode("utf-8"),
            )
            admin_query_status, _admin_headers, _admin_body = app.handle_json(
                "POST",
                "/internal/evidence?admin_token=gateway-secret-token",
                {},
                json.dumps(evidence_payload()).encode("utf-8"),
            )
            self.assertEqual(query_status, 404)
            self.assertEqual(cookie_status, 401)
            self.assertEqual(bearer_status, 401)
            self.assertEqual(admin_query_status, 401)

    def test_correct_token_persists_event_and_incident(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            status, headers, body = self._post(app, {"X-Gateway-Token": GATEWAY_TOKEN})
            response = json.loads(body.decode("utf-8"))
            stored = app.store.recent_events()[0]
            self.assertEqual(status, 201)
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(response["event_id"], stored["event_id"])
            self.assertIsNotNone(response["incident_id"])
            self.assertEqual(stored["severity"], "problem")
            self.assertEqual(app.store.list_incidents()[-1]["status"], "open")

    def test_internal_evidence_is_not_admin_authentication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(
                Path(temp_dir),
                admin_token="admin-token",
                admin_user="admin",
                admin_password="password",
                gateway_internal_token=GATEWAY_TOKEN,
            )
            gateway_status, _headers, _body = self._post(app, {"X-Gateway-Token": GATEWAY_TOKEN})
            self.assertEqual(gateway_status, 201)

            admin_status, _admin_headers, _admin_body = self._post(
                app, {"X-Admin-Token": "admin-token"}
            )
            self.assertEqual(admin_status, 401)

    def test_normal_severity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            status, _headers, body = self._post(
                app,
                {"X-Gateway-Token": GATEWAY_TOKEN},
                evidence_payload(severity="normal", message="GET /health HTTP/1.1 200"),
            )
            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("invalid severity", response["error"])

    def test_unknown_severity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            status, _headers, body = self._post(
                app,
                {"X-Gateway-Token": GATEWAY_TOKEN},
                evidence_payload(severity="catastrophic"),
            )
            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("invalid severity", response["error"])

    def test_supplied_classification_is_not_reclassified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            payload = evidence_payload(
                severity="problem",
                message="GET /health HTTP/1.1 200",
                status_code=200,
                category="db_too_many_connections",
            )
            status, _headers, _body = self._post(app, {"X-Gateway-Token": GATEWAY_TOKEN}, payload)
            stored = app.store.recent_events()[0]
            self.assertEqual(status, 201)
            self.assertEqual(stored["severity"], "problem")
            self.assertEqual(stored["category"], "db_too_many_connections")
            self.assertNotIn("source_profile", stored["metadata"])
            self.assertNotIn("parsed_fields", stored["metadata"])

    def test_supplied_fields_preserved_in_storage_and_raw_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            app = create_app(data_dir, gateway_internal_token=GATEWAY_TOKEN)
            status, _headers, _body = self._post(app, {"X-Gateway-Token": GATEWAY_TOKEN})
            stored = app.store.recent_events()[0]
            self.assertEqual(status, 201)
            self.assertEqual(stored["category"], "db_too_many_connections")
            self.assertEqual(stored["fingerprint"], "fp_db_too_many_connections")
            self.assertEqual(stored["metadata"]["signal_type"], "database")
            self.assertEqual(
                stored["metadata"]["classification"],
                {"rule_id": "db.connection_limit.v1", "confidence": 0.98},
            )
            files = list((data_dir / "raw_logs" / "website_1" / "db1").glob("*/*.jsonl"))
            row = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["category"], "db_too_many_connections")
            self.assertEqual(row["fingerprint"], "fp_db_too_many_connections")
            self.assertEqual(row["metadata"]["signal_type"], "database")
            self.assertEqual(row["metadata"]["classification"]["rule_id"], "db.connection_limit.v1")

    def test_gateway_context_before_is_kept_in_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            context = [{"message": "ready for connections", "severity": "normal"}]
            status, _headers, _body = self._post(
                app,
                {"X-Gateway-Token": GATEWAY_TOKEN},
                evidence_payload(context_before=context),
            )
            stored = app.store.recent_events()[0]
            self.assertEqual(status, 201)
            self.assertEqual(stored["metadata"]["context_before"], context)

    def test_dedupe_stores_once_and_archives_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            app = create_app(data_dir, gateway_internal_token=GATEWAY_TOKEN)
            first_status, _headers, first_body = self._post(app, {"X-Gateway-Token": GATEWAY_TOKEN})
            second_status, _headers, second_body = self._post(app, {"X-Gateway-Token": GATEWAY_TOKEN})
            first = json.loads(first_body.decode("utf-8"))
            second = json.loads(second_body.decode("utf-8"))
            files = list((data_dir / "raw_logs" / "website_1" / "db1").glob("*/*.jsonl"))
            self.assertEqual(first_status, 201)
            self.assertEqual(second_status, 201)
            self.assertEqual(first["event_id"], second["event_id"])
            self.assertEqual(app.store.count_events("website_1"), 1)
            self.assertEqual(len(files), 1)
            self.assertEqual(len(files[0].read_text(encoding="utf-8").splitlines()), 1)

    def test_response_is_compatible_with_ingest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            status, _headers, body = self._post(app, {"X-Gateway-Token": GATEWAY_TOKEN})
            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 201)
            self.assertEqual(
                set(response),
                {"event_id", "incident_id", "severity", "category", "fingerprint", "buffered"},
            )
            self.assertFalse(response["buffered"])
            self.assertEqual(response["severity"], "problem")

    def test_missing_required_event_fields_return_400(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), gateway_internal_token=GATEWAY_TOKEN)
            status, _headers, body = self._post(
                app,
                {"X-Gateway-Token": GATEWAY_TOKEN},
                evidence_payload(message=""),
            )
            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("missing required event field", response["error"])

    def test_internal_agent_validation_requires_gateway_token_and_checks_agent_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(
                Path(temp_dir),
                enroll_token="enroll",
                enforce_agent_token=True,
                gateway_internal_token=GATEWAY_TOKEN,
            )
            registration = app.store.register_agent(
                {
                    "agent_id": "db1",
                    "website_id": "website_1",
                    "agent_role": "db",
                    "registered_at": "2026-07-31T10:00:00+00:00",
                }
            )
            agent_token = registration["agent_token"]
            body = json.dumps({"agent_id": "db1"}).encode("utf-8")

            missing_status, _headers, _response = app.handle_json(
                "POST", "/internal/agents/validate", {"X-Agent-Token": agent_token}, body
            )
            wrong_status, _headers, wrong_body = app.handle_json(
                "POST",
                "/internal/agents/validate",
                {"X-Gateway-Token": GATEWAY_TOKEN, "X-Agent-Token": "wrong"},
                body,
            )
            valid_status, _headers, valid_body = app.handle_json(
                "POST",
                "/internal/agents/validate",
                {"X-Gateway-Token": GATEWAY_TOKEN, "X-Agent-Token": agent_token},
                body,
            )

            self.assertEqual(missing_status, 401)
            self.assertEqual(wrong_status, 200)
            self.assertFalse(json.loads(wrong_body)["valid"])
            self.assertEqual(valid_status, 200)
            self.assertTrue(json.loads(valid_body)["valid"])

    def test_internal_agent_validation_preserves_disabled_enforcement(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(
                Path(temp_dir),
                enforce_agent_token=False,
                gateway_internal_token=GATEWAY_TOKEN,
            )
            status, _headers, body = app.handle_json(
                "POST",
                "/internal/agents/validate",
                {"X-Gateway-Token": GATEWAY_TOKEN},
                json.dumps({"agent_id": "legacy-agent"}).encode("utf-8"),
            )
            response = json.loads(body)
            self.assertEqual(status, 200)
            self.assertTrue(response["valid"])
            self.assertFalse(response["enforced"])


if __name__ == "__main__":
    unittest.main()
