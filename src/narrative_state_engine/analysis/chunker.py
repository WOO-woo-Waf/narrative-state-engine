from __future__ import annotations

import re

from narrative_state_engine.analysis.models import TextChunk


_CHAPTER_HEADING_RE = re.compile(
    r"^\s*((?:第\s*[0-9一二三四五六七八九十百千万两零〇]+\s*[章节卷部集回]|chapter\s+\d+)[^\n]*)$",
    flags=re.IGNORECASE | re.MULTILINE,
)
_PARAGRAPH_RE = re.compile(r"\S(?:.*(?:\n(?!\s*\n).*)*)?", flags=re.MULTILINE)
_SENTENCE_RE = re.compile(r".+?(?:[。！？!?]+[”’\"]?|$)", flags=re.DOTALL)


class TextChunker:
    """Chapter and paragraph aware chunker.

    ``max_chunk_chars`` is a soft context budget, not a fixed slicing size.
    The chunker prefers natural chapter/paragraph/sentence boundaries and only
    falls back to a hard character split when a single sentence is too large.
    """

    def __init__(
        self,
        *,
        max_chunk_chars: int = 1800,
        overlap_chars: int = 240,
        min_chunk_chars: int = 240,
        hard_chunk_chars: int | None = None,
    ) -> None:
        self.target_chunk_chars = max(400, int(max_chunk_chars))
        self.overlap_chars = max(0, min(int(overlap_chars), self.target_chunk_chars - 100))
        self.min_chunk_chars = max(80, int(min_chunk_chars))
        fallback_hard = max(self.target_chunk_chars + 1000, int(self.target_chunk_chars * 1.35))
        self.hard_chunk_chars = max(self.target_chunk_chars, int(hard_chunk_chars or fallback_hard))

    @property
    def max_chunk_chars(self) -> int:
        return self.target_chunk_chars

    def chunk(self, text: str) -> list[TextChunk]:
        normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip():
            return []

        sections = self._split_sections(normalized)
        chunks: list[TextChunk] = []
        for chapter_index, section in enumerate(sections, start=1):
            chunks.extend(
                self._semantic_chunks(
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

    def _semantic_chunks(
        self,
        *,
        text: str,
        base_offset: int,
        chapter_index: int,
        heading: str,
    ) -> list[TextChunk]:
        blocks = self._paragraph_blocks(text=text, base_offset=base_offset)
        if not blocks:
            return []

        chunks: list[TextChunk] = []
        current_parts: list[tuple[int, int, str]] = []
        current_len = 0

        def flush() -> None:
            nonlocal current_parts, current_len
            if not current_parts:
                return
            chunks.append(
                self._build_chunk(
                    chapter_index=chapter_index,
                    local_idx=len(chunks) + 1,
                    heading=heading,
                    parts=current_parts,
                )
            )
            current_parts = []
            current_len = 0

        for start, end, paragraph in blocks:
            if len(paragraph) > self.hard_chunk_chars:
                flush()
                chunks.extend(
                    self._split_long_paragraph(
                        paragraph=paragraph,
                        absolute_start=start,
                        chapter_index=chapter_index,
                        heading=heading,
                        local_idx_start=len(chunks) + 1,
                    )
                )
                continue

            proposed_len = current_len + (2 if current_parts else 0) + len(paragraph)
            if current_parts and proposed_len > self.target_chunk_chars:
                flush()

            current_parts.append((start, end, paragraph))
            current_len = current_len + (2 if current_len else 0) + len(paragraph)

            if current_len >= self.hard_chunk_chars:
                flush()

        flush()
        return self._merge_tiny_tail(chunks)

    def _paragraph_blocks(self, *, text: str, base_offset: int) -> list[tuple[int, int, str]]:
        blocks: list[tuple[int, int, str]] = []
        for match in _PARAGRAPH_RE.finditer(text):
            raw = match.group(0)
            paragraph = raw.strip()
            if not paragraph:
                continue
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw.rstrip())
            start = base_offset + match.start() + leading
            end = base_offset + match.start() + trailing
            blocks.append((start, end, paragraph))
        return blocks

    def _split_long_paragraph(
        self,
        *,
        paragraph: str,
        absolute_start: int,
        chapter_index: int,
        heading: str,
        local_idx_start: int,
    ) -> list[TextChunk]:
        units = self._sentence_units(paragraph=paragraph, absolute_start=absolute_start)
        chunks: list[TextChunk] = []
        current_parts: list[tuple[int, int, str]] = []
        current_len = 0

        def flush() -> None:
            nonlocal current_parts, current_len
            if current_parts:
                chunks.append(
                    self._build_chunk(
                        chapter_index=chapter_index,
                        local_idx=local_idx_start + len(chunks),
                        heading=heading,
                        parts=current_parts,
                    )
                )
                current_parts = []
                current_len = 0

        for start, end, sentence in units:
            if len(sentence) > self.hard_chunk_chars:
                flush()
                for piece_start, piece in self._hard_split(sentence=sentence, absolute_start=start):
                    piece_end = piece_start + len(piece)
                    chunks.append(
                        self._build_chunk(
                            chapter_index=chapter_index,
                            local_idx=local_idx_start + len(chunks),
                            heading=heading,
                            parts=[(piece_start, piece_end, piece)],
                        )
                    )
                continue

            proposed_len = current_len + (2 if current_parts else 0) + len(sentence)
            if current_parts and proposed_len > self.target_chunk_chars:
                flush()
            current_parts.append((start, end, sentence))
            current_len = current_len + (2 if current_len else 0) + len(sentence)
        flush()
        return chunks

    def _sentence_units(self, *, paragraph: str, absolute_start: int) -> list[tuple[int, int, str]]:
        units: list[tuple[int, int, str]] = []
        for match in _SENTENCE_RE.finditer(paragraph):
            sentence = match.group(0).strip()
            if not sentence:
                continue
            leading = len(match.group(0)) - len(match.group(0).lstrip())
            start = absolute_start + match.start() + leading
            end = start + len(sentence)
            units.append((start, end, sentence))
        return units or [(absolute_start, absolute_start + len(paragraph), paragraph)]

    def _hard_split(self, *, sentence: str, absolute_start: int) -> list[tuple[int, str]]:
        pieces: list[tuple[int, str]] = []
        start = 0
        while start < len(sentence):
            end = min(start + self.hard_chunk_chars, len(sentence))
            piece = sentence[start:end].strip()
            if piece:
                leading = len(sentence[start:end]) - len(sentence[start:end].lstrip())
                pieces.append((absolute_start + start + leading, piece))
            start = end
        return pieces

    def _build_chunk(
        self,
        *,
        chapter_index: int,
        local_idx: int,
        heading: str,
        parts: list[tuple[int, int, str]],
    ) -> TextChunk:
        text = "\n\n".join(part[2] for part in parts).strip()
        return TextChunk(
            chunk_id=f"ch{chapter_index:03d}-{local_idx:03d}",
            chapter_index=chapter_index,
            heading=heading,
            start_offset=parts[0][0],
            end_offset=parts[-1][1],
            text=text,
        )

    def _merge_tiny_tail(self, chunks: list[TextChunk]) -> list[TextChunk]:
        if len(chunks) < 2:
            return chunks
        tail = chunks[-1]
        previous = chunks[-2]
        combined_len = len(previous.text) + 2 + len(tail.text)
        if len(tail.text) < self.min_chunk_chars and combined_len <= self.target_chunk_chars:
            previous.text = (previous.text.rstrip() + "\n\n" + tail.text.lstrip()).strip()
            previous.end_offset = tail.end_offset
            return chunks[:-1]
        return chunks
