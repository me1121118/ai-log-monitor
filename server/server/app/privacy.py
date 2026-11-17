from __future__ import annotations

import re
from typing import Any

from .ai_settings import DEFAULT_AI_SETTINGS

def redact_text(text: str, settings: dict[str, Any] | None = None) -> str:
    active_settings = settings or DEFAULT_AI_SETTINGS
    privacy = dict(active_settings.get("privacy") or {})
    if not privacy.get("redact_before_send", True):
        return text

    fields = privacy.get("redact_fields") or DEFAULT_AI_SETTINGS["privacy"]["redact_fields"]
    result = str(text)
    result = re.sub(
        r"(?i)\b(authorization\s*[:=]\s*)(bearer|basic)\s+[A-Za-z0-9._~+/\-]+=*",
        r"\1\2 [REDACTED]",
        result,
    )
    result = re.sub(
        r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/\-]{8,}=*",
        r"\1 [REDACTED]",
        result,
    )
    for field in fields:
        field_name = str(field).strip()
        if not field_name or field_name.lower() == "authorization":
            continue
        result = re.sub(
            rf"(?i)\b({re.escape(field_name)})\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)",
            r"\1\2[REDACTED]",
            result,
        )
    result = re.sub(
        r"(?i)(://[^:/@\s]+:)[^@/\s]+(@)",
        r"\1[REDACTED]\2",
        result,
    )
    return result
