from __future__ import annotations

from collections import Counter
import re
from typing import Any, TypedDict

from app.agents.llm import DeepSeekClient
from app.core.config import get_settings


LATEX_COMMAND_WORDS = {
    "begin",
    "binom",
    "cdot",
    "cos",
    "cot",
    "csc",
    "det",
    "displaystyle",
    "dfrac",
    "end",
    "exp",
    "frac",
    "hline",
    "left",
    "max",
    "min",
    "mathrm",
    "qquad",
    "quad",
    "right",
    "sec",
    "sin",
    "tan",
    "text",
    "times",
    "to",
    "vec",
}

LATEX_COMMAND_REPLACEMENTS = {
    "alpha": "alpha",
    "beta": "beta",
    "delta": "delta",
    "Delta": "Delta",
    "epsilon": "epsilon",
    "frac": "fraction",
    "gamma": "gamma",
    "Gamma": "Gamma",
    "ge": "greater than or equal",
    "geq": "greater than or equal",
    "infty": "infinity",
    "int": "integral",
    "lambda": "lambda",
    "Lambda": "Lambda",
    "le": "less than or equal",
    "leq": "less than or equal",
    "lim": "limit",
    "ln": "logarithm",
    "log": "logarithm",
    "mu": "mu",
    "nabla": "gradient",
    "neq": "not equal",
    "omega": "omega",
    "Omega": "Omega",
    "partial": "partial derivative",
    "phi": "phi",
    "pi": "pi",
    "prod": "product",
    "sigma": "sigma",
    "Sigma": "Sigma",
    "sqrt": "square root",
    "sum": "summation",
    "theta": "theta",
    "Theta": "Theta",
}

TERM_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "left",
    "right",
    "that",
    "the",
    "there",
    "this",
    "to",
    "with",
}

FORMULA_HARD_TERM_STOPWORDS = {
    "dx",
    "dy",
    "dz",
    "fraction",
    "over",
    "power",
    "subscript",
    "superscript",
}

FORMULA_STANDALONE_TERM_STOPWORDS = FORMULA_HARD_TERM_STOPWORDS | {
    "derivative",
    "gradient",
    "integral",
    "limit",
    "partial",
    "root",
    "square",
    "summation",
}

KEY_TERM_NOISE_WORDS = (
    {word.lower() for word in LATEX_COMMAND_WORDS}
    | {word.lower() for word in LATEX_COMMAND_REPLACEMENTS}
    | {"dt", "formula", "formulae"}
)

MATH_SYMBOL_CHARS = "=^_+-*/<>|" + "".join(
    chr(code)
    for code in (
        0x222B,  # integral
        0x221A,  # square root
        0x221E,  # infinity
        0x2264,  # less-than or equal
        0x2265,  # greater-than or equal
        0x2260,  # not equal
        0x2248,  # almost equal
        0x2211,  # summation
        0x220F,  # product
        0x2202,  # partial derivative
        0x2206,  # increment
        0x2207,  # nabla
        0x00B1,  # plus-minus
        0x00D7,  # multiplication
        0x00F7,  # division
    )
)
MATH_SYMBOL_RE = re.compile("[" + re.escape(MATH_SYMBOL_CHARS) + "]")

FORMULA_SPAN_PATTERNS = [
    r"\$\$.*?\$\$",
    r"\\\[.*?\\\]",
    r"\\\(.*?\\\)",
    r"\$[^$\n]{2,400}\$",
]

MAX_KEY_TERMS = 5

MATH_CONCEPT_TERMS: dict[str, tuple[str, float]] = {
    "\u6b63\u9879\u7ea7\u6570": ("concept", 2.4),
    "\u6536\u655b\u7ea7\u6570": ("concept", 2.3),
    "\u53d1\u6563\u7ea7\u6570": ("concept", 2.3),
    "\u5e42\u7ea7\u6570": ("concept", 2.1),
    "\u7ea7\u6570": ("concept", 1.8),
    "\u6536\u655b": ("concept", 1.7),
    "\u53d1\u6563": ("concept", 1.7),
    "\u90e8\u5206\u548c": ("concept", 2.1),
    "\u901a\u9879": ("concept", 1.6),
    "\u6bd4\u8f83\u5224\u522b\u6cd5": ("method", 2.5),
    "\u6bd4\u503c\u5224\u522b\u6cd5": ("method", 2.4),
    "\u6839\u503c\u5224\u522b\u6cd5": ("method", 2.4),
    "\u5224\u522b\u6cd5": ("method", 1.8),
    "\u6781\u9650": ("concept", 1.8),
    "\u5bfc\u6570": ("concept", 1.8),
    "\u504f\u5bfc\u6570": ("concept", 2.0),
    "\u79ef\u5206": ("concept", 1.8),
    "\u66f2\u7ebf\u79ef\u5206": ("concept", 2.3),
    "\u5fae\u5206": ("concept", 1.7),
    "\u77e9\u9635": ("concept", 1.8),
    "\u7279\u5f81\u503c": ("concept", 2.2),
    "\u6982\u7387": ("concept", 1.8),
    "\u65b9\u5dee": ("concept", 1.8),
    "line integral": ("concept", 2.3),
    "partial derivative": ("concept", 2.3),
}

CHINESE_TERM_NOISE = {
    "\u5176\u90e8\u5206\u548c\u4e3a",
    "\u90e8\u5206\u548c\u4e3a",
    "\u548c\u4e3a",
    "\u4e3a",
    "\u8fd9\u5c31\u8868\u660e",
    "\u8fd9\u8868\u660e",
    "\u53ef\u89c1",
    "\u56e0\u6b64",
    "\u6240\u4ee5",
    "\u5176\u4e2d",
    "\u8fd9\u65f6",
    "\u4e0b\u9762",
    "\u4e0a\u9762",
}

CHINESE_TERM_NOISE_RE = re.compile(
    "|".join(re.escape(item) for item in sorted(CHINESE_TERM_NOISE, key=len, reverse=True))
)


class EnrichedChunk(TypedDict):
    """增强后的文档 chunk。

    `content` 保留原文，`embedding_text` 用于写入 Chroma 检索。
    对英文资料来说，embedding_text 会包含原文、中文摘要和中英术语，
    从而提升中文查询命中英文教材片段的概率。
    """

    content: str
    content_raw: str
    retrieval_text: str
    embedding_text: str
    formulas: list[str]
    source_lang: str
    summary_zh: str
    key_terms: list[dict[str, Any]]


async def enrich_chunks(chunks: list[str], filename: str) -> list[EnrichedChunk]:
    """批量增强文档 chunk。

    有 DeepSeek API Key 时，前若干个 chunk 会调用模型生成更准确的中文摘要
    和术语表；未配置 Key 或模型失败时，使用本地启发式规则兜底。
    """

    settings = get_settings()
    llm = DeepSeekClient()
    enriched: list[EnrichedChunk] = []

    for index, chunk in enumerate(chunks):
        formulas = extract_formulas(chunk)
        retrieval_text = clean_text_for_retrieval(chunk)
        fallback = _fallback_enrichment(retrieval_text)

        if settings.deepseek_api_key and index < settings.rag_enrich_max_chunks:
            result = await llm.complete_json(
                system_prompt=(
                    "你是课程资料 RAG 预处理助手。请分析一个课程文档片段，"
                    "识别语言，生成中文摘要，并抽取中英术语对。必须返回 JSON。"
                    "key_terms 只能包含课程概念、定理、方法、章节术语；不要把 LaTeX 命令、"
                    "单个变量名、公式片段、页码或排版符号当作术语。"
                ),
                user_payload={
                    "filename": filename,
                    "chunk_index": index,
                    "content": retrieval_text[:4000],
                    "schema": {
                        "source_lang": "en|zh|mixed|unknown",
                        "summary_zh": "用中文概括这个片段的核心内容",
                        "key_terms": [
                            {
                                "source": "process scheduling",
                                "zh": "进程调度",
                                "kind": "concept|method|theorem|chapter|term",
                                "confidence": 0.8,
                            }
                        ],
                    },
                },
                fallback=fallback,
            )
            normalized = _normalize_enrichment(
                chunk, retrieval_text, formulas, result, fallback
            )
        else:
            normalized = _normalize_enrichment(
                chunk, retrieval_text, formulas, fallback, fallback
            )

        enriched.append(normalized)

    return enriched


def _fallback_enrichment(content: str) -> dict[str, Any]:
    """在没有 LLM 时生成稳定的 chunk 增强信息。"""

    source_lang = detect_language(content)
    terms = _extract_terms(content)
    if source_lang == "en":
        term_text = "、".join(term["source"] for term in terms[:5]) or "核心概念"
        summary = f"该英文片段主要围绕 {term_text} 等概念展开。"
    elif source_lang == "zh":
        summary = _shorten_zh(content)
    else:
        summary = _shorten_zh(content)
    return {
        "source_lang": source_lang,
        "summary_zh": summary,
        "key_terms": terms,
    }


def _normalize_enrichment(
    content: str,
    retrieval_text: str,
    formulas: list[str],
    raw: dict[str, Any],
    fallback: dict[str, Any],
) -> EnrichedChunk:
    """校验模型输出，并生成最终写入 Chroma 的增强文本。"""

    source_lang = str(raw.get("source_lang") or fallback["source_lang"])[:20]
    summary_zh = str(raw.get("summary_zh") or fallback["summary_zh"]).strip()
    raw_terms = raw.get("key_terms") if raw is not fallback else []
    key_terms = _normalize_terms(raw_terms, fallback["key_terms"])
    term_lines = [
        f"{item['source']} = {item['zh']}"
        for item in key_terms
        if item.get("source") or item.get("zh")
    ]
    formula_line = "Formulae: " + " ; ".join(formulas[:5]) if formulas else ""

    embedding_text = "\n".join(
        item
        for item in [
            retrieval_text or content,
            formula_line,
            f"中文摘要：{summary_zh}" if summary_zh else "",
            "核心术语：" + "；".join(term_lines) if term_lines else "",
        ]
        if item
    )

    return {
        "content": content,
        "content_raw": content,
        "retrieval_text": retrieval_text,
        "embedding_text": embedding_text,
        "formulas": formulas,
        "source_lang": source_lang,
        "summary_zh": summary_zh,
        "key_terms": key_terms,
    }


def detect_language(text: str) -> str:
    """用字符比例粗略判断 chunk 语言。"""

    english_letters = len(re.findall(r"[A-Za-z]", text))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    if english_letters == 0 and chinese_chars == 0:
        return "unknown"
    if english_letters > chinese_chars * 2:
        return "en"
    if chinese_chars > english_letters:
        return "zh"
    return "mixed"


def _extract_terms(text: str) -> list[dict[str, Any]]:
    """Extract a small, high-precision term list for local fallback tagging."""

    cleaned_text = clean_text_for_retrieval(text)
    candidates: dict[str, dict[str, Any]] = {}

    def add_candidate(
        value: str,
        *,
        score: float = 1.0,
        kind: str | None = None,
        term_source: str = "local",
    ) -> None:
        term = clean_key_term(value)
        if not is_valid_key_term(term):
            return
        inferred_kind, bonus = _term_kind_and_bonus(term)
        final_kind = kind or inferred_kind
        final_score = score + bonus
        identity = _term_identity(term, term)
        existing = candidates.get(identity)
        if existing and float(existing.get("_score") or 0.0) >= final_score:
            return
        confidence = min(0.95, 0.48 + final_score / 6.0)
        candidates[identity] = {
            "source": term[:80],
            "zh": term[:80] if _is_chinese_text(term) else "",
            "kind": final_kind,
            "confidence": round(confidence, 3),
            "term_source": term_source,
            "_score": final_score,
        }

    lowered_text = cleaned_text.lower()
    for concept, (kind, score) in MATH_CONCEPT_TERMS.items():
        source = lowered_text if concept.isascii() else cleaned_text
        if concept in source:
            add_candidate(concept, score=score + 1.0, kind=kind)

    english_counter = Counter(
        clean_key_term(match.group(0))
        for match in re.finditer(
            r"\b[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,2}\b",
            cleaned_text,
        )
    )
    for term, count in english_counter.items():
        words = re.findall(r"[A-Za-z]+", term)
        score = 0.7 + min(count, 4) * 0.25 + min(len(words), 3) * 0.15
        add_candidate(term, score=score)

    for block in re.findall(r"[\u4e00-\u9fff]{2,24}", cleaned_text):
        for term in _chinese_concept_candidates(block):
            add_candidate(term, score=1.0)

    return _rank_terms(candidates.values(), limit=MAX_KEY_TERMS)


def _normalize_terms(
    value: Any, fallback: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Normalize LLM/local terms, merge them, and keep only precise labels."""

    candidates: list[dict[str, Any]] = []
    if isinstance(value, list):
        candidates.extend(
            _normalize_term_item(item, default_source="llm") for item in value
        )
    candidates.extend(
        _normalize_term_item(item, default_source="local") for item in fallback
    )
    return _rank_terms(
        [item for item in candidates if item],
        limit=MAX_KEY_TERMS,
    )


def _normalize_term_item(item: Any, default_source: str) -> dict[str, Any]:
    if isinstance(item, dict):
        source = str(item.get("source") or item.get("en") or "").strip()
        zh = str(item.get("zh") or item.get("translation") or "").strip()
        kind = str(item.get("kind") or "").strip() or None
        confidence = _coerce_confidence(item.get("confidence"))
        term_source = str(item.get("term_source") or default_source).strip()
    else:
        source = str(item).strip()
        zh = ""
        kind = None
        confidence = None
        term_source = default_source

    source = clean_key_term(source)
    zh = clean_key_term(zh)
    if source and not is_valid_key_term(source):
        source = ""
    if zh and not is_valid_key_term(zh):
        zh = ""
    if not source and not zh:
        return {}

    display = zh or source
    inferred_kind, bonus = _term_kind_and_bonus(display)
    if not kind:
        kind = inferred_kind
    base_confidence = 0.76 if term_source == "llm" else 0.62
    if confidence is None:
        confidence = min(0.95, base_confidence + bonus / 10.0)
    return {
        "source": (source or zh)[:80],
        "zh": (zh or source if _is_chinese_text(source or zh) else zh)[:80],
        "kind": kind,
        "confidence": round(max(0.0, min(confidence, 0.98)), 3),
        "term_source": term_source if term_source in {"local", "llm"} else default_source,
    }


def _rank_terms(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        source = clean_key_term(str(item.get("source") or ""))
        zh = clean_key_term(str(item.get("zh") or ""))
        if source and not is_valid_key_term(source):
            source = ""
        if zh and not is_valid_key_term(zh):
            zh = ""
        if not source and not zh:
            continue
        identity = _term_identity(source, zh)
        confidence = _coerce_confidence(item.get("confidence")) or 0.55
        _, bonus = _term_kind_and_bonus(zh or source)
        score = float(item.get("_score") or 0.0) + confidence + bonus
        normalized = {
            "source": (source or zh)[:80],
            "zh": (zh or source if _is_chinese_text(source or zh) else zh)[:80],
            "kind": str(item.get("kind") or _term_kind_and_bonus(zh or source)[0]),
            "confidence": round(max(0.0, min(confidence, 0.98)), 3),
            "term_source": str(item.get("term_source") or "local"),
            "_score": score,
        }
        existing = best.get(identity)
        if existing is None or score > float(existing.get("_score") or 0.0):
            best[identity] = normalized

    ranked = sorted(
        best.values(),
        key=lambda item: (
            -float(item.get("_score") or 0.0),
            -len(str(item.get("zh") or item.get("source") or "")),
            str(item.get("source") or item.get("zh") or ""),
        ),
    )
    result: list[dict[str, Any]] = []
    for item in ranked[:limit]:
        item.pop("_score", None)
        result.append(item)
    return result


def _term_kind_and_bonus(term: str) -> tuple[str, float]:
    cleaned = clean_key_term(term)
    lowered = cleaned.lower()
    exact = MATH_CONCEPT_TERMS.get(cleaned) or MATH_CONCEPT_TERMS.get(lowered)
    if exact:
        return exact

    best_kind = "term"
    best_bonus = 0.0
    for concept, (kind, bonus) in MATH_CONCEPT_TERMS.items():
        source = lowered if concept.isascii() else cleaned
        if concept in source and bonus * 0.65 > best_bonus:
            best_kind = kind
            best_bonus = bonus * 0.65
    if best_bonus:
        return best_kind, best_bonus
    if cleaned.endswith("\u5224\u522b\u6cd5"):
        return "method", 1.8
    if cleaned.endswith("\u5b9a\u7406"):
        return "theorem", 1.7
    if cleaned.endswith("\u7ae0") or cleaned.endswith("\u8282"):
        return "chapter", 1.2
    return "term", 0.0


def _term_identity(source: str, zh: str) -> str:
    value = zh or source
    if _is_chinese_text(value):
        return re.sub(r"\s+", "", value)
    return re.sub(r"\s+", " ", value.lower()).strip()


def _coerce_confidence(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_chinese_text(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _chinese_concept_candidates(block: str) -> list[str]:
    block = clean_key_term(block)
    if not block:
        return []
    candidates: set[str] = set()
    for concept in MATH_CONCEPT_TERMS:
        if not concept.isascii() and concept in block:
            candidates.add(concept)

    max_len = min(8, len(block))
    for size in range(max_len, 1, -1):
        for start in range(0, len(block) - size + 1):
            term = clean_key_term(block[start : start + size])
            if _looks_like_chinese_concept(term):
                candidates.add(term)
    return sorted(
        candidates,
        key=lambda value: (
            -_term_kind_and_bonus(value)[1],
            -len(value),
            value,
        ),
    )


def _looks_like_chinese_concept(term: str) -> bool:
    if not term or not _is_chinese_text(term):
        return False
    if term in MATH_CONCEPT_TERMS:
        return True
    if len(term) < 4:
        return False
    if term[0] in set("\u5176\u8fd9\u53ef\u56e0\u6240\u660e\u548c\u4e3a\u4e14\u5219\u6709\u7531\u53d6\u5f53"):
        return False
    concept_markers = (
        "\u7ea7\u6570",
        "\u6536\u655b",
        "\u53d1\u6563",
        "\u90e8\u5206\u548c",
        "\u5224\u522b\u6cd5",
        "\u6781\u9650",
        "\u5bfc\u6570",
        "\u79ef\u5206",
        "\u5fae\u5206",
        "\u77e9\u9635",
        "\u7279\u5f81\u503c",
        "\u6982\u7387",
        "\u65b9\u5dee",
        "\u5b9a\u7406",
    )
    return any(marker in term for marker in concept_markers)


def extract_formulas(text: str) -> list[str]:
    """Extract LaTeX/math-looking expressions for exact formula retrieval."""

    candidates: list[str] = []
    patterns = [
        r"\$\$.*?\$\$",
        r"\\\[.*?\\\]",
        r"\\\(.*?\\\)",
        r"\$[^$\n]{2,400}\$",
    ]
    for pattern in patterns:
        candidates.extend(match.group(0) for match in re.finditer(pattern, text, re.S))

    for line in text.splitlines():
        stripped = line.strip()
        if any(re.search(pattern, stripped, re.S) for pattern in FORMULA_SPAN_PATTERNS):
            stripped = _strip_delimited_formulas(stripped).strip()
        if _looks_like_formula_line(stripped):
            candidates.append(stripped)

    formulas: list[str] = []
    for candidate in candidates:
        formula = _normalize_formula(candidate)
        if not formula or formula in formulas:
            continue
        formulas.append(formula)
        if len(formulas) >= 12:
            break
    return formulas


def _looks_like_formula_line(line: str) -> bool:
    if len(line) < 3 or len(line) > 500:
        return False
    has_latex_command = bool(
        re.search(r"\\(?:frac|int|sum|lim|sqrt|begin|partial|nabla)", line)
    )
    if has_latex_command:
        return True
    math_symbols = len(MATH_SYMBOL_RE.findall(line))
    alpha_or_digit = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", line))
    differential_terms = len(re.findall(r"\b(?:dx|dy|dz|dt)\b", line, re.I))
    prose_words = len(re.findall(r"\b[A-Za-z]{3,}\b", line))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", line))
    if chinese_chars > 8 and math_symbols < 4:
        return False
    if prose_words > 6 and math_symbols < 4:
        return False
    return (math_symbols >= 2 and alpha_or_digit >= 2) or (
        math_symbols >= 1 and differential_terms >= 1
    )


def _normalize_formula(value: str) -> str:
    formula = value.strip()
    formula = re.sub(r"^\$\$|\$\$$", "", formula).strip()
    formula = re.sub(r"^\$|\$$", "", formula).strip()
    formula = re.sub(r"^\\\(|\\\)$", "", formula).strip()
    formula = re.sub(r"^\\\[|\\\]$", "", formula).strip()
    formula = re.sub(r"\s+", " ", formula)
    return formula[:500]


def clean_text_for_retrieval(text: str) -> str:
    """为检索和术语抽取清洗 LaTeX 排版噪声，保留公式语义提示。"""

    cleaned = text
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = _strip_delimited_formulas(cleaned)
    cleaned = cleaned.replace("\\left", " ").replace("\\right", " ")
    cleaned = re.sub(r"\\(?:mathrm|operatorname|text)\{([^{}]*)\}", r" \1 ", cleaned)
    cleaned = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r" fraction \1 over \2 ", cleaned)
    cleaned = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r" square root \1 ", cleaned)
    cleaned = re.sub(r"\\begin\{[^{}]+\}|\\end\{[^{}]+\}", " ", cleaned)

    def replace_command(match: re.Match[str]) -> str:
        command = match.group(1)
        if command in LATEX_COMMAND_WORDS:
            return " "
        return f" {LATEX_COMMAND_REPLACEMENTS.get(command, '')} "

    cleaned = re.sub(r"\\([A-Za-z]+)", replace_command, cleaned)
    cleaned = cleaned.replace("^", " power ").replace("_", " subscript ")
    cleaned = re.sub(r"[{}\\]+", " ", cleaned)
    cleaned = re.sub(r"[=+\-*/<>|()[\],.;:]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _strip_delimited_formulas(text: str) -> str:
    cleaned = text
    for pattern in FORMULA_SPAN_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.DOTALL)
    return cleaned


def clean_key_term(term: str) -> str:
    """清理模型返回的单个术语，避免把公式片段写入标签。"""

    cleaned = term.strip()
    cleaned = re.sub(r"^\$+|\$+$", "", cleaned)
    cleaned = re.sub(r"^\\\(|\\\)$|^\\\[|\\\]$", "", cleaned).strip()
    cleaned = re.sub(r"^formulae?\s*:\s*", "", cleaned, flags=re.I)
    cleaned = CHINESE_TERM_NOISE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+[A-Za-z]$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    parts = cleaned.split()
    while parts and parts[0].lower() in TERM_STOPWORDS:
        parts.pop(0)
    while parts and parts[-1].lower() in TERM_STOPWORDS:
        parts.pop()
    cleaned = " ".join(parts)
    return cleaned


def is_valid_key_term(term: str) -> bool:
    """判断术语是否像课程概念，而不是 LaTeX 命令、变量或公式片段。"""

    cleaned = clean_key_term(term)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in TERM_STOPWORDS or lowered in KEY_TERM_NOISE_WORDS:
        return False
    if _is_chinese_text(cleaned):
        compacted = re.sub(r"\s+", "", cleaned)
        if compacted in CHINESE_TERM_NOISE:
            return False
        if len(compacted) > 10 and _term_kind_and_bonus(compacted)[1] <= 0:
            return False
    words = [word.lower() for word in re.findall(r"[A-Za-z]+", cleaned)]
    if any(word in FORMULA_HARD_TERM_STOPWORDS for word in words):
        return False
    if len(words) == 1 and words[0] in FORMULA_STANDALONE_TERM_STOPWORDS:
        return False
    if "\\" in cleaned or any(char in cleaned for char in "{}^_"):
        return False
    if re.fullmatch(r"\d*[A-Za-z]\d*", cleaned):
        return False
    if re.fullmatch(r"[A-Za-z]", cleaned):
        return False
    if re.fullmatch(r"(?:[A-Za-z]\s*){2,5}", cleaned):
        return False
    if re.fullmatch(r"[\d\s.,:/+-]+", cleaned):
        return False
    if re.search(r"[=+\-*/<>]", cleaned) and re.search(r"[A-Za-z0-9]", cleaned):
        return False
    if len(cleaned) < 2:
        return False
    symbol_count = len(re.findall(r"[^A-Za-z0-9\u4e00-\u9fff\s-]", cleaned))
    if symbol_count > max(1, len(cleaned) // 4):
        return False
    return True


def _shorten_zh(text: str) -> str:
    """截取一段适合作为中文摘要兜底的文本。"""

    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= 160:
        return cleaned
    return cleaned[:160] + "..."
