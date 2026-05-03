from __future__ import annotations

import json
from typing import Any, Callable

from narrative_state_engine.domain.models import (
    AuthorConstraint,
    AuthorPlanningQuestion,
    AuthorPlanProposal,
    AuthorPlotPlan,
    ChapterBlueprint,
)
from narrative_state_engine.domain.planning import AuthorPlanningEngine
from narrative_state_engine.llm.client import unified_text_llm
from narrative_state_engine.llm.json_parsing import JsonBlobParser
from narrative_state_engine.llm.prompt_management import compose_system_prompt
from narrative_state_engine.models import NovelAgentState


AuthorPlanningLLMCall = Callable[[list[dict[str, str]], str], str]


class LLMAuthorPlanningEngine(AuthorPlanningEngine):
    def __init__(
        self,
        *,
        llm_call: AuthorPlanningLLMCall | None = None,
        fallback: AuthorPlanningEngine | None = None,
    ) -> None:
        self.llm_call = llm_call or _default_llm_call
        self.fallback = fallback or AuthorPlanningEngine()
        self.parser = JsonBlobParser()

    def propose(self, state: NovelAgentState, author_input: str) -> AuthorPlanProposal:
        fallback_proposal = self.fallback.propose(state, author_input)
        try:
            raw = self.llm_call(
                build_author_dialogue_planning_messages(
                    state=state,
                    author_input=author_input,
                    fallback_proposal=fallback_proposal,
                ),
                "author_dialogue_planning",
            )
            parsed = self.parser.parse(raw)
            if not parsed.ok or not isinstance(parsed.data, dict):
                raise ValueError(parsed.error)
            proposal = _proposal_from_payload(
                state=state,
                author_input=author_input,
                payload=dict(parsed.data),
                fallback=fallback_proposal,
            )
        except Exception as exc:
            fallback_proposal.rationale.append(f"LLM author planning fallback used: {exc}")
            return fallback_proposal

        state.domain.author_plan_proposals[-1] = proposal
        state.metadata["latest_author_plan_proposal_id"] = proposal.proposal_id
        return proposal


def build_author_dialogue_planning_messages(
    *,
    state: NovelAgentState,
    author_input: str,
    fallback_proposal: AuthorPlanProposal | None = None,
) -> list[dict[str, str]]:
    schema = {
        "author_goal": "string",
        "ending_direction": "string",
        "major_plot_spine": ["string"],
        "required_beats": ["string"],
        "forbidden_beats": ["string"],
        "pacing_target": "string",
        "chapter_goal": "string",
        "ending_hook": "string",
        "character_arc_plan": ["string"],
        "relationship_arc_plan": ["string"],
        "reveal_schedule": ["string"],
        "clarifying_questions": [
            {"question_type": "string", "question": "string", "reason": "string", "priority": "high|normal|low"}
        ],
        "retrieval_query_hints": {
            "semantic_query": "string",
            "required_beats": ["string"],
            "forbidden_beats": ["string"],
            "preferred_evidence": ["string"],
        },
        "rationale": ["string"],
    }
    context = {
        "story_id": state.story.story_id,
        "chapter_number": state.chapter.chapter_number,
        "chapter_objective": state.chapter.objective,
        "latest_summary": state.chapter.latest_summary,
        "open_questions": state.chapter.open_questions,
        "scene_cards": state.chapter.scene_cards,
        "characters": [
            {
                "character_id": item.character_id,
                "name": item.name,
                "goals": item.goals,
                "knowledge_boundary": item.knowledge_boundary,
            }
            for item in state.story.characters[:12]
        ],
        "plot_threads": [
            {
                "thread_id": item.thread_id,
                "name": item.name,
                "status": item.status,
                "stakes": item.stakes,
                "next_expected_beat": item.next_expected_beat,
            }
            for item in state.story.major_arcs[:12]
        ],
        "existing_author_constraints": [item.model_dump(mode="json") for item in state.domain.author_constraints],
        "retrieval_context": state.metadata.get("retrieval_context", {}),
        "author_dialogue_retrieval_context": state.metadata.get("author_dialogue_retrieval_context", {}),
        "fallback_rule_proposal": fallback_proposal.model_dump(mode="json") if fallback_proposal else {},
    }
    user = {
        "author_input": author_input,
        "context": context,
        "schema": schema,
    }
    return [
        {"role": "system", "content": compose_system_prompt(purpose="author_dialogue_planning").system_content},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]


def _proposal_from_payload(
    *,
    state: NovelAgentState,
    author_input: str,
    payload: dict[str, Any],
    fallback: AuthorPlanProposal,
) -> AuthorPlanProposal:
    required = _str_list(payload.get("required_beats")) or list(fallback.proposed_plan.required_beats)
    forbidden = _str_list(payload.get("forbidden_beats")) or list(fallback.proposed_plan.forbidden_beats)
    pacing_target = str(payload.get("pacing_target") or "")
    proposal_id = fallback.proposal_id
    constraints: list[AuthorConstraint] = []
    idx = 1
    for text in required:
        constraints.append(
            AuthorConstraint(
                constraint_id=f"{proposal_id}-llm-required-{idx:03d}",
                constraint_type="required_beat",
                text=text,
                status="candidate",
                violation_policy="warn",
                applies_to_chapters=[state.chapter.chapter_number],
            )
        )
        idx += 1
    for text in forbidden:
        constraints.append(
            AuthorConstraint(
                constraint_id=f"{proposal_id}-llm-forbidden-{idx:03d}",
                constraint_type="forbidden_beat",
                text=text,
                priority="high",
                status="candidate",
                violation_policy="block_commit",
                applies_to_chapters=[state.chapter.chapter_number],
            )
        )
        idx += 1
    if pacing_target:
        constraints.append(
            AuthorConstraint(
                constraint_id=f"{proposal_id}-llm-pacing-{idx:03d}",
                constraint_type="pacing_target",
                text=pacing_target,
                status="candidate",
                violation_policy="warn",
                applies_to_chapters=[state.chapter.chapter_number],
            )
        )

    plan = AuthorPlotPlan(
        plan_id=proposal_id,
        story_id=state.story.story_id,
        author_goal=str(payload.get("author_goal") or author_input)[:1200],
        ending_direction=str(payload.get("ending_direction") or ""),
        major_plot_spine=_str_list(payload.get("major_plot_spine")) or required,
        required_beats=required,
        forbidden_beats=forbidden,
        open_author_questions=[
            str(item.get("question", ""))
            for item in _dict_list(payload.get("clarifying_questions"))
            if str(item.get("question", "")).strip()
        ],
    )
    blueprint = ChapterBlueprint(
        blueprint_id=f"{proposal_id}-llm-chapter-{state.chapter.chapter_number}",
        chapter_index=state.chapter.chapter_number,
        chapter_goal=str(payload.get("chapter_goal") or (required[0] if required else state.chapter.objective)),
        required_beats=required,
        forbidden_beats=forbidden,
        pacing_target=pacing_target,
        ending_hook=str(payload.get("ending_hook") or ""),
    )
    questions = [
        AuthorPlanningQuestion(
            question_id=f"{proposal_id}-llm-question-{idx:03d}",
            question_type=str(item.get("question_type") or "planning"),
            question=str(item.get("question") or ""),
            reason=str(item.get("reason") or ""),
            priority=str(item.get("priority") or "normal"),
        )
        for idx, item in enumerate(_dict_list(payload.get("clarifying_questions")), start=1)
        if str(item.get("question") or "").strip()
    ]
    hints = dict(payload.get("retrieval_query_hints") or {})
    hints.setdefault("semantic_query", " ".join([author_input, *required, *forbidden])[:1200])
    hints.setdefault("required_beats", required)
    hints.setdefault("forbidden_beats", forbidden)
    hints.setdefault(
        "preferred_evidence",
        ["author_constraints", "plot_evidence", "character_evidence", "world_evidence", "style_evidence"],
    )
    return AuthorPlanProposal(
        proposal_id=proposal_id,
        story_id=state.story.story_id,
        raw_author_input=author_input,
        status="draft",
        proposed_plan=plan,
        proposed_constraints=constraints,
        proposed_chapter_blueprints=[blueprint],
        open_questions=[item.question for item in questions],
        clarifying_questions=questions,
        retrieval_query_hints=hints,
        rationale=_str_list(payload.get("rationale")) or ["LLM-assisted author planning generated a candidate plan."],
    )


def _default_llm_call(messages: list[dict[str, str]], purpose: str) -> str:
    return str(unified_text_llm(messages, purpose=purpose, json_mode=True))


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None or value == "":
        return []
    return [str(value).strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
