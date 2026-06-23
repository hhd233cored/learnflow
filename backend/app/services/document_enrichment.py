from __future__ import annotations

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
    "and",
    "are",
    "for",
    "from",
    "left",
    "right",
    "that",
    "there",
    "this",
    "with",
}

FORMULA_TERM_STOPWORDS = {
    "derivative",
    "dx",
    "dy",
    "dz",
    "fraction",
    "gradient",
    "integral",
    "limit",
    "over",
    "partial",
    "power",
    "root",
    "square",
    "subscript",
    "summation",
    "superscript",
}


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
    key_terms: list[dict[str, str]]


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
                            {"source": "process scheduling", "zh": "进程调度"}
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
    key_terms = _normalize_terms(raw.get("key_terms"), fallback["key_terms"])
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


def _extract_terms(text: str) -> list[dict[str, str]]:
    """从文本里抽取少量候选术语，作为无 LLM 时的兜底术语表。"""

    terms: list[dict[str, str]] = []
    cleaned_text = clean_text_for_retrieval(text)
    english_terms = re.findall(
        r"\b[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,2}\b",
        cleaned_text,
    )
    for term in english_terms:
        cleaned = clean_key_term(term.strip())
        if not is_valid_key_term(cleaned):
            continue
        if cleaned not in [item["source"] for item in terms]:
            terms.append({"source": cleaned[:80], "zh": ""})
        if len(terms) >= 8:
            break

    chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,8}", cleaned_text)
    for term in chinese_terms:
        if is_valid_key_term(term) and term not in [item["zh"] for item in terms]:
            terms.append({"source": term, "zh": term})
        if len(terms) >= 10:
            break
    return terms


def _normalize_terms(value: Any, fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    """把模型返回的术语表规整成短列表。"""

    if not isinstance(value, list):
        return fallback[:10]

    normalized: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            source = str(item.get("source") or item.get("en") or "").strip()
            zh = str(item.get("zh") or item.get("translation") or "").strip()
        else:
            source = str(item).strip()
            zh = ""
        source = clean_key_term(source)
        zh = clean_key_term(zh)
        if not source and not zh:
            continue
        if source and not is_valid_key_term(source):
            source = ""
        if zh and not is_valid_key_term(zh):
            zh = ""
        if not source and not zh:
            continue
        normalized.append({"source": source[:80], "zh": zh[:80]})
        if len(normalized) >= 10:
            break
    return normalized or [
        item
        for item in fallback[:10]
        if is_valid_key_term(item.get("source", "")) or is_valid_key_term(item.get("zh", ""))
    ]


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
    if re.search(r"\\(?:frac|int|sum|lim|sqrt|begin|partial|nabla)", line):
        return True
    math_symbols = len(re.findall(r"[=^_+\-*/<>∫Σ√∞≤≥]", line))
    alpha_or_digit = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", line))
    return math_symbols >= 2 and alpha_or_digit >= 2


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


def clean_key_term(term: str) -> str:
    """清理模型返回的单个术语，避免把公式片段写入标签。"""

    cleaned = term.strip()
    cleaned = re.sub(r"^\$+|\$+$", "", cleaned)
    cleaned = re.sub(r"^\\\(|\\\)$|^\\\[|\\\]$", "", cleaned).strip()
    cleaned = re.sub(r"\s+[A-Za-z]$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def is_valid_key_term(term: str) -> bool:
    """判断术语是否像课程概念，而不是 LaTeX 命令、变量或公式片段。"""

    cleaned = clean_key_term(term)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in TERM_STOPWORDS or lowered in LATEX_COMMAND_WORDS:
        return False
    words = [word.lower() for word in re.findall(r"[A-Za-z]+", cleaned)]
    if any(word in FORMULA_TERM_STOPWORDS for word in words):
        return False
    if lowered in {key.lower() for key in LATEX_COMMAND_REPLACEMENTS}:
        return False
    if "\\" in cleaned or any(char in cleaned for char in "{}^_"):
        return False
    if re.fullmatch(r"[A-Za-z]", cleaned):
        return False
    if re.fullmatch(r"(?:[A-Za-z]\s*){2,5}", cleaned):
        return False
    if re.fullmatch(r"[\d\s.,:/+-]+", cleaned):
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
