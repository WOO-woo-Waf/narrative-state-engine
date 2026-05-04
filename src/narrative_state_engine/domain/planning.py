from __future__ import annotations

import re
from datetime import datetime, timezone

from narrative_state_engine.domain.models import (
    AuthorConstraint,
    AuthorIntent,
    AuthorPlanningQuestion,
    AuthorPlanProposal,
    AuthorPlotPlan,
    ChapterBlueprint,
    RuleMechanism,
    TerminologyEntry,
    WorldConcept,
)
from narrative_state_engine.models import NovelAgentState


_ENDING_TOKENS = ["\u7ed3\u5c40", "\u6700\u540e", "\u6700\u7ec8", "\u6536\u5c3e", "ending"]
_FORBIDDEN_TOKENS = [
    "\u4e0d\u8981\u8ba9",
    "\u4e0d\u80fd\u8ba9",
    "\u7981\u6b62\u8ba9",
    "\u4e0d\u8bb8\u8ba9",
    "\u4e0d\u8981",
    "\u4e0d\u80fd",
    "\u7981\u6b62",
    "\u522b\u8ba9",
    "\u4e0d\u8bb8",
    "forbid",
    "forbidden",
]
_FORESHADOWING_TOKENS = [
    "\u4f0f\u7b14",
    "\u94fa\u57ab",
    "\u7ebf\u7d22",
    "\u63ed\u9732",
    "\u89e3\u91ca",
    "\u56de\u6536",
    "foreshadow",
]
_RELATIONSHIP_TOKENS = [
    "\u5173\u7cfb",
    "\u5408\u4f5c",
    "\u51b3\u88c2",
    "\u548c\u597d",
    "\u4fe1\u4efb",
    "\u80cc\u53db",
    "relationship",
]
_CHARACTER_ARC_TOKENS = [
    "\u6210\u957f",
    "\u9010\u6e10",
    "\u53d8\u5f97",
    "\u4eba\u7269",
    "\u89d2\u8272",
    "\u6027\u683c",
    "character",
]
_CHAPTER_GOAL_TOKENS = [
    "\u4e0b\u4e00\u7ae0",
    "\u8fd9\u4e00\u7ae0",
    "\u672c\u7ae0",
    "\u5fc5\u987b",
    "\u9700\u8981",
    "\u8981",
    "\u53d1\u73b0",
    "\u627e\u5230",
    "\u63a8\u8fdb",
    "must",
    "chapter",
]
_PACING_TOKENS = [
    "\u8282\u594f",
    "\u538b\u6291",
    "\u8f7b\u677e",
    "\u7d27\u5f20",
    "\u6162",
    "\u5feb",
    "pacing",
]
_SETTING_TOKENS = [
    "\u4fee\u70bc",
    "\u4fee\u884c",
    "\u5883\u754c",
    "\u7b51\u57fa",
    "\u7075\u6839",
    "\u529f\u6cd5",
    "\u6cd5\u672f",
    "\u79d8\u672f",
    "\u7075\u77f3",
    "\u4e39\u836f",
    "\u7a81\u7834",
    "\u53cd\u566c",
    "\u4ee3\u4ef7",
    "\u5951\u7ea6",
    "\u4f53\u7cfb",
    "system",
    "rank",
    "skill",
    "resource",
]


class AuthorPlanningEngine:
    """Turns author input into candidate plans, then promotes confirmed plans."""

    def propose(self, state: NovelAgentState, author_input: str) -> AuthorPlanProposal:
        text = str(author_input or "").strip()
        story_id = state.story.story_id
        proposal_id = _proposal_id(story_id, len(state.domain.author_plan_proposals) + 1)
        intents = _extract_intents(proposal_id, text)
        constraints = _constraints_from_intents(proposal_id, intents, state.chapter.chapter_number)
        plan = _build_plan(state, proposal_id, text, constraints)
        blueprints = _build_chapter_blueprints(proposal_id, state, constraints)
        proposal = AuthorPlanProposal(
            proposal_id=proposal_id,
            story_id=story_id,
            raw_author_input=text,
            status="draft",
            proposed_plan=plan,
            proposed_constraints=constraints,
            proposed_chapter_blueprints=blueprints,
            open_questions=_open_questions_for(text, constraints),
            clarifying_questions=_clarifying_questions_for(proposal_id, state, text, constraints),
            retrieval_query_hints=_retrieval_query_hints_for(state, text, constraints, blueprints),
            rationale=[
                "Rule-based author planning converted the input into candidate intents, constraints, and chapter blueprints.",
                "Candidate content is not promoted into confirmed author constraints until confirm() is called.",
            ],
        )
        state.domain.author_intents.extend(intents)
        state.domain.author_plan_proposals.append(proposal)
        state.metadata["latest_author_plan_proposal_id"] = proposal_id
        return proposal

    def confirm(
        self,
        state: NovelAgentState,
        *,
        proposal_id: str | None = None,
    ) -> AuthorPlanProposal:
        proposal = _find_proposal(state, proposal_id)
        if proposal is None:
            raise ValueError("Author plan proposal not found.")

        confirmed = proposal.model_copy(deep=True)
        confirmed.status = "confirmed"
        confirmed.proposed_constraints = [
            item.model_copy(update={"status": "confirmed"})
            for item in confirmed.proposed_constraints
        ]
        confirmed.proposed_plan.story_id = state.story.story_id
        if not confirmed.proposed_plan.plan_id:
            confirmed.proposed_plan.plan_id = confirmed.proposal_id

        state.domain.author_plan = _merge_author_plan(state.domain.author_plan, confirmed.proposed_plan)
        state.domain.author_constraints = _merge_constraints(
            state.domain.author_constraints,
            confirmed.proposed_constraints,
        )
        state.domain.chapter_blueprints = _merge_blueprints(
            state.domain.chapter_blueprints,
            confirmed.proposed_chapter_blueprints,
        )
        _apply_setting_constraints(state, confirmed.proposed_constraints)

        for idx, item in enumerate(state.domain.author_plan_proposals):
            if item.proposal_id == proposal.proposal_id:
                state.domain.author_plan_proposals[idx] = confirmed
                break
        state.metadata["confirmed_author_plan_proposal_id"] = confirmed.proposal_id
        return confirmed


def _proposal_id(story_id: str, idx: int) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", story_id or "story").strip("-") or "story"
    return f"author-plan-{token}-{idx:03d}"


def _extract_intents(proposal_id: str, text: str) -> list[AuthorIntent]:
    clauses = _split_clauses(text)
    intents: list[AuthorIntent] = []
    for idx, clause in enumerate(clauses, start=1):
        intent_type = _intent_type_for_clause(clause)
        constraints = [clause] if clause else []
        uncertainty = []
        if intent_type == "general":
            uncertainty = ["The rule parser needs a clearer author intent category."]
        intents.append(
            AuthorIntent(
                intent_id=f"{proposal_id}-intent-{idx:03d}",
                raw_text=clause,
                intent_type=intent_type,
                extracted_constraints=constraints,
                uncertainty=uncertainty,
                requires_confirmation=True,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    if not intents and text:
        intents.append(
            AuthorIntent(
                intent_id=f"{proposal_id}-intent-001",
                raw_text=text,
                intent_type="general",
                extracted_constraints=[text],
                uncertainty=["No specific plot category was detected."],
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    return intents


def _split_clauses(text: str) -> list[str]:
    parts = re.split(r"[\n;；。！？!?，,]+", text)
    clauses = [_clean_clause(item) for item in parts]
    return [item for item in clauses if item]


def _clean_clause(text: str) -> str:
    clause = text.strip(" \t\r\n，,：:")
    clause = re.sub(r"^(?:\u4f46\u662f|\u4f46|\u7136\u540e|\u540c\u65f6)\s*", "", clause)
    return clause.strip(" \t\r\n，,：:")


def _intent_type_for_clause(clause: str) -> str:
    if _contains_any(clause, _ENDING_TOKENS):
        return "ending_direction"
    if _contains_any(clause, _SETTING_TOKENS):
        return "setting_system"
    if _contains_any(clause, _FORBIDDEN_TOKENS):
        return "forbidden_development"
    if _contains_any(clause, _FORESHADOWING_TOKENS):
        return "foreshadowing"
    if _contains_any(clause, _RELATIONSHIP_TOKENS):
        return "relationship_arc"
    if _contains_any(clause, _CHARACTER_ARC_TOKENS):
        return "character_arc"
    if _contains_any(clause, _CHAPTER_GOAL_TOKENS):
        return "chapter_goal"
    if _contains_any(clause, _PACING_TOKENS):
        return "pacing"
    return "general"


def _constraints_from_intents(
    proposal_id: str,
    intents: list[AuthorIntent],
    current_chapter: int,
) -> list[AuthorConstraint]:
    constraints: list[AuthorConstraint] = []
    for idx, intent in enumerate(intents, start=1):
        text = _constraint_text_for_intent(intent)
        if not text:
            continue
        constraint_type = _constraint_type_for_intent(intent.intent_type)
        policy = "block_commit" if constraint_type == "forbidden_beat" else "warn"
        applies_to = _chapters_from_text(text) or ([current_chapter] if intent.intent_type == "chapter_goal" else [])
        constraints.append(
            AuthorConstraint(
                constraint_id=f"{proposal_id}-constraint-{idx:03d}",
                constraint_type=constraint_type,
                text=text,
                priority="high" if policy == "block_commit" else "normal",
                status="candidate",
                applies_to_chapters=applies_to,
                violation_policy=policy,
            )
        )
    return constraints


def _constraint_text_for_intent(intent: AuthorIntent) -> str:
    text = intent.raw_text.strip()
    if intent.intent_type != "forbidden_development":
        return text
    for token in _FORBIDDEN_TOKENS:
        if token.isascii():
            continue
        text = re.sub(rf"^\s*{re.escape(token)}", "", text).strip(" ，,：:")
    return text or intent.raw_text.strip()


def _constraint_type_for_intent(intent_type: str) -> str:
    if intent_type == "forbidden_development":
        return "forbidden_beat"
    if intent_type in {"chapter_goal", "ending_direction", "foreshadowing", "character_arc", "relationship_arc"}:
        return "required_beat"
    if intent_type == "pacing":
        return "pacing_target"
    if intent_type == "setting_system":
        return "setting_system"
    return "general"


def _build_plan(
    state: NovelAgentState,
    proposal_id: str,
    raw_text: str,
    constraints: list[AuthorConstraint],
) -> AuthorPlotPlan:
    required = [item.text for item in constraints if item.constraint_type == "required_beat"]
    forbidden = [item.text for item in constraints if item.constraint_type == "forbidden_beat"]
    ending = _pick_clause(raw_text, _ENDING_TOKENS)
    return AuthorPlotPlan(
        plan_id=proposal_id,
        story_id=state.story.story_id,
        author_goal=raw_text[:600],
        ending_direction=ending,
        major_plot_spine=list(required[:12]),
        required_beats=required,
        forbidden_beats=forbidden,
        open_author_questions=[],
    )


def _build_chapter_blueprints(
    proposal_id: str,
    state: NovelAgentState,
    constraints: list[AuthorConstraint],
) -> list[ChapterBlueprint]:
    required = [item.text for item in constraints if item.constraint_type == "required_beat"]
    forbidden = [item.text for item in constraints if item.constraint_type == "forbidden_beat"]
    pacing = [item.text for item in constraints if item.constraint_type == "pacing_target"]
    if not required and not forbidden and not pacing:
        return []
    return [
        ChapterBlueprint(
            blueprint_id=f"{proposal_id}-chapter-{state.chapter.chapter_number}",
            chapter_index=state.chapter.chapter_number,
            chapter_goal=required[0] if required else state.chapter.objective,
            required_plot_threads=[item.thread_id for item in state.domain.plot_threads[:3]],
            required_beats=required,
            forbidden_beats=forbidden,
            pacing_target=pacing[0] if pacing else "",
            ending_hook="Keep a concrete unresolved tension for the next continuation round.",
        )
    ]


def _open_questions_for(text: str, constraints: list[AuthorConstraint]) -> list[str]:
    questions = []
    if text and not any(item.constraint_type == "required_beat" for item in constraints):
        questions.append("Should this author input define a required beat for the next chapter?")
    if "\u7ae0" in text and not re.search(r"\u7b2c\s*\d+\s*\u7ae0|\d+\s*\u7ae0", text):
        questions.append("A chapter-level intent was detected, but no exact chapter number was found.")
    return questions


def _clarifying_questions_for(
    proposal_id: str,
    state: NovelAgentState,
    text: str,
    constraints: list[AuthorConstraint],
) -> list[AuthorPlanningQuestion]:
    questions: list[AuthorPlanningQuestion] = []
    if not any(item.constraint_type == "required_beat" for item in constraints):
        questions.append(
            AuthorPlanningQuestion(
                question_id=f"{proposal_id}-question-required-beat",
                question_type="required_beat",
                question="下一段或下一章必须发生的核心剧情节点是什么？",
                reason="没有检测到明确的 required beat，自动写作会缺少硬目标。",
                priority="high",
            )
        )
    if not any(item.constraint_type == "forbidden_beat" for item in constraints):
        questions.append(
            AuthorPlanningQuestion(
                question_id=f"{proposal_id}-question-forbidden-beat",
                question_type="forbidden_beat",
                question="哪些发展绝对不能发生，或者发生就必须回滚？",
                reason="禁用发展用于阻止模型把剧情写向作者不想要的方向。",
                priority="high",
            )
        )
    if state.domain.characters and not _mentions_any_character(text, state):
        questions.append(
            AuthorPlanningQuestion(
                question_id=f"{proposal_id}-question-character-focus",
                question_type="character_focus",
                question="这一轮重点人物是谁？他们之间希望产生什么关系变化？",
                reason="人物焦点会影响角色卡、关系状态和原文片段的检索路由。",
                applies_to=[item.character_id for item in state.domain.characters[:6]],
            )
        )
    if not any(item.constraint_type == "pacing_target" for item in constraints):
        questions.append(
            AuthorPlanningQuestion(
                question_id=f"{proposal_id}-question-pacing",
                question_type="pacing",
                question="这一段节奏希望更偏铺垫、对峙、爆发，还是收束？",
                reason="节奏目标会影响场景案例、风格片段和章节蓝图。",
            )
        )
    return questions[:6]


def _retrieval_query_hints_for(
    state: NovelAgentState,
    text: str,
    constraints: list[AuthorConstraint],
    blueprints: list[ChapterBlueprint],
) -> dict:
    required = [item.text for item in constraints if item.constraint_type == "required_beat"]
    forbidden = [item.text for item in constraints if item.constraint_type == "forbidden_beat"]
    pacing = [item.text for item in constraints if item.constraint_type == "pacing_target"]
    blueprint = blueprints[0] if blueprints else None
    return {
        "semantic_query": " ".join(
            item
            for item in [
                text,
                " ".join(required[:6]),
                " ".join(forbidden[:4]),
                blueprint.chapter_goal if blueprint else "",
                state.chapter.objective,
            ]
            if item
        )[:1200],
        "required_beats": required,
        "forbidden_beats": forbidden,
        "pacing_targets": pacing,
        "target_chapter_index": state.chapter.chapter_number,
        "preferred_evidence": [
            "author_constraints",
            "compressed_memory",
            "plot_evidence",
            "character_evidence",
            "style_evidence",
            "scene_case_evidence",
        ],
    }


def _mentions_any_character(text: str, state: NovelAgentState) -> bool:
    names = []
    names.extend(character.name for character in state.domain.characters)
    names.extend(character.name for character in state.story.characters)
    return any(name and name in text for name in names)


def _pick_clause(text: str, markers: list[str]) -> str:
    for clause in _split_clauses(text):
        if _contains_any(clause, markers):
            return clause
    return ""


def _chapters_from_text(text: str) -> list[int]:
    chapters: list[int] = []
    for match in re.finditer(r"(?:\u7b2c\s*)?(\d+)\s*\u7ae0", text):
        chapters.append(int(match.group(1)))
    return sorted(set(chapters))


def _contains_any(text: str, tokens: list[str]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens)


def _find_proposal(state: NovelAgentState, proposal_id: str | None) -> AuthorPlanProposal | None:
    if proposal_id:
        for proposal in state.domain.author_plan_proposals:
            if proposal.proposal_id == proposal_id:
                return proposal
        return None
    if state.domain.author_plan_proposals:
        return state.domain.author_plan_proposals[-1]
    return None


def _merge_author_plan(existing: AuthorPlotPlan, incoming: AuthorPlotPlan) -> AuthorPlotPlan:
    if not existing.plan_id:
        return incoming
    merged = existing.model_copy(deep=True)
    if incoming.author_goal:
        merged.author_goal = incoming.author_goal
    if incoming.ending_direction:
        merged.ending_direction = incoming.ending_direction
    merged.major_plot_spine = _merge_list(merged.major_plot_spine, incoming.major_plot_spine)
    merged.required_beats = _merge_list(merged.required_beats, incoming.required_beats)
    merged.forbidden_beats = _merge_list(merged.forbidden_beats, incoming.forbidden_beats)
    merged.character_arc_plan_ids = _merge_list(merged.character_arc_plan_ids, incoming.character_arc_plan_ids)
    merged.relationship_arc_plan_ids = _merge_list(merged.relationship_arc_plan_ids, incoming.relationship_arc_plan_ids)
    merged.foreshadowing_plan_ids = _merge_list(merged.foreshadowing_plan_ids, incoming.foreshadowing_plan_ids)
    merged.reveal_schedule_ids = _merge_list(merged.reveal_schedule_ids, incoming.reveal_schedule_ids)
    merged.open_author_questions = _merge_list(merged.open_author_questions, incoming.open_author_questions)
    return merged


def _merge_constraints(
    existing: list[AuthorConstraint],
    incoming: list[AuthorConstraint],
) -> list[AuthorConstraint]:
    rows = {item.constraint_id: item for item in existing}
    for item in incoming:
        rows[item.constraint_id] = item
    return list(rows.values())


def _merge_blueprints(
    existing: list[ChapterBlueprint],
    incoming: list[ChapterBlueprint],
) -> list[ChapterBlueprint]:
    rows = {item.blueprint_id: item for item in existing}
    for item in incoming:
        rows[item.blueprint_id] = item
    return list(rows.values())


def _merge_list(left: list[str], right: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in [*left, *right]:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _apply_setting_constraints(state: NovelAgentState, constraints: list[AuthorConstraint]) -> None:
    for constraint in constraints:
        if constraint.status != "confirmed" or constraint.constraint_type != "setting_system":
            continue
        text = constraint.text.strip()
        if not text:
            continue
        concept_id = f"{constraint.constraint_id}-setting"
        if any(token in text for token in ["不能", "不得", "不可", "必须", "突破", "反噬", "代价", "限制", "条件"]):
            if not any(item.concept_id == concept_id for item in state.domain.rule_mechanisms):
                state.domain.rule_mechanisms.append(
                    RuleMechanism(
                        concept_id=concept_id,
                        name=_setting_name_from_text(text),
                        definition=text,
                        rules=[text],
                        limitations=[text] if any(token in text for token in ["不能", "不得", "不可", "反噬", "代价", "限制"]) else [],
                        confidence=1.0,
                        status="confirmed",
                        author_locked=True,
                    )
                )
            continue
        if any(token in text for token in ["灵根", "命格", "契约", "血脉", "道心", "体系"]):
            if not any(item.concept_id == concept_id for item in state.domain.world_concepts):
                state.domain.world_concepts.append(
                    WorldConcept(
                        concept_id=concept_id,
                        name=_setting_name_from_text(text),
                        definition=text,
                        rules=[text],
                        confidence=1.0,
                        status="confirmed",
                        author_locked=True,
                    )
                )
            continue
        if not any(item.concept_id == concept_id for item in state.domain.terminology):
            state.domain.terminology.append(
                TerminologyEntry(
                    concept_id=concept_id,
                    name=_setting_name_from_text(text),
                    definition=text,
                    confidence=1.0,
                    status="confirmed",
                    author_locked=True,
                )
            )


def _setting_name_from_text(text: str) -> str:
    match = re.search(r"[\u4e00-\u9fffA-Za-z0-9_]{2,12}(?:体系|境|阶|级|品|灵根|功法|法术|秘术|灵石|丹药|规则|条件|代价|反噬|契约)", text)
    if match:
        return match.group(0)
    return text[:16]
