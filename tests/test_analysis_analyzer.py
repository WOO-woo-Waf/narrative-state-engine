from narrative_state_engine.analysis import NovelTextAnalyzer


def test_analyzer_builds_story_bible_assets():
    text = (
        "第一章\n"
        "风从巷口压过来，他停住脚步，抬眼看向窗台。"
        "她的眉梢轻轻一挑，神色仍旧克制。"
        "“你真的要现在进去吗？”她低声问。"
        "他没有回答，只是握紧门把，心里闪过迟疑。\n"
        "第二章\n"
        "夜雨更密，街灯把影子拉长。"
        "“别回头。”他在雨里说。"
    )
    analyzer = NovelTextAnalyzer(max_chunk_chars=200)

    result = analyzer.analyze(
        source_text=text,
        story_id="story-test-001",
        story_title="Test Story",
    )

    assert result.story_id == "story-test-001"
    assert result.summary["chunk_count"] >= 2
    assert result.summary["chapter_count"] >= 2
    assert len(result.chunk_states) == result.summary["chunk_state_count"]
    assert len(result.chapter_states) >= 2
    assert len(result.snippet_bank) > 0
    assert len(result.story_bible.character_cards) > 0
    assert len(result.story_bible.plot_threads) > 0
    assert len(result.story_bible.world_rules) > 0
    assert result.global_story_state is not None
    assert result.coverage["total_chars"] == len(text)
    assert result.story_synopsis.strip()

    profile = result.story_bible.style_profile
    assert "dialogue" in profile.description_mix
    assert "short" in profile.sentence_length_distribution
    assert isinstance(profile.lexical_fingerprint, list)
