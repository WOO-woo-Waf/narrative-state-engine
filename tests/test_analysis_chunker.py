from narrative_state_engine.analysis.chunker import TextChunker


def test_chunker_splits_by_chapter_heading_and_window():
    text = (
        "第一章 起风\n"
        + "夜色压在街道上。" * 80
        + "\n第二章 落雨\n"
        + "雨滴打在窗沿。" * 80
    )
    chunker = TextChunker(max_chunk_chars=280, overlap_chars=40)

    chunks = chunker.chunk(text)

    assert len(chunks) >= 3
    assert chunks[0].chapter_index == 1
    assert any(item.chapter_index == 2 for item in chunks)
    assert all(item.end_offset > item.start_offset for item in chunks)


def test_chunker_handles_plain_text_without_heading():
    text = "这是一段没有章节标题的文本。" * 100
    chunker = TextChunker(max_chunk_chars=220, overlap_chars=30)

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert all(item.chapter_index == 1 for item in chunks)
