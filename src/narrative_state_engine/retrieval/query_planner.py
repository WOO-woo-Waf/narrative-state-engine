from __future__ import annotations

import re
from dataclasses import dataclass, field

CJK_SALIENT_MARKERS = (
    "角色",
    "人物",
    "剧情",
    "情节",
    "主线",
    "支线",
    "世界观",
    "世界",
    "风格",
    "伏笔",
    "线索",
    "联动",
    "冲突",
    "关系",
)


@dataclass(frozen=True)
class RetrievalQueryPlan:
    query_text: str
    semantic_query: str
    keyword_terms: list[str] = field(default_factory=list)
    entity_terms: list[str] = field(default_factory=list)
    evidence_types: list[str] = field(default_factory=list)


class NarrativeQueryPlanner:
    def plan(
        self,
        *,
        query_text: str,
        characters: list[str] | None = None,
        plot_threads: list[str] | None = None,
        evidence_types: list[str] | None = None,
    ) -> RetrievalQueryPlan:
        text = str(query_text or "").strip()
        character_terms = [item.strip() for item in characters or [] if item.strip()]
        plot_terms = [item.strip() for item in plot_threads or [] if item.strip()]
        keyword_terms = _keywords(" ".join([text, *character_terms, *plot_terms]))
        return RetrievalQueryPlan(
            query_text=text,
            semantic_query=" ".join([text, *character_terms, *plot_terms]).strip(),
            keyword_terms=keyword_terms,
            entity_terms=[*character_terms, *plot_terms],
            evidence_types=list(evidence_types or []),
        )


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        for term in _expand_token(token):
            if term in seen:
                continue
            seen.add(term)
            out.append(term)
            if len(out) >= 32:
                return out
    return out[:32]


def _expand_token(token: str) -> list[str]:
    if not _has_cjk(token):
        return [token]
    if len(token) <= 4:
        return [token]

    terms: list[str] = []
    if len(token) <= 12:
        terms.append(token)
    terms.extend(_salient_marker_terms(token))
    windows: list[tuple[int, str]] = []
    for size in (6, 5, 4, 3, 2):
        for index in range(0, len(token) - size + 1):
            term = token[index : index + size]
            if _is_low_signal_cjk_term(term):
                continue
            windows.append((index, term))
    salient = [item for item in windows if _is_salient_cjk_term(item[1])]
    ordinary = [item for item in windows if not _is_salient_cjk_term(item[1])]
    salient.sort(key=lambda item: (-len(item[1]), item[0]))
    ordinary.sort(key=lambda item: (-len(item[1]), item[0]))
    for _, term in [*salient, *ordinary]:
        if term in terms:
            continue
        terms.append(term)
        if len(terms) >= 16:
            return terms
    return terms


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _is_low_signal_cjk_term(term: str) -> bool:
    low_signal = {
        "一个",
        "这个",
        "那个",
        "自己",
        "什么",
        "怎么",
        "然后",
        "但是",
        "还是",
        "就是",
        "因为",
        "所以",
        "可以",
        "需要",
        "进行",
        "相关",
    }
    return term in low_signal


def _is_salient_cjk_term(term: str) -> bool:
    return any(marker in term for marker in CJK_SALIENT_MARKERS)


def _salient_marker_terms(token: str) -> list[str]:
    terms: list[str] = []
    for marker in CJK_SALIENT_MARKERS:
        start = token.find(marker)
        while start >= 0:
            left = max(0, start - 2)
            right = min(len(token), start + len(marker) + 2)
            for term in (token[left : start + len(marker)], token[start:right], token[left:right]):
                if len(term) >= 2 and term not in terms and not _is_low_signal_cjk_term(term):
                    terms.append(term)
            start = token.find(marker, start + 1)
    return terms[:12]
