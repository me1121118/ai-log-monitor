import unittest

from server.app.log_parsers import parse_signal_fields


class LogParserTests(unittest.TestCase):
    def test_extracts_http_request_status_and_latency(self):
        fields = parse_signal_fields({
            "message": '10.0.0.1 - - "GET /api/orders HTTP/1.1" 503 120 request_time=0.250',
        })

        self.assertEqual(fields["request_method"], "GET")
        self.assertEqual(fields["request_path"], "/api/orders")
        self.assertEqual(fields["status_code"], 503)
        self.assertEqual(fields["latency_ms"], 250.0)

    def test_extracts_database_error_code(self):
        fields = parse_signal_fields({
            "message": "[ERROR] [MY-010119] Aborting due to too many connections",
        })

        self.assertEqual(fields["database_error_code"], "MY-010119")

    def test_existing_status_code_has_precedence(self):
        fields = parse_signal_fields({
            "status_code": 502,
            "message": '"GET / HTTP/1.1" 200 10',
        })

        self.assertEqual(fields["status_code"], 502)


if __name__ == "__main__":
    unittest.main()
