from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkSlice:
    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    chunk_type: str = "prose"


def chunk_chapter(
    text: str,
    *,
    chapter_start_offset: int = 0,
    target_chars: int = 1000,
    overlap_chars: int = 160,
    chunk_type: str = "prose",
) -> list[ChunkSlice]:
    source = text or ""
    target = max(int(target_chars), 300)
    overlap = min(max(int(overlap_chars), 0), target // 2)
    chunks: list[ChunkSlice] = []
    start = 0
    idx = 1
    while start < len(source):
        raw_end = min(start + target, len(source))
        end = _choose_boundary(source, raw_end, start=start)
        if end <= start:
            end = raw_end
        chunk_text = source[start:end].strip()
        if chunk_text:
            chunks.append(
                ChunkSlice(
                    chunk_index=idx,
                    text=chunk_text,
                    start_offset=chapter_start_offset + start,
                    end_offset=chapter_start_offset + end,
                    chunk_type=chunk_type,
                )
            )
            idx += 1
        if end >= len(source):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _choose_boundary(text: str, raw_end: int, *, start: int) -> int:
    if raw_end >= len(text):
        return len(text)
    window_start = max(start + 300, raw_end - 260)
    window = text[window_start:raw_end]
    paragraph = window.rfind("\n\n")
    if paragraph >= 0:
        return window_start + paragraph + 2
    best = max(window.rfind(mark) for mark in ("。", "！", "？", ".", "!", "?"))
    if best >= 0:
        return window_start + best + 1
    newline = window.rfind("\n")
    if newline >= 0:
        return window_start + newline + 1
    return raw_end
