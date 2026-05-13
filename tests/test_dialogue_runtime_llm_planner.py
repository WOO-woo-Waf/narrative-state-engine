from __future__ import annotations

import json

from narrative_state_engine.domain.dialogue_llm_planner import DialogueLLMPlanner
from narrative_state_engine.domain.dialogue_runtime import DialogueRuntimeService
from narrative_state_engine.domain.state_objects import StateCandidateItemRecord, StateCandidateSetRecord
from narrative_state_engine.storage.audit import InMemoryAuditDraftRepository
from narrative_state_engine.storage.dialogue_runtime import InMemoryDialogueRuntimeRepository
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_dialogue_runtime_invokes_llm_and_creates_validated_audit_draft(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "1")
    service = _service_with_fake_llm(
        _repo_with_candidate(candidate_id="candidate-runtime", risk="low"),
        {
            "assistant_message": "已根据作者要求生成审计草稿。",
            "provenance": {"source": "llm", "model_name": "fake-dialogue-model", "fallback_used": False},
            "action_drafts": [
                {
                    "tool_name": "create_audit_action_draft",
                    "title": "接受低风险候选",
                    "summary": "接受当前低风险候选。",
                    "risk_level": "low",
                    "tool_params": {
                        "story_id": "story-runtime",
                        "task_id": "task-runtime",
                        "items": [
                            {
                                "candidate_item_id": "candidate-runtime",
                                "operation": "accept_candidate",
                                "reason": "作者要求通过当前正确候选。",
                            }
                        ],
                    },
                    "expected_effect": "等待作者确认后执行候选审计。",
                }
            ],
            "open_questions": [],
            "warnings": [],
        },
    )
    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="audit")

    response = service.append_message(thread["thread_id"], content="全部通过")

    assert response["runtime_mode"] == "llm"
    assert response["model_invoked"] is True
    assert response["llm_success"] is True
    assert response["draft_source"] == "llm"
    assert response["fallback_reason"] == ""
    assert response["drafts"][0]["metadata"]["draft_source"] == "llm"
    assert response["assistant_message"]["content"] == "已根据作者要求生成审计草稿。"
    events = service.runtime_repository.list_events(thread["thread_id"])
    assert any(event["event_type"] == "llm_call_started" for event in events)
    assert any(event["event_type"] == "llm_call_completed" for event in events)


def test_dialogue_runtime_llm_json_failure_uses_visible_backend_fallback(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "1")
    repo = _repo_with_candidate(candidate_id="candidate-runtime", risk="low")
    planner = DialogueLLMPlanner(llm_call=lambda _messages, _purpose: "{", model_name="fake-dialogue-model")
    service = DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=repo,
        audit_repository=InMemoryAuditDraftRepository(),
        llm_planner=planner,
    )
    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="audit")

    response = service.append_message(thread["thread_id"], content="帮我审计当前候选")

    assert response["runtime_mode"] == "backend_rule_fallback"
    assert response["model_invoked"] is True
    assert response["llm_success"] is False
    assert response["draft_source"] == "backend_rule_fallback"
    assert response["fallback_reason"] == "LLM_JSON_PARSE_ERROR"
    assert response["drafts"][0]["metadata"]["draft_source"] == "backend_rule_fallback"
    events = service.runtime_repository.list_events(thread["thread_id"])
    assert any(event["event_type"] == "llm_call_failed" for event in events)
    assert any(event["event_type"] == "fallback_used" for event in events)


def test_dialogue_runtime_reject_without_reason_falls_back_with_validation_marker(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "1")
    service = _service_with_fake_llm(
        _repo_with_candidate(candidate_id="candidate-runtime", risk="low"),
        {
            "assistant_message": "尝试拒绝候选。",
            "action_drafts": [
                {
                    "tool_name": "create_audit_action_draft",
                    "risk_level": "low",
                    "tool_params": {
                        "items": [
                            {
                                "candidate_item_id": "candidate-runtime",
                                "operation": "reject_candidate",
                            }
                        ]
                    },
                }
            ],
        },
    )
    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="audit")

    response = service.append_message(thread["thread_id"], content="帮我审计当前候选")

    assert response["runtime_mode"] == "backend_rule_fallback"
    assert response["fallback_reason"] == "LLM_ACTION_DRAFT_VALIDATION_ERROR"
    assert response["drafts"][0]["metadata"]["draft_source"] == "backend_rule_fallback"


def test_dialogue_runtime_high_risk_accept_from_llm_requires_high_risk_confirmation(monkeypatch):
    monkeypatch.setenv("NOVEL_AGENT_DIALOGUE_LLM_ENABLED", "1")
    service = _service_with_fake_llm(
        _repo_with_candidate(candidate_id="candidate-high", risk="high"),
        {
            "assistant_message": "高风险候选需要高风险确认。",
            "action_drafts": [
                {
                    "tool_name": "create_audit_action_draft",
                    "title": "接受主角状态候选",
                    "summary": "作者明确要求接受。",
                    "risk_level": "low",
                    "tool_params": {
                        "items": [
                            {
                                "candidate_item_id": "candidate-high",
                                "operation": "accept_candidate",
                                "reason": "作者明确要求主角相关候选通过。",
                            }
                        ]
                    },
                }
            ],
        },
    )
    thread = service.create_thread(story_id="story-runtime", task_id="task-runtime", scene_type="audit")

    response = service.append_message(thread["thread_id"], content="主角相关全部通过")

    assert response["runtime_mode"] == "llm"
    assert response["drafts"][0]["risk_level"] == "high"
    assert response["drafts"][0]["confirmation_policy"]["confirmation_text"] == "确认高风险写入"


def _service_with_fake_llm(repo: InMemoryStoryStateRepository, payload: dict) -> DialogueRuntimeService:
    planner = DialogueLLMPlanner(
        llm_call=lambda _messages, _purpose: json.dumps(payload, ensure_ascii=False),
        model_name="fake-dialogue-model",
    )
    return DialogueRuntimeService(
        runtime_repository=InMemoryDialogueRuntimeRepository(),
        state_repository=repo,
        audit_repository=InMemoryAuditDraftRepository(),
        llm_planner=planner,
    )


def _repo_with_candidate(*, candidate_id: str, risk: str) -> InMemoryStoryStateRepository:
    repo = InMemoryStoryStateRepository()
    object_type = "character" if risk == "high" else "location"
    confidence = 0.4 if risk == "high" else 0.92
    repo.save_state_candidate_records(
        [StateCandidateSetRecord(candidate_set_id="set-runtime", story_id="story-runtime", task_id="task-runtime", source_type="runtime-test")],
        [
            StateCandidateItemRecord(
                candidate_item_id=candidate_id,
                candidate_set_id="set-runtime",
                story_id="story-runtime",
                task_id="task-runtime",
                target_object_id=f"obj-{candidate_id}",
                target_object_type=object_type,
                field_path="summary",
                proposed_value="Candidate value.",
                source_role="primary_story",
                evidence_ids=["ev-runtime"],
                confidence=confidence,
            )
        ],
    )
    return repo
