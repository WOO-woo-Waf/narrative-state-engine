from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JsonParseResult:
    ok: bool
    data: Any = None
    error: str = ""
    raw: str = ""


class JsonBlobParser:
    _FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.IGNORECASE)

    def extract_json_text(self, text: str) -> str:
        if not isinstance(text, str):
            return ""
        raw = text.strip()
        if not raw:
            return ""
        match = self._FENCE_RE.search(raw)
        if match:
            raw = (match.group(1) or "").strip()
        if raw.startswith("{") and raw.endswith("}"):
            return raw
        if raw.startswith("[") and raw.endswith("]"):
            return raw
        obj = self._extract_balanced(raw, "{", "}")
        if obj:
            return obj
        arr = self._extract_balanced(raw, "[", "]")
        if arr:
            return arr
        return raw

    def parse(self, text: str) -> JsonParseResult:
        raw = self.extract_json_text(text)
        if not raw:
            return JsonParseResult(ok=False, error="empty", raw="")
        try:
            return JsonParseResult(ok=True, data=json.loads(raw), raw=raw)
        except Exception as exc:
            return JsonParseResult(ok=False, error=str(exc), raw=raw)

    def _extract_balanced(self, text: str, open_ch: str, close_ch: str) -> str:
        start = text.find(open_ch)
        if start == -1:
            return ""
        depth = 0
        in_str: str | None = None
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_str:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == in_str:
                    in_str = None
                continue
            if ch in {'"', "'"}:
                in_str = ch
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return ""
