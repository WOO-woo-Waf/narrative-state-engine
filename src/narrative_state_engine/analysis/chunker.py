from __future__ import annotations

import re

from narrative_state_engine.analysis.models import TextChunk


_CHAPTER_HEADING_RE = re.compile(
    r"^\s*((?:第\s*[0-9一二三四五六七八九十百千万两零〇]+[章节卷部集回]|chapter\s+\d+)[^\n]*)$",
    flags=re.IGNORECASE | re.MULTILINE,
)


class TextChunker:
    def __init__(
        self,
        *,
        max_chunk_chars: int = 1800,
        overlap_chars: int = 240,
        min_chunk_chars: int = 240,
    ) -> None:
        self.max_chunk_chars = max(400, int(max_chunk_chars))
        self.overlap_chars = max(0, min(int(overlap_chars), self.max_chunk_chars - 100))
        self.min_chunk_chars = max(80, int(min_chunk_chars))

    def chunk(self, text: str) -> list[TextChunk]:
        normalized = (text or "").replace("\r\n", "\n")
        if not normalized.strip():
            return []

        sections = self._split_sections(normalized)
        chunks: list[TextChunk] = []
        for chapter_index, section in enumerate(sections, start=1):
            chunks.extend(
                self._rolling_chunks(
                    text=str(section["text"]),
                    base_offset=int(section["start_offset"]),
                    chapter_index=chapter_index,
                    heading=str(section["heading"]),
                )
            )
        return chunks

    def _split_sections(self, text: str) -> list[dict[str, str | int]]:
        matches = list(_CHAPTER_HEADING_RE.finditer(text))
        if not matches:
            return [{"heading": "", "text": text, "start_offset": 0}]

        sections: list[dict[str, str | int]] = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            section_text = text[start:end]
            if not section_text.strip():
                continue
            sections.append(
                {
                    "heading": (match.group(1) or "").strip(),
                    "text": section_text,
                    "start_offset": start,
                }
            )
        return sections or [{"heading": "", "text": text, "start_offset": 0}]

    def _rolling_chunks(
        self,
        *,
        text: str,
        base_offset: int,
        chapter_index: int,
        heading: str,
    ) -> list[TextChunk]:
        if not text.strip():
            return []

        step = self.max_chunk_chars - self.overlap_chars
        if step <= 0:
            step = self.max_chunk_chars

        chunks: list[TextChunk] = []
        local_idx = 1
        start = 0
        while start < len(text):
            end = min(start + self.max_chunk_chars, len(text))
            chunk_text = text[start:end]
            if not chunk_text.strip():
                break

            if len(chunk_text.strip()) < self.min_chunk_chars and chunks:
                previous = chunks[-1]
                previous.text = (previous.text.rstrip() + "\n" + chunk_text.lstrip()).strip()
                previous.end_offset = base_offset + end
                break

            chunks.append(
                TextChunk(
                    chunk_id=f"ch{chapter_index:03d}-{local_idx:03d}",
                    chapter_index=chapter_index,
                    heading=heading,
                    start_offset=base_offset + start,
                    end_offset=base_offset + end,
                    text=chunk_text.strip(),
                )
            )
            local_idx += 1
            if end >= len(text):
                break
            start += step
        return chunks
