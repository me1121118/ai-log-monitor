import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from server.app.maintenance import create_backup, restore_backup


class MaintenanceTests(unittest.TestCase):
    def test_create_backup_includes_database_imports_and_safe_configs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            config_dir = root / "server"
            backup_dir = root / "backups"
            data_dir.mkdir()
            config_dir.mkdir()
            (data_dir / "database.db").write_text("db-content", encoding="utf-8")
            (data_dir / "imports").mkdir()
            (data_dir / "imports" / "sample.log").write_text("log-content", encoding="utf-8")
            (config_dir / "ai.yaml").write_text("ai:\n  mode: mock\n", encoding="utf-8")
            (config_dir / "config.yaml").write_text("server:\n  port: 8888\n", encoding="utf-8")
            (config_dir / "secrets.env").write_text("ADMIN_PASSWORD=secret\n", encoding="utf-8")

            archive = create_backup(
                data_dir=data_dir,
                config_paths=[config_dir / "ai.yaml", config_dir / "config.yaml", config_dir / "secrets.env"],
                backup_dir=backup_dir,
                created_at="2026-07-17T00:00:00+00:00",
            )

            with zipfile.ZipFile(archive) as backup:
                names = set(backup.namelist())
                manifest = json.loads(backup.read("manifest.json").decode("utf-8"))
            self.assertIn("data/database.db", names)
            self.assertIn("data/imports/sample.log", names)
            self.assertIn("config/ai.yaml", names)
            self.assertIn("config/config.yaml", names)
            self.assertNotIn("config/secrets.env", names)
            self.assertEqual(manifest["created_at"], "2026-07-17T00:00:00+00:00")
            self.assertEqual(manifest["secrets_included"], False)

    def test_restore_backup_restores_data_and_config_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_data = root / "source-data"
            source_config = root / "source-config"
            source_data.mkdir()
            source_config.mkdir()
            (source_data / "database.db").write_text("db-content", encoding="utf-8")
            (source_config / "ai.yaml").write_text("ai:\n  mode: api\n", encoding="utf-8")
            (source_config / "config.yaml").write_text("server:\n  port: 8888\n", encoding="utf-8")
            archive = create_backup(
                data_dir=source_data,
                config_paths=[source_config / "ai.yaml", source_config / "config.yaml"],
                backup_dir=root / "backups",
                created_at="2026-07-17T00:00:00+00:00",
            )
            target_data = root / "target-data"
            target_config = root / "target-config"

            restored = restore_backup(archive, data_dir=target_data, config_dir=target_config)

            self.assertEqual((target_data / "database.db").read_text(encoding="utf-8"), "db-content")
            self.assertIn("mode: api", (target_config / "ai.yaml").read_text(encoding="utf-8"))
            self.assertIn("port: 8888", (target_config / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(restored["data_files"], 1)
            self.assertEqual(restored["config_files"], 2)


if __name__ == "__main__":
    unittest.main()
