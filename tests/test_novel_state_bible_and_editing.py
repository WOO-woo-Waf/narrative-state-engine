from typer.testing import CliRunner

from narrative_state_engine.analysis import (
    AnalysisRunResult,
    CharacterCardAsset,
    ConceptSystemAsset,
    NovelStateBibleAsset,
    PlotThreadAsset,
    StoryBibleAsset,
)
from narrative_state_engine.analysis.merging import CharacterCanonicalizer
from narrative_state_engine.bootstrap import apply_analysis_to_state
from narrative_state_engine.cli import _sync_latest_analysis_into_state, app
from narrative_state_engine.domain import CharacterCard, RuleMechanism, StateEditEngine
from narrative_state_engine.models import NovelAgentState
from narrative_state_engine.storage.repository import InMemoryStoryStateRepository


def test_novel_state_bible_alias_keeps_story_bible_compatibility():
    bible = NovelStateBibleAsset(
        character_cards=[
            CharacterCardAsset(
                character_id="char-lin",
                name="林舟",
                identity_tags=["调查者"],
                stable_traits=["克制"],
                current_goals=["查明真相"],
                knowledge_boundary=["不知道幕后人"],
                decision_patterns=["先确认再行动"],
                status="confirmed",
            )
        ],
        system_ranks=[ConceptSystemAsset(concept_id="rank-001", name="筑基境", concept_type="system_rank")],
    )

    assert isinstance(bible, StoryBibleAsset)
    assert bible.character_cards[0].decision_patterns == ["先确认再行动"]
    assert bible.system_ranks[0].name == "筑基境"


def test_character_canonicalizer_filters_non_character_concepts_to_candidates():
    cards = [
        CharacterCardAsset(character_id="char-001", name="林舟", voice_profile=["克制"], confidence=0.9),
        CharacterCardAsset(character_id="char-002", name="灵根", confidence=0.9),
        CharacterCardAsset(character_id="char-003", name="筑基境", confidence=0.9),
    ]

    kept, candidates = CharacterCanonicalizer().canonicalize(cards, setting_terms=["灵根", "筑基境"])

    assert [item.name for item in kept] == ["林舟"]
    assert {item["name"] for item in candidates} == {"灵根", "筑基境"}


def test_state_edit_proposal_updates_character_style_world_and_locks_author_edits():
    state = NovelAgentState.demo("继续")
    state.domain.characters = [CharacterCard(character_id="char-lin", name="林舟")]
    engine = StateEditEngine()

    proposal = engine.propose(
        state,
        "林舟不擅长撒谎。风格减少解释性旁白。筑基之前不能御剑。",
    )
    confirmed = engine.confirm(state, proposal)

    assert confirmed.status == "confirmed"
    lin = state.domain.characters[0]
    assert lin.author_locked is True
    assert any("不擅长撒谎" in item for item in lin.stable_traits)
    assert state.domain.style_constraints
    assert any("筑基之前不能御剑" in item.definition for item in state.domain.rule_mechanisms)
    assert state.domain.rule_mechanisms[-1].author_locked is True
    assert confirmed.diff


def test_author_locked_domain_state_survives_later_analysis_mapping():
    state = NovelAgentState.demo("继续")
    state.domain.characters = [
        CharacterCard(
            character_id="char-lin",
            name="林舟",
            stable_traits=["作者锁定：不擅长撒谎"],
            author_locked=True,
            updated_by="author",
        )
    ]
    state.domain.rule_mechanisms = [
        RuleMechanism(
            concept_id="author-rule",
            name="御剑限制",
            definition="筑基之前不能御剑。",
            author_locked=True,
            updated_by="author",
        )
    ]
    analysis = AnalysisRunResult(
        analysis_version="analysis-edit-001",
        story_id=state.story.story_id,
        story_title=state.story.title,
        story_bible=StoryBibleAsset(
            character_cards=[
                CharacterCardAsset(
                    character_id="char-lin",
                    name="林舟",
                    stable_traits=["自动分析：擅长欺瞒"],
                    confidence=0.9,
                )
            ],
            rule_mechanisms=[
                ConceptSystemAsset(
                    concept_id="author-rule",
                    name="御剑限制",
                    definition="自动分析：可以御剑。",
                )
            ],
        ),
    )

    apply_analysis_to_state(state, analysis)

    lin = next(item for item in state.domain.characters if item.character_id == "char-lin")
    assert lin.stable_traits == ["作者锁定：不擅长撒谎"]
    mechanism = next(item for item in state.domain.rule_mechanisms if item.concept_id == "author-rule")
    assert mechanism.definition == "筑基之前不能御剑。"


def test_create_state_cli_initializes_author_editable_state_without_llm():
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "create-state",
            "主角林舟，风格短促克制。筑基之前不能御剑。",
            "--story-id",
            "story-cli-create",
            "--no-persist",
        ],
    )

    assert result.exit_code == 0
    assert "story-cli-create" in result.output
    assert "operation_count" in result.output


def test_edit_state_syncs_latest_analysis_before_author_edit():
    repo = InMemoryStoryStateRepository()
    state = NovelAgentState.demo("继续下一章。")
    state.story.story_id = "story-edit-sync"
    state.metadata["task_id"] = "task-edit-sync"
    repo.save(state)
    repo.save_analysis_assets(
        AnalysisRunResult(
            analysis_version="analysis-sync-001",
            story_id="story-edit-sync",
            story_title="Edit Sync",
            story_bible=StoryBibleAsset(
                character_cards=[CharacterCardAsset(character_id="char-lin", name="林舟", voice_profile=["克制"])],
                plot_threads=[
                    PlotThreadAsset(
                        thread_id="arc-analysis",
                        name="分析主线",
                        stakes="查明秘境异动",
                        anchor_events=["林舟确认秘境异动"],
                    )
                ],
            ),
            story_synopsis="分析基线摘要。",
            summary={"task_id": "task-edit-sync", "story_synopsis": "分析基线摘要。"},
        )
    )

    synced = _sync_latest_analysis_into_state(
        repository=repo,
        state=state,
        story_id="story-edit-sync",
        task_id="task-edit-sync",
    )

    assert synced is True
    assert any(item.name == "林舟" for item in state.story.characters)
    assert any(item.thread_id == "arc-analysis" for item in state.story.major_arcs)
