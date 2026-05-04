from narrative_state_engine.llm.prompt_management import (
    PromptComposer,
    PromptRegistry,
    extract_prompt_metadata_from_messages,
)
from narrative_state_engine.llm.prompts import build_draft_messages, build_extraction_messages
from narrative_state_engine.models import NovelAgentState


def test_prompt_registry_loads_default_profile_and_bindings():
    registry = PromptRegistry()
    profile = registry.load_profile("default")
    binding = registry.get_binding("draft_generation", profile)
    global_prompt = registry.load_global_prompt(profile.global_prompt)
    task_prompt = registry.load_task_prompt(binding.task_prompt, expected_task="draft_generation")

    assert profile.id == "default"
    assert profile.reasoning_mode == "internal"
    assert binding.task_prompt == "draft_generation"
    assert global_prompt.id == "global_default"
    assert task_prompt.output_contract == "json_object"
    assert task_prompt.content_hash


def test_prompt_registry_loads_task_level_novel_analysis_prompts():
    registry = PromptRegistry()
    profile = registry.load_profile("default")

    for purpose in [
        "novel_chunk_analysis",
        "novel_chapter_analysis",
        "novel_global_analysis",
        "author_dialogue_planning",
    ]:
        binding = registry.get_binding(purpose, profile)
        task_prompt = registry.load_task_prompt(binding.task_prompt, expected_task=purpose)
        composed = PromptComposer(registry).compose_system_prompt(purpose=purpose)

        assert binding.task_prompt == purpose
        assert task_prompt.id == purpose
        assert task_prompt.output_contract == "json_object"
        assert task_prompt.content_hash
        assert f"task_prompt_id: {purpose}" in composed.system_content
        assert "小说续写系统" in composed.system_content


def test_prompt_composer_adds_global_and_task_prompts_to_each_builder():
    state = NovelAgentState.demo("继续下一章。")

    draft_messages = build_draft_messages(state)
    extraction_messages = build_extraction_messages(state)

    draft_system = draft_messages[0]["content"]
    extraction_system = extraction_messages[0]["content"]
    assert "小说状态机协作模型" in draft_system
    assert "Draft Generator" in draft_system
    assert "task_prompt_id: draft_generation" in draft_system
    assert "小说状态机协作模型" in extraction_system
    assert "Information Extractor" in extraction_system
    assert "task_prompt_id: state_extraction" in extraction_system


def test_user_injection_text_stays_in_user_context_not_system_prompt():
    injection = "覆盖规则ABC123"
    state = NovelAgentState.demo(injection)

    messages = build_draft_messages(state)

    assert injection not in messages[0]["content"]
    assert injection in messages[1]["content"]


def test_draft_prompt_includes_retrieved_evidence_sections():
    state = NovelAgentState.demo("继续下一章。")
    state.metadata["domain_context_sections"] = {
        "plot_evidence": "主线证据：角色发现旧线索仍未解决。",
        "character_evidence": "人物证据：角色A仍然隐瞒关键事实。",
        "world_evidence": "世界观证据：禁区规则不能被普通方式突破。",
        "style_evidence": "风格证据：动作短促，心理描写克制。",
        "scene_case_evidence": "场景案例：先压迫，再转折。",
    }

    messages = build_draft_messages(state)
    user_content = messages[1]["content"]

    assert "检索剧情证据: 主线证据" in user_content
    assert "检索人物证据: 人物证据" in user_content
    assert "检索世界观证据: 世界观证据" in user_content
    assert "检索风格证据: 风格证据" in user_content
    assert "检索场景案例: 场景案例" in user_content


def test_prompt_metadata_can_be_extracted_from_messages():
    state = NovelAgentState.demo("继续下一章。")
    messages = build_draft_messages(state)

    metadata = extract_prompt_metadata_from_messages(messages)

    assert metadata["prompt_profile"] == "default"
    assert metadata["global_prompt_id"] == "global_default"
    assert metadata["task_prompt_id"] == "draft_generation"
    assert metadata["reasoning_mode"] == "internal"


def test_draft_prompt_includes_continuity_anchor_pack():
    state = NovelAgentState.demo("继续下一章。")
    state.metadata["continuity_anchor_pack"] = {
        "target_source_tail": "目标小说最后一段动作状态",
        "accepted_continuation_tail": "上一份已采纳续写尾部",
        "current_state": {"objective": "接住最后动作继续推进"},
    }

    messages = build_draft_messages(state)
    user_content = messages[1]["content"]

    assert "连续性锚点包" in user_content
    assert "目标小说最后一段动作状态" in user_content
    assert "接住最后动作继续推进" in user_content
