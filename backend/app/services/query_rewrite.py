from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.document_enrichment import clean_text_for_retrieval, extract_formulas


QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "怎么",
    "如何",
    "为什么",
    "一下",
    "讲解",
    "说明",
}

FORMULA_QUERY_STOPWORDS = {
    "begin",
    "cdot",
    "dfrac",
    "displaystyle",
    "end",
    "frac",
    "left",
    "right",
    "text",
}


@dataclass(frozen=True)
class QueryPlan:
    semantic_query: str
    lexical_terms: list[str]
    formula_terms: list[str]


def rewrite_query(query: str) -> QueryPlan:
    """Split a user query into semantic, lexical, and formula-facing signals."""

    formulas = extract_formulas(query)
    semantic_query = clean_text_for_retrieval(query) or query.strip()
    lexical_terms = tokenize_for_lexical(semantic_query)
    formula_terms = formula_tokens(query, formulas)
    return QueryPlan(
        semantic_query=semantic_query,
        lexical_terms=_dedupe(lexical_terms)[:24],
        formula_terms=_dedupe(formula_terms)[:24],
    )


def tokenize_for_lexical(text: str) -> list[str]:
    """Tokenize mixed Chinese/English/math text for lightweight BM25 scoring."""

    lowered = text.lower()
    tokens: list[str] = []
    tokens.extend(
        token
        for token in re.findall(r"[a-z][a-z0-9-]{1,}|[0-9]+(?:\.[0-9]+)?", lowered)
        if token not in QUERY_STOPWORDS
    )
    for block in re.findall(r"[\u4e00-\u9fff]{2,16}", text):
        if block in QUERY_STOPWORDS:
            continue
        tokens.append(block)
        if len(block) > 4:
            tokens.extend(block[index : index + 2] for index in range(len(block) - 1))
            tokens.extend(block[index : index + 3] for index in range(len(block) - 2))
    return _dedupe(tokens)


def formula_tokens(text: str, formulas: list[str] | None = None) -> list[str]:
    """Extract exact-ish formula tokens without promoting LaTeX command words."""

    sources = [text, *(formulas or [])]
    tokens: list[str] = []
    for source in sources:
        normalized = source.replace("\\", " ")
        tokens.extend(
            token.lower()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9]*|[0-9]+(?:\.[0-9]+)?", normalized)
            if token.lower() not in FORMULA_QUERY_STOPWORDS
        )
        tokens.extend(re.findall(r"[=+\-*/^_(){}\[\],]", source))
    return _dedupe(tokens)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
