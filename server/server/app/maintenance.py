from __future__ import annotations

import json
import argparse
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SAFE_CONFIG_NAMES = {"ai.yaml", "config.yaml"}


def create_backup(
    data_dir: Path,
    config_paths: list[Path],
    backup_dir: Path,
    created_at: str | None = None,
    include_secrets: bool = False,
) -> Path:
    created = created_at or datetime.now(timezone.utc).isoformat()
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive_path = backup_dir / f"ai-log-backup-{_safe_timestamp(created)}.zip"
    data_dir = Path(data_dir)
    included_data: list[str] = []
    included_config: list[str] = []

    manifest = {
        "app": "ai-log-monitor",
        "created_at": created,
        "format": 1,
        "secrets_included": bool(include_secrets),
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if data_dir.exists():
            for path in sorted(item for item in data_dir.rglob("*") if item.is_file()):
                relative = path.relative_to(data_dir).as_posix()
                arcname = f"data/{relative}"
                archive.write(path, arcname)
                included_data.append(arcname)

        for config_path in config_paths:
            path = Path(config_path)
            if not path.is_file():
                continue
            if not include_secrets and path.name not in SAFE_CONFIG_NAMES:
                continue
            arcname = f"config/{path.name}"
            archive.write(path, arcname)
            included_config.append(arcname)

        manifest["data_files"] = included_data
        manifest["config_files"] = included_config
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return archive_path


def restore_backup(archive_path: Path, data_dir: Path, config_dir: Path) -> dict[str, Any]:
    data_dir = Path(data_dir)
    config_dir = Path(config_dir)
    data_files = 0
    config_files = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            name = _safe_member_name(member.filename)
            if name is None or member.is_dir() or name == "manifest.json":
                continue
            if name.startswith("data/"):
                target = data_dir / name.removeprefix("data/")
                _extract_member(archive, member, target)
                data_files += 1
            elif name.startswith("config/"):
                relative_name = name.removeprefix("config/")
                if "/" in relative_name or "\\" in relative_name:
                    continue
                target = config_dir / relative_name
                _extract_member(archive, member, target)
                config_files += 1
    return {"data_files": data_files, "config_files": config_files}


def _extract_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member) as source:
        target.write_bytes(source.read())


def _safe_member_name(name: str) -> str | None:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def _safe_timestamp(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value).strip("-") or "backup"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Log Monitor maintenance tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--data-dir", required=True)
    backup_parser.add_argument("--backup-dir", required=True)
    backup_parser.add_argument("--config", action="append", default=[])
    backup_parser.add_argument("--include-secrets", action="store_true")

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--archive", required=True)
    restore_parser.add_argument("--data-dir", required=True)
    restore_parser.add_argument("--config-dir", required=True)

    args = parser.parse_args(argv)
    if args.command == "backup":
        archive = create_backup(
            data_dir=Path(args.data_dir),
            backup_dir=Path(args.backup_dir),
            config_paths=[Path(item) for item in args.config],
            include_secrets=bool(args.include_secrets),
        )
        print(json.dumps({"archive": str(archive)}, sort_keys=True))
        return 0
    if args.command == "restore":
        result = restore_backup(
            Path(args.archive),
            data_dir=Path(args.data_dir),
            config_dir=Path(args.config_dir),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
