from __future__ import annotations
from typing import Any
from html import escape
import json
import re
from urllib.parse import unquote

LOG_PAGE_SIZE = 10

def _bearer_token(value: str) -> str:
    prefix = "Bearer "
    return value[len(prefix):].strip() if value.startswith(prefix) else ""


def _cookie_value(cookie_header: str, name: str) -> str:
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == name:
            return unquote(value.strip())
    return ""


def _h(value: Any) -> str:
    return escape(str(value), quote=True)


def _positive_int(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default
from pathlib import Path


def _compact_page_numbers(current: int, total_pages: int) -> list[int | None]:
    if total_pages <= 7:
        return list(range(1, total_pages + 1))

    pages = {1, total_pages, current - 1, current, current + 1}
    if current <= 3:
        pages.update({2, 3})
    if current >= total_pages - 2:
        pages.update({total_pages - 2, total_pages - 1})

    ordered = [page for page in sorted(pages) if 1 <= page <= total_pages]
    compact: list[int | None] = []
    previous = 0
    for page in ordered:
        if previous and page - previous > 1:
            compact.append(None)
        compact.append(page)
        previous = page
    return compact


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    if not name:
        return "uploaded.log"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "uploaded.log"


def _safe_path_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())[:80] or "unknown"


def _safe_timestamp(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", value)
