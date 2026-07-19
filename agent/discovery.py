from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .config import AgentConfig, LogPath


LogCandidate = tuple[str, str, str]


DEFAULT_LOG_CANDIDATES: tuple[LogCandidate, ...] = (
    ("syslog", "/host/var/log/syslog", "system"),
    ("auth_log", "/host/var/log/auth.log", "auth"),
    ("kernel_log", "/host/var/log/kern.log", "kernel"),
    ("messages", "/host/var/log/messages", "system"),
    ("nginx_error", "/host/var/log/nginx/error.log", "nginx"),
    ("nginx_access", "/host/var/log/nginx/access.log", "nginx"),
    ("apache_error", "/host/var/log/apache2/error.log", "apache"),
    ("apache_access", "/host/var/log/apache2/access.log", "apache"),
    ("httpd_error", "/host/var/log/httpd/error_log", "apache"),
    ("httpd_access", "/host/var/log/httpd/access_log", "apache"),
    ("mysql_error", "/host/var/log/mysql/error.log", "mysql"),
    ("mariadb", "/host/var/log/mariadb/mariadb.log", "mariadb"),
    ("postgresql", "/host/var/log/postgresql/*.log", "postgresql"),
    ("redis", "/host/var/log/redis/redis-server.log", "redis"),
    ("haproxy", "/host/var/log/haproxy.log", "haproxy"),
    ("syslog", "/var/log/syslog", "system"),
    ("auth_log", "/var/log/auth.log", "auth"),
    ("kernel_log", "/var/log/kern.log", "kernel"),
    ("messages", "/var/log/messages", "system"),
    ("nginx_error", "/var/log/nginx/error.log", "nginx"),
    ("nginx_access", "/var/log/nginx/access.log", "nginx"),
    ("apache_error", "/var/log/apache2/error.log", "apache"),
    ("apache_access", "/var/log/apache2/access.log", "apache"),
    ("httpd_error", "/var/log/httpd/error_log", "apache"),
    ("httpd_access", "/var/log/httpd/access_log", "apache"),
    ("mysql_error", "/var/log/mysql/error.log", "mysql"),
    ("mariadb", "/var/log/mariadb/mariadb.log", "mariadb"),
    ("postgresql", "/var/log/postgresql/*.log", "postgresql"),
    ("redis", "/var/log/redis/redis-server.log", "redis"),
    ("haproxy", "/var/log/haproxy.log", "haproxy"),
)


def with_discovered_log_paths(
    config: AgentConfig,
    candidates: Iterable[LogCandidate] = DEFAULT_LOG_CANDIDATES,
) -> AgentConfig:
    discovered = discover_log_paths([*config.log_paths, *_installed_service_log_paths()], candidates)
    if discovered == config.log_paths:
        return config
    return replace(config, log_paths=discovered)


def _installed_service_log_paths() -> list[LogPath]:
    for etc_root, syslog in (
        (Path("/host/etc"), Path("/host/var/log/syslog")),
        (Path("/etc"), Path("/var/log/syslog")),
    ):
        if (etc_root / "mysql").is_dir() and _is_readable_file(syslog):
            return [
                LogPath(
                    name="mariadb_journal",
                    path=syslog,
                    type="mariadb",
                    includes=("mariadbd", "mysqld"),
                )
            ]
    return []


def discover_log_paths(
    configured_paths: Iterable[LogPath],
    candidates: Iterable[LogCandidate] = DEFAULT_LOG_CANDIDATES,
) -> list[LogPath]:
    merged = list(configured_paths)
    seen_paths = {str(item.path) for item in merged}
    seen_names = {item.name for item in merged}

    for base_name, pattern, log_type in candidates:
        for path in _expand_pattern(pattern):
            path_key = str(path)
            if path_key in seen_paths or not _is_readable_file(path):
                continue
            name = _unique_name(base_name, path, seen_names)
            merged.append(LogPath(name=name, path=path, type=log_type))
            seen_paths.add(path_key)
            seen_names.add(name)

    return merged


def _expand_pattern(pattern: str) -> list[Path]:
    path = Path(pattern)
    if not any(char in pattern for char in "*?["):
        return [path]
    return sorted(candidate for candidate in path.parent.glob(path.name))


def _is_readable_file(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_file():
            return False
        with path.open("r", encoding="utf-8", errors="replace"):
            return True
    except OSError:
        return False


def _unique_name(base_name: str, path: Path, seen_names: set[str]) -> str:
    if base_name not in seen_names:
        return base_name
    suffix = _safe_suffix(path)
    candidate = f"{base_name}_{suffix}"
    counter = 2
    while candidate in seen_names:
        candidate = f"{base_name}_{suffix}_{counter}"
        counter += 1
    return candidate


def _safe_suffix(path: Path) -> str:
    suffix = path.name or "log"
    return "".join(char.lower() if char.isalnum() else "_" for char in suffix).strip("_") or "log"
