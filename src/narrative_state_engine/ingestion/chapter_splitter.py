from __future__ import annotations

import re
from dataclasses import dataclass


CHAPTER_HEADING_RE = re.compile(
    r"^\s*(第[零〇一二三四五六七八九十百千万\d]+[章章节回卷集部].{0,80})\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ChapterSlice:
    chapter_index: int
    title: str
    text: str
    start_offset: int
    end_offset: int


def split_chapters(text: str, *, fallback_chars: int = 9000) -> list[ChapterSlice]:
    source = text or ""
    matches = list(CHAPTER_HEADING_RE.finditer(source))
    if not matches:
        return _fallback_chapters(source, fallback_chars=fallback_chars)

    chapters: list[ChapterSlice] = []
    for idx, match in enumerate(matches):
        next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(source)
        start = match.start()
        end = next_start
        body = source[start:end].strip()
        chapters.append(
            ChapterSlice(
                chapter_index=idx + 1,
                title=match.group(1).strip(),
                text=body,
                start_offset=start,
                end_offset=end,
            )
        )
    return chapters


def _fallback_chapters(text: str, *, fallback_chars: int) -> list[ChapterSlice]:
    size = max(int(fallback_chars), 2000)
    chapters: list[ChapterSlice] = []
    start = 0
    idx = 1
    while start < len(text):
        end = _near_boundary(text, min(start + size, len(text)))
        if end <= start:
            end = min(start + size, len(text))
        chapters.append(
            ChapterSlice(
                chapter_index=idx,
                title=f"Pseudo Chapter {idx}",
                text=text[start:end].strip(),
                start_offset=start,
                end_offset=end,
            )
        )
        start = end
        idx += 1
    return chapters or [ChapterSlice(chapter_index=1, title="Pseudo Chapter 1", text="", start_offset=0, end_offset=0)]


def _near_boundary(text: str, pos: int) -> int:
    if pos >= len(text):
        return len(text)
    window_start = max(pos - 800, 0)
    window = text[window_start:pos]
    paragraph = window.rfind("\n\n")
    if paragraph >= 0:
        return window_start + paragraph + 2
    sentence_positions = [window.rfind(mark) for mark in ("。", "！", "？", ".", "!", "?")]
    best = max(sentence_positions)
    if best >= 0:
        return window_start + best + 1
    return pos
