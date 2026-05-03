from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "gb18030")


@dataclass(frozen=True)
class LoadedText:
    path: Path
    text: str
    encoding: str
    sha256: str


def load_txt(path: str | Path, *, encoding: str = "auto") -> LoadedText:
    file_path = Path(path)
    raw = file_path.read_bytes()
    if encoding and encoding.lower() != "auto":
        text = raw.decode(encoding)
        return LoadedText(
            path=file_path,
            text=_normalize_newlines(text),
            encoding=encoding,
            sha256=hashlib.sha256(raw).hexdigest(),
        )

    errors: list[str] = []
    for candidate in ENCODING_CANDIDATES:
        try:
            text = raw.decode(candidate)
            return LoadedText(
                path=file_path,
                text=_normalize_newlines(text),
                encoding=candidate,
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        except UnicodeDecodeError as exc:
            errors.append(f"{candidate}: {exc}")
    raise UnicodeDecodeError("auto", raw, 0, 1, "; ".join(errors))


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()
