from narrative_state_engine.graph.workflow import run_pipeline
from narrative_state_engine.graph.nodes import TemplateDraftGenerator, plot_planner
from narrative_state_engine.models import (
    CommitStatus,
    NovelAgentState,
    UpdateType,
    ValidationStatus,
)


def test_pipeline_generates_structured_working_state():
    state = NovelAgentState.demo("继续下一章，保持设定一致并推进主线。")
    result = run_pipeline(state)

    assert result.validation.status in {
        ValidationStatus.PASSED,
        ValidationStatus.NEEDS_HUMAN_REVIEW,
    }
    assert result.commit.status in {
        CommitStatus.COMMITTED,
        CommitStatus.ROLLED_BACK,
    }
    assert result.thread.working_summary
    assert result.draft.content
    assert result.draft.planned_beat
    assert result.draft.style_targets
    assert result.draft.continuity_notes
    assert result.draft.raw_payload
    assert result.thread.pending_changes
    assert result.thread.pending_changes[0].update_type in {
        UpdateType.EVENT,
        UpdateType.PLOT_PROGRESS,
    }
    assert result.thread.pending_changes[0].summary


def test_pipeline_rolls_back_on_blocked_trope():
    state = NovelAgentState.demo("继续写第二章。")
    state.preference.blocked_tropes.append("新的细节浮出水面")
    result = run_pipeline(state, generator=TemplateDraftGenerator())

    assert result.validation.status == ValidationStatus.PASSED
    assert result.commit.status == CommitStatus.COMMITTED
    assert result.metadata.get("repair_attempts", 0) >= 1


def test_plot_planner_prefers_objective_over_demo_placeholder_arc():
    state = NovelAgentState.demo("续写下一章。")
    state.chapter.objective = "完成约三万字的一整章，并将女主的反差贯彻始终。"

    result = plot_planner(state, None)

    assert result.metadata["planned_beat"] == state.chapter.objective
    assert result.metadata.get("selected_plot_thread") is None
