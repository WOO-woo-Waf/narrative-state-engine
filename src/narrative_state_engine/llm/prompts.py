from __future__ import annotations

import json

from narrative_state_engine.llm.prompt_management import compose_system_prompt
from narrative_state_engine.models import NovelAgentState


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").replace("\r", "\n").replace("\n", " ").split()).strip()


def _truncate_text(value: object, *, max_chars: int) -> str:
    text = _normalize_text(value)
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1] + "…"


def _compact_lines(
    values: list[object],
    *,
    max_items: int,
    max_item_chars: int,
) -> list[str]:
    rows: list[str] = []
    for raw in values:
        text = _truncate_text(raw, max_chars=max_item_chars)
        if text:
            rows.append(text)
        if len(rows) >= max_items:
            break
    return rows


def _format_examples(state: NovelAgentState) -> tuple[str, str]:
    evidence_pack = state.analysis.evidence_pack or {}
    style_examples = evidence_pack.get("style_snippet_examples", {})
    style_rows: list[str] = []
    for snippet_type in ["action", "expression", "appearance", "environment", "dialogue", "inner_monologue"]:
        lines = _compact_lines(
            list(style_examples.get(snippet_type, [])),
            max_items=2,
            max_item_chars=70,
        )
        if lines:
            style_rows.append(f"{snippet_type}: {' | '.join(lines)}")

    case_rows: list[str] = []
    for item in list(evidence_pack.get("event_case_examples", []))[:2]:
        event_type = _truncate_text(item.get("event_type", ""), max_chars=24)
        actions = _compact_lines(list(item.get("action_sequence", [])), max_items=2, max_item_chars=60)
        dialogues = _compact_lines(list(item.get("dialogue_turns", [])), max_items=2, max_item_chars=40)
        segments: list[str] = []
        if event_type:
            segments.append(f"type={event_type}")
        if actions:
            segments.append(f"action={' / '.join(actions)}")
        if dialogues:
            segments.append(f"dialogue={' / '.join(dialogues)}")
        if segments:
            case_rows.append("; ".join(segments))

    return (" || ".join(style_rows) if style_rows else "无"), (" || ".join(case_rows) if case_rows else "无")


def build_draft_messages(state: NovelAgentState) -> list[dict[str, str]]:
    system = compose_system_prompt(purpose="draft_generation").system_content
    schema = {
        "content": "string, 本轮章节片段正文",
        "rationale": "string, 本轮推进理由",
        "planned_beat": "string, 本轮推进点",
        "style_targets": ["string"],
        "continuity_notes": ["string"],
    }

    style_examples_text, case_examples_text = _format_examples(state)
    repair_prompt = _truncate_text(state.metadata.get("repair_prompt", ""), max_chars=180)
    natural_instruction = "若用户指令偏泛化，请优先延续既有冲突与节奏，自然推进情节。"

    fragment_stats = state.metadata.get("chapter_fragment_stats", {}) or {}
    segment_plan = state.metadata.get("chapter_segment_plan", {}) or {}
    fragment_tail = _truncate_text(state.metadata.get("chapter_fragment_tail", ""), max_chars=320)
    domain_context = state.metadata.get("domain_context_sections", {}) or {}
    author_constraints_text = _truncate_text(domain_context.get("author_constraints", ""), max_chars=360)
    compressed_memory_text = _truncate_text(domain_context.get("compressed_memory", ""), max_chars=520)
    domain_character_text = _truncate_text(domain_context.get("character_cards", ""), max_chars=360)
    domain_plot_text = _truncate_text(domain_context.get("plot_threads", ""), max_chars=360)
    retrieved_plot_text = _truncate_text(domain_context.get("plot_evidence", ""), max_chars=900)
    retrieved_character_text = _truncate_text(domain_context.get("character_evidence", ""), max_chars=700)
    retrieved_world_text = _truncate_text(domain_context.get("world_evidence", ""), max_chars=700)
    retrieved_style_text = _truncate_text(domain_context.get("style_evidence", ""), max_chars=650)
    retrieved_scene_case_text = _truncate_text(domain_context.get("scene_case_evidence", ""), max_chars=520)
    round_no = int(state.metadata.get("chapter_loop_round", 1) or 1)
    fragment_count = int(fragment_stats.get("fragment_count", 0) or 0)
    written_chars = int(fragment_stats.get("written_chars", 0) or 0)
    target_chars = int(fragment_stats.get("target_chars", 0) or 0)
    remaining_chars = int(fragment_stats.get("remaining_chars", 0) or 0)
    target_min_chars = int(segment_plan.get("target_min_chars", 900) or 900)
    target_max_chars = int(segment_plan.get("target_max_chars", 1400) or 1400)
    hard_cap_chars = int(segment_plan.get("hard_cap_chars", 1800) or 1800)

    premise = _truncate_text(state.story.premise, max_chars=220)
    latest_summary = _truncate_text(state.chapter.latest_summary, max_chars=260)
    objective = _truncate_text(state.chapter.objective, max_chars=180)
    open_questions = _compact_lines(list(state.chapter.open_questions), max_items=5, max_item_chars=80)
    scene_cards = _compact_lines(list(state.chapter.scene_cards), max_items=5, max_item_chars=50)
    world_rules = _compact_lines(list(state.story.world_rules), max_items=8, max_item_chars=90)
    plot_memory = _compact_lines(list(state.memory.plot), max_items=4, max_item_chars=80)
    character_memory = _compact_lines(list(state.memory.character), max_items=4, max_item_chars=60)
    blocked_tropes = _compact_lines(list(state.preference.blocked_tropes), max_items=4, max_item_chars=30)
    rhetoric_preferences = _compact_lines(list(state.style.rhetoric_preferences), max_items=5, max_item_chars=24)
    forbidden_patterns = _compact_lines(list(state.style.forbidden_patterns), max_items=5, max_item_chars=30)

    segment_directive = (
        f"本轮是第 {round_no} 轮片段写作。"
        f" 当前已写约 {written_chars} 字，目标全章至少 {target_chars or target_min_chars} 字，"
        f" 尚需推进约 {remaining_chars} 字。"
        f" 本轮请只写一个连续片段，目标 {target_min_chars}-{target_max_chars} 字，"
        f" 不要超过 {hard_cap_chars} 字，不要重复已经写过的内容。"
    )
    if fragment_count > 0:
        segment_directive += " 直接承接“已写片段尾部”，继续往前推进。"
    else:
        segment_directive += " 这是本章首个片段，需要稳住起笔并建立本轮推进点。"

    user = (
        f"作品标题: {_truncate_text(state.story.title, max_chars=80)}\n"
        f"作品前提: {premise or '无'}\n"
        f"章节目标: {objective or '无'}\n"
        f"上章摘要: {latest_summary or '无'}\n"
        f"开放问题: {'; '.join(open_questions) if open_questions else '无'}\n"
        f"场景卡: {'; '.join(scene_cards) if scene_cards else '无'}\n"
        f"世界规则: {'; '.join(world_rules) if world_rules else '无'}\n"
        f"剧情推进点: {'; '.join(plot_memory) if plot_memory else '无'}\n"
        f"角色记忆: {'; '.join(character_memory) if character_memory else '无'}\n"
        f"风格约束: POV={state.style.narrative_pov}; 时态={state.style.tense}; "
        f"修辞偏好={'/'.join(rhetoric_preferences) if rhetoric_preferences else '无'}; "
        f"禁止模式={'/'.join(forbidden_patterns) if forbidden_patterns else '无'}\n"
        f"风格统计: 句长分布={json.dumps(state.style.sentence_length_distribution, ensure_ascii=False)}; "
        f"描写占比={json.dumps(state.style.description_mix, ensure_ascii=False)}\n"
        f"证据句配额样例: {style_examples_text}\n"
        f"事件样例: {case_examples_text}\n"
        f"作者约束: {author_constraints_text or '无'}\n"
        f"压缩记忆: {compressed_memory_text or '无'}\n"
        f"领域角色卡: {domain_character_text or '无'}\n"
        f"领域剧情线: {domain_plot_text or '无'}\n"
        f"检索剧情证据: {retrieved_plot_text or '无'}\n"
        f"检索人物证据: {retrieved_character_text or '无'}\n"
        f"检索世界观证据: {retrieved_world_text or '无'}\n"
        f"检索风格证据: {retrieved_style_text or '无'}\n"
        f"检索场景案例: {retrieved_scene_case_text or '无'}\n"
        f"已写片段尾部: {fragment_tail or '无'}\n"
        f"分段协议: {segment_directive}\n"
        f"修正提示: {repair_prompt or '无'}\n"
        f"续写原则: {natural_instruction}\n"
        f"用户偏好: 节奏={state.preference.pace}; 氛围={state.preference.preferred_mood}; "
        f"禁用桥段={'/'.join(blocked_tropes) if blocked_tropes else '无'}\n"
        f"当前请求: {_truncate_text(state.thread.user_input, max_chars=220)}\n"
        "写作要求:\n"
        "1. 只输出当前片段，不要重复前文，也不要总结整章。\n"
        "2. 片段必须是可直接拼接到章节中的正文，而不是提纲或说明。\n"
        "3. 若总目标很长，也只完成本轮配额，把悬念留给下一轮。\n"
        "4. continuity_notes 只记录本轮需要保持的连续性约束。\n"
        "5. 若作者约束存在，必须优先满足作者约束，不得触发禁止剧情点。\n"
        f"请按如下 schema 输出 JSON:\n{json.dumps(schema, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_extraction_messages(state: NovelAgentState) -> list[dict[str, str]]:
    system = compose_system_prompt(purpose="state_extraction").system_content
    schema = {
        "accepted_updates": [
            {
                "change_id": "string",
                "update_type": "event|world_fact|character_state|relationship|plot_progress|style_note|preference",
                "summary": "string",
                "details": "string",
                "stable_fact": True,
                "confidence": 0.0,
                "source_span": "string",
                "related_entities": [
                    {"entity_id": "string", "entity_type": "string", "name": "string"}
                ],
                "metadata": {},
            }
        ],
        "notes": ["string"],
    }
    existing_events = "; ".join(
        _truncate_text(event.summary, max_chars=80)
        for event in state.story.event_log[-5:]
        if _truncate_text(event.summary, max_chars=80)
    )
    world_rules = "; ".join(_compact_lines(list(state.story.world_rules), max_items=8, max_item_chars=70))
    user = (
        f"章节号: {state.chapter.chapter_number}\n"
        f"候选正文:\n{state.draft.content}\n\n"
        f"已有世界规则: {world_rules or '无'}\n"
        f"已有事件: {existing_events or '无'}\n"
        "请从候选正文中抽取新增的稳定状态更新，并严格按照下面的 schema 输出 JSON:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
