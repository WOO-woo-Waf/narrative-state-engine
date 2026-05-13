from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from narrative_state_engine.domain.models import (
    CharacterCard,
    ChapterBlueprint,
    PlotThreadState,
    RuleMechanism,
    StyleConstraint,
    WorldRule,
)

if TYPE_CHECKING:
    from narrative_state_engine.models import NovelAgentState


class StateEditOperation(BaseModel):
    operation_id: str
    target_type: str
    target_id: str = ""
    field_path: str = ""
    action: str = "append"
    value: Any = None
    author_locked: bool = True
    status: str = "candidate"


class StateEditProposal(BaseModel):
    proposal_id: str
    story_id: str
    raw_author_input: str
    status: str = "draft"
    operations: list[StateEditOperation] = Field(default_factory=list)
    diff: list[dict[str, Any]] = Field(default_factory=list)
    clarifying_questions: list[dict[str, str]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: str = ""


class StateEditEngine:
    def propose(self, state: NovelAgentState, author_input: str) -> StateEditProposal:
        text = str(author_input or "").strip()
        proposal_id = f"state-edit-{state.story.story_id}-{len(state.domain.reports.get('state_edit_history', [])) + 1:03d}"
        operations = _operations_from_text(state, proposal_id, text)
        proposal = StateEditProposal(
            proposal_id=proposal_id,
            story_id=state.story.story_id,
            raw_author_input=text,
            operations=operations,
            diff=[_operation_diff(state, op) for op in operations],
            clarifying_questions=_clarifying_questions_for_edit(state, text, operations),
            open_questions=[],
            notes=[
                "Natural-language state edit parsed into candidate operations.",
                "Author-confirmed edits are marked author_locked and should not be overwritten by later analysis.",
            ],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        proposal.open_questions = [item["question"] for item in proposal.clarifying_questions]
        state.domain.reports["latest_state_edit_proposal"] = proposal.model_dump(mode="json")
        return proposal

    def confirm(self, state: NovelAgentState, proposal: StateEditProposal) -> StateEditProposal:
        confirmed = proposal.model_copy(deep=True)
        confirmed.status = "confirmed"
        confirmed.operations = [
            op.model_copy(update={"status": "confirmed", "author_locked": True})
            for op in confirmed.operations
        ]
        for op in confirmed.operations:
            _apply_operation(state, op, raw_author_input=proposal.raw_author_input)
        history = list(state.domain.reports.get("state_edit_history", []))
        history.append(confirmed.model_dump(mode="json"))
        state.domain.reports["state_edit_history"] = history[-100:]
        state.domain.reports["latest_state_edit_proposal"] = confirmed.model_dump(mode="json")
        return confirmed


def _operations_from_text(state: NovelAgentState, proposal_id: str, text: str) -> list[StateEditOperation]:
    operations: list[StateEditOperation] = []
    clauses = [item.strip() for item in re.split(r"[\n。；;]+", text) if item.strip()]
    for idx, clause in enumerate(clauses, start=1):
        op_id = f"{proposal_id}-op-{idx:03d}"
        character = _mentioned_character(state, clause)
        if character:
            field = _character_field_for_clause(clause)
            operations.append(
                StateEditOperation(
                    operation_id=op_id,
                    target_type="character",
                    target_id=character.character_id,
                    field_path=field,
                    value=_clean_edit_value(clause, character.name),
                )
            )
            continue
        if _is_style_clause(clause):
            operations.append(
                StateEditOperation(
                    operation_id=op_id,
                    target_type="style",
                    field_path="style_constraints",
                    value=clause,
                )
            )
            continue
        if _is_plot_clause(clause):
            operations.append(
                StateEditOperation(
                    operation_id=op_id,
                    target_type="plot_thread",
                    target_id=state.domain.plot_threads[0].thread_id if state.domain.plot_threads else "plot-author-main",
                    field_path="next_expected_beats",
                    value=clause,
                )
            )
            continue
        if _is_setting_clause(clause):
            operations.append(
                StateEditOperation(
                    operation_id=op_id,
                    target_type="rule_mechanism",
                    field_path="rules",
                    value=clause,
                )
            )
            continue
        if _is_chapter_clause(clause):
            operations.append(
                StateEditOperation(
                    operation_id=op_id,
                    target_type="chapter_blueprint",
                    target_id=f"chapter-{state.chapter.chapter_number}",
                    field_path="required_beats",
                    value=clause,
                )
            )
            continue
        operations.append(
            StateEditOperation(
                operation_id=op_id,
                target_type="world_rule",
                field_path="rule_text",
                value=clause,
            )
        )
    return operations


def _clarifying_questions_for_edit(
    state: NovelAgentState,
    text: str,
    operations: list[StateEditOperation],
) -> list[dict[str, str]]:
    questions: list[dict[str, str]] = []
    if not text.strip():
        questions.append(
            {
                "question_type": "empty_edit",
                "question": "你想修改哪个状态对象或哪个字段？",
                "reason": "没有收到可解析的作者修改意见。",
                "priority": "high",
            }
        )
        return questions
    if not operations:
        questions.append(
            {
                "question_type": "unparsed_edit",
                "question": "这条修改意见应该落到角色、关系、场景、世界规则、风格，还是章节蓝图？",
                "reason": "当前解析器没有生成明确的状态操作。",
                "priority": "high",
            }
        )
    fallback_world_rules = [op for op in operations if op.target_type == "world_rule"]
    if fallback_world_rules and len(fallback_world_rules) == len(operations):
        questions.append(
            {
                "question_type": "edit_scope",
                "question": "这些内容默认会作为世界规则/作者约束保存；是否其实应该写入某个角色卡、关系或章节规划？",
                "reason": "没有匹配到明确角色名、风格词、剧情线或章节词时，会进入较宽泛的 world_rule。",
                "priority": "normal",
            }
        )
    if state.domain.characters and not any(op.target_type == "character" for op in operations):
        questions.append(
            {
                "question_type": "character_scope",
                "question": "这次修改是否需要绑定到具体角色卡？如果需要，请写出角色名和字段。",
                "reason": "当前修改未命中已有角色名，可能无法落到角色卡字段。",
                "priority": "normal",
            }
        )
    return questions[:4]


def _operation_diff(state: NovelAgentState, op: StateEditOperation) -> dict[str, Any]:
    before: Any = None
    if op.target_type == "character":
        target = _find_character_by_id(state, op.target_id)
        before = list(getattr(target, op.field_path, [])) if target else None
    elif op.target_type == "style":
        before = [item.rule_text for item in state.domain.style_constraints]
    elif op.target_type == "world_rule":
        before = [item.rule_text for item in state.domain.world_rules]
    elif op.target_type == "rule_mechanism":
        before = [item.definition for item in state.domain.rule_mechanisms]
    return {
        "operation_id": op.operation_id,
        "target_type": op.target_type,
        "target_id": op.target_id,
        "field_path": op.field_path,
        "before": before,
        "after": op.value,
        "action": op.action,
    }


def _apply_operation(state: NovelAgentState, op: StateEditOperation, *, raw_author_input: str) -> None:
    revision = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": "author",
        "operation_id": op.operation_id,
        "raw_author_input": raw_author_input,
    }
    if op.target_type == "character":
        target = _find_character_by_id(state, op.target_id)
        if target is None:
            return
        values = getattr(target, op.field_path, [])
        if isinstance(values, list) and op.value not in values:
            values.append(str(op.value))
        target.updated_by = "author"
        target.author_locked = True
        target.status = "confirmed"
        target.revision_history.append(revision)
        return
    if op.target_type == "style":
        constraint_id = f"author-style-{len(state.domain.style_constraints) + 1:03d}"
        state.domain.style_constraints.append(
            StyleConstraint(
                constraint_id=constraint_id,
                constraint_type="author_style_rule",
                rule_text=str(op.value),
                severity="warning",
                source="author",
            )
        )
        if str(op.value) not in state.style.rhetoric_preferences:
            state.style.rhetoric_preferences.append(str(op.value))
        return
    if op.target_type == "plot_thread":
        if not state.domain.plot_threads:
            state.domain.plot_threads.append(
                PlotThreadState(thread_id=op.target_id, name="作者剧情线", status="open", updated_by="author", author_locked=True)
            )
        target = state.domain.plot_threads[0]
        if str(op.value) not in target.next_expected_beats:
            target.next_expected_beats.append(str(op.value))
        target.updated_by = "author"
        target.author_locked = True
        target.status = "confirmed"
        target.revision_history.append(revision)
        return
    if op.target_type == "chapter_blueprint":
        chapter_index = state.chapter.chapter_number
        blueprint = next((item for item in state.domain.chapter_blueprints if item.chapter_index == chapter_index), None)
        if blueprint is None:
            blueprint = ChapterBlueprint(
                blueprint_id=f"author-blueprint-{chapter_index}",
                chapter_index=chapter_index,
                chapter_goal=state.chapter.objective or str(op.value),
            )
            state.domain.chapter_blueprints.append(blueprint)
        if str(op.value) not in blueprint.required_beats:
            blueprint.required_beats.append(str(op.value))
        return
    if op.target_type == "rule_mechanism":
        state.domain.rule_mechanisms.append(
            RuleMechanism(
                concept_id=f"author-rule-mechanism-{len(state.domain.rule_mechanisms) + 1:03d}",
                name=_short_name(str(op.value)),
                definition=str(op.value),
                rules=[str(op.value)],
                limitations=[str(op.value)] if _contains_limitation(str(op.value)) else [],
                confidence=1.0,
                status="confirmed",
                source_type="author",
                updated_by="author",
                author_locked=True,
                revision_history=[revision],
            )
        )
        return
    if op.target_type == "world_rule":
        state.domain.world_rules.append(
            WorldRule(
                rule_id=f"author-world-rule-{len(state.domain.world_rules) + 1:03d}",
                rule_text=str(op.value),
                rule_type="author_constraint",
                confidence=1.0,
                status="confirmed",
                source_type="author",
                updated_by="author",
                author_locked=True,
                revision_history=[revision],
            )
        )
        if str(op.value) not in state.story.world_rules:
            state.story.world_rules.append(str(op.value))


def _mentioned_character(state: NovelAgentState, text: str) -> CharacterCard | None:
    for character in state.domain.characters:
        names = [character.name, *character.aliases]
        if any(name and name in text for name in names):
            return character
    for character in state.story.characters:
        if character.name and character.name in text:
            card = CharacterCard(character_id=character.character_id, name=character.name)
            state.domain.characters.append(card)
            return card
    return None


def _find_character_by_id(state: NovelAgentState, character_id: str) -> CharacterCard | None:
    return next((item for item in state.domain.characters if item.character_id == character_id), None)


def _character_field_for_clause(clause: str) -> str:
    if any(token in clause for token in ["台词", "说话", "口吻", "语气"]):
        return "voice_profile"
    if any(token in clause for token in ["不能", "不要", "不得", "禁区"]):
        return "forbidden_actions"
    if any(token in clause for token in ["害怕", "恐惧", "伤痕", "弱点"]):
        return "wounds_or_fears"
    if any(token in clause for token in ["决定", "选择", "判断"]):
        return "decision_patterns"
    if any(token in clause for token in ["目标", "想要"]):
        return "current_goals"
    return "stable_traits"


def _clean_edit_value(clause: str, name: str) -> str:
    return clause.replace(name, "").strip(" ，,：:。") or clause


def _is_style_clause(clause: str) -> bool:
    return any(token in clause for token in ["风格", "语气", "句子", "对话", "旁白", "描写", "节奏"])


def _is_plot_clause(clause: str) -> bool:
    return any(token in clause for token in ["剧情线", "主线", "支线", "伏笔", "揭示", "结局"])


def _is_chapter_clause(clause: str) -> bool:
    return any(token in clause for token in ["本章", "下一章", "这一章", "章节"])


def _is_setting_clause(clause: str) -> bool:
    return any(token in clause for token in ["体系", "境界", "筑基", "御剑", "灵根", "功法", "法术", "灵石", "丹药", "突破", "反噬", "代价", "契约"])


def _contains_limitation(text: str) -> bool:
    return any(token in text for token in ["不能", "不得", "不可", "不要", "代价", "反噬", "限制"])


def _short_name(text: str) -> str:
    match = re.search(r"[\u4e00-\u9fffA-Za-z0-9_]{2,16}", text)
    return match.group(0) if match else text[:16]
