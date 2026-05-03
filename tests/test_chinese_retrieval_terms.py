from narrative_state_engine.retrieval.hybrid_search import (
    _keyword_substring_terms,
    _keyword_term_weight,
)
from narrative_state_engine.retrieval.query_planner import NarrativeQueryPlanner


def test_query_planner_expands_long_chinese_story_query_into_recall_terms():
    plan = NarrativeQueryPlanner().plan(
        query_text="继续推进共享世界观中的角色联动和下一段剧情"
    )

    assert "共享世界观" in plan.keyword_terms
    assert "角色联动" in plan.keyword_terms
    assert any("剧情" in term for term in plan.keyword_terms)
    assert len(plan.keyword_terms) <= 32


def test_keyword_substring_terms_keep_stable_order_and_filter_duplicates():
    terms = _keyword_substring_terms(["角色联动", "角色联动", "世界观", "", "a", "剧情推进"])

    assert terms == ["角色联动", "世界观", "剧情推进"]


def test_keyword_substring_terms_drop_overly_generic_short_terms():
    terms = _keyword_substring_terms(["同作者风格", "作者", "风格", "角色", "角色联动", "世界观"])

    assert terms == ["同作者风格", "角色联动", "世界观"]


def test_keyword_substring_terms_drop_generic_terms_when_no_specific_anchor_exists():
    terms = _keyword_substring_terms(["角色", "剧情", "主线", "风格", "作者"])

    assert terms == []


def test_keyword_term_weight_prefers_earlier_and_longer_terms():
    early_long = _keyword_term_weight(term="角色联动", rank=0)
    late_short = _keyword_term_weight(term="剧情", rank=12)

    assert early_long > late_short
