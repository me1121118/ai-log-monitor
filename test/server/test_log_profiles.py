import unittest

from server.app.log_profiles import profile_source


class LogProfileTests(unittest.TestCase):
    def test_profiles_known_service_paths(self):
        cases = [
            ({"service": "nginx", "file_path": "/host/var/log/nginx/access.log"}, "proxy", "access", True),
            ({"service": "nginx", "file_path": "/host/var/log/nginx/error.log"}, "proxy", "error", False),
            ({"service": "mariadb", "file_path": "/host/var/log/mysql/error.log"}, "database", "error", False),
            ({"service": "haproxy", "log_type": "journal"}, "proxy", "journal", True),
            ({"service": "kernel", "file_path": "/host/var/log/syslog"}, "system", "system", False),
            ({"service": "sshd", "file_path": "/host/var/log/auth.log"}, "security", "audit", False),
        ]

        for event, service_class, source_kind, traffic_candidate in cases:
            with self.subTest(event=event):
                profile = profile_source(event)
                self.assertEqual(profile["service_class"], service_class)
                self.assertEqual(profile["source_kind"], source_kind)
                self.assertEqual(profile["traffic_candidate"], traffic_candidate)

    def test_unknown_source_is_not_assumed_to_be_traffic(self):
        profile = profile_source({"service": "custom", "file_path": "/opt/custom/log.txt"})

        self.assertEqual(profile["service_class"], "unknown")
        self.assertFalse(profile["traffic_candidate"])


if __name__ == "__main__":
    unittest.main()
