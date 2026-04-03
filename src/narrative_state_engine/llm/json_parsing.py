from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JsonParseResult:
    ok: bool
    data: Any = None
    error: str = ""
    raw: str = ""
    original_raw: str = ""
    repair_applied: bool = False
    repair_notes: list[str] = field(default_factory=list)


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

        first_error = ""
        try:
            return JsonParseResult(ok=True, data=json.loads(raw), raw=raw)
        except Exception as exc:
            first_error = str(exc)

        repaired_raw, repair_notes = self._repair_common_json(raw)
        if repaired_raw != raw:
            try:
                return JsonParseResult(
                    ok=True,
                    data=json.loads(repaired_raw),
                    raw=repaired_raw,
                    original_raw=raw,
                    repair_applied=True,
                    repair_notes=repair_notes,
                )
            except Exception as exc:
                second_error = str(exc)
            try:
                as_python = self._to_python_literal_candidate(repaired_raw)
                parsed_python = ast.literal_eval(as_python)
                if isinstance(parsed_python, (dict, list)):
                    return JsonParseResult(
                        ok=True,
                        data=parsed_python,
                        raw=repaired_raw,
                        original_raw=raw,
                        repair_applied=True,
                        repair_notes=repair_notes + ["python_literal_eval"],
                    )
            except Exception as exc:
                third_error = str(exc)
            return JsonParseResult(
                ok=False,
                error=(
                    f"raw_json_error={first_error}; "
                    f"repaired_json_error={second_error}; "
                    f"python_literal_error={third_error}"
                ),
                raw=repaired_raw,
                original_raw=raw,
                repair_applied=True,
                repair_notes=repair_notes,
            )

        try:
            as_python = self._to_python_literal_candidate(raw)
            parsed_python = ast.literal_eval(as_python)
            if isinstance(parsed_python, (dict, list)):
                return JsonParseResult(
                    ok=True,
                    data=parsed_python,
                    raw=raw,
                    original_raw=raw,
                    repair_applied=True,
                    repair_notes=["python_literal_eval"],
                )
        except Exception as exc:
            python_error = str(exc)
            return JsonParseResult(
                ok=False,
                error=f"raw_json_error={first_error}; python_literal_error={python_error}",
                raw=raw,
                original_raw=raw,
            )

        return JsonParseResult(ok=False, error=f"raw_json_error={first_error}", raw=raw, original_raw=raw)

    def _repair_common_json(self, raw: str) -> tuple[str, list[str]]:
        repaired = raw
        notes: list[str] = []

        replaced_quotes = repaired.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        if replaced_quotes != repaired:
            repaired = replaced_quotes
            notes.append("normalize_smart_quotes")

        escaped_controls = self._escape_control_chars_in_strings(repaired)
        if escaped_controls != repaired:
            repaired = escaped_controls
            notes.append("escape_control_chars_in_strings")

        without_trailing_commas = re.sub(r",\s*([}\]])", r"\1", repaired)
        if without_trailing_commas != repaired:
            repaired = without_trailing_commas
            notes.append("strip_trailing_commas")

        return repaired, notes

    def _escape_control_chars_in_strings(self, raw: str) -> str:
        out: list[str] = []
        in_string = False
        escape = False
        quote_char = '"'

        for ch in raw:
            if in_string:
                if escape:
                    out.append(ch)
                    escape = False
                    continue
                if ch == "\\":
                    out.append(ch)
                    escape = True
                    continue
                if ch == quote_char:
                    out.append(ch)
                    in_string = False
                    continue
                if ch == "\n":
                    out.append("\\n")
                    continue
                if ch == "\r":
                    out.append("\\r")
                    continue
                if ch == "\t":
                    out.append("\\t")
                    continue
                out.append(ch)
                continue

            if ch == quote_char:
                in_string = True
                out.append(ch)
                continue

            out.append(ch)

        return "".join(out)

    def _to_python_literal_candidate(self, raw: str) -> str:
        candidate = raw
        candidate = re.sub(r"\btrue\b", "True", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\bfalse\b", "False", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\bnull\b", "None", candidate, flags=re.IGNORECASE)
        return candidate

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
