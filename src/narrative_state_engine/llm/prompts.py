from __future__ import annotations

import json

from narrative_state_engine.models import NovelAgentState


def build_draft_messages(state: NovelAgentState) -> list[dict[str, str]]:
    system = (
        "你是小说续写系统中的 Draft Generator 节点。"
        "你必须严格遵守世界规则、角色知识边界、章节目标和风格约束。"
        "输出必须是 JSON 对象，不要输出任何额外说明。"
    )
    schema = {
        "content": "string, 章节正文",
        "rationale": "string, 本次推进理由",
        "planned_beat": "string, 本轮推进点",
        "style_targets": ["string"],
        "continuity_notes": ["string"],
    }
    user = (
        f"作品标题: {state.story.title}\n"
        f"作品前提: {state.story.premise}\n"
        f"章节目标: {state.chapter.objective}\n"
        f"上章摘要: {state.chapter.latest_summary}\n"
        f"开放问题: {'; '.join(state.chapter.open_questions)}\n"
        f"场景卡: {'; '.join(state.chapter.scene_cards)}\n"
        f"世界规则: {'; '.join(state.story.world_rules)}\n"
        f"剧情推进点: {'; '.join(state.memory.plot[:3])}\n"
        f"角色记忆: {'; '.join(state.memory.character[:3])}\n"
        f"风格约束: POV={state.style.narrative_pov}; 时态={state.style.tense}; "
        f"修辞偏好={'/'.join(state.style.rhetoric_preferences)}; "
        f"禁止模式={'/'.join(state.style.forbidden_patterns)}\n"
        f"用户偏好: 节奏={state.preference.pace}; 氛围={state.preference.preferred_mood}; "
        f"禁用桥段={'/'.join(state.preference.blocked_tropes)}\n"
        f"当前请求: {state.thread.user_input}\n"
        f"请按如下 schema 输出 JSON:\n{json.dumps(schema, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_extraction_messages(state: NovelAgentState) -> list[dict[str, str]]:
    system = (
        "你是小说续写系统中的 Information Extractor 节点。"
        "请从候选正文中抽取可以写入状态层的稳定更新。"
        "输出必须是 JSON 对象，不要输出任何额外说明。"
        "不要输出猜测性内容，不要输出纯风格评论。"
    )
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
    existing_events = "; ".join(event.summary for event in state.story.event_log[-5:])
    user = (
        f"章节号: {state.chapter.chapter_number}\n"
        f"正文:\n{state.draft.content}\n\n"
        f"已有世界规则: {'; '.join(state.story.world_rules)}\n"
        f"已有事件: {existing_events}\n"
        "请抽取新增状态，并按如下 schema 输出 JSON:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
