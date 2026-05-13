from narrative_state_engine.analysis.chunker import TextChunker


def test_chunker_splits_by_chapter_heading_and_paragraph_budget():
    text = (
        "第一章 起风\n"
        + "\n\n".join(f"夜色压在街道上，第{i}段仍然属于同一场景。" * 4 for i in range(12))
        + "\n\n第二章 落雨\n"
        + "\n\n".join(f"雨滴打在窗沿，第{i}段继续推进。" * 4 for i in range(12))
    )
    chunker = TextChunker(max_chunk_chars=260, overlap_chars=40)

    chunks = chunker.chunk(text)

    assert len(chunks) >= 3
    assert chunks[0].chapter_index == 1
    assert any(item.chapter_index == 2 for item in chunks)
    assert all(item.end_offset > item.start_offset for item in chunks)
    assert all(not item.text.startswith(" ") for item in chunks)


def test_chunker_default_budget_is_large_context_oriented(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_ANALYSIS_MAX_CHUNK_CHARS", "60000")
    monkeypatch.setenv("NOVEL_AGENT_ANALYSIS_CHUNK_OVERLAP_CHARS", "0")
    text = "\n\n".join(f"第{i}段，仍然属于同一个长上下文分析块。" * 20 for i in range(80))

    chunks = TextChunker().chunk(text)

    assert len(chunks) == 1
    assert len(chunks[0].text) > 10_000


def test_chunker_keeps_short_paragraphs_together_instead_of_fixed_slicing():
    paragraphs = [f"第{i}段，人物在同一个场景里继续说话。" * 4 for i in range(8)]
    text = "\n\n".join(paragraphs)
    chunker = TextChunker(max_chunk_chars=400, overlap_chars=30, hard_chunk_chars=520)

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert all(item.chapter_index == 1 for item in chunks)
    assert all("\n\n" in item.text or len(item.text) <= 90 for item in chunks)
    assert all(len(item.text) <= 520 for item in chunks)


def test_chunker_splits_single_overlong_paragraph_by_sentence_boundary():
    sentence = "他停在门前，听见门后有很轻的响动。"
    text = sentence * 40
    chunker = TextChunker(max_chunk_chars=400, overlap_chars=0, hard_chunk_chars=460)

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert all(len(item.text) <= 460 for item in chunks)
    assert all(item.text.endswith("。") for item in chunks[:-1])
