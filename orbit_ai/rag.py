from __future__ import annotations

import re
import math
from collections import Counter
from typing import Any

from .integrations.query_understanding import QueryUnderstandingService

STOPWORDS = set("a an and are as at be by for from has have how i in is it its of on or that the their this to was what when where which who why will with your you our do does did can could would should is are was were aap aur hai hain kya ka ki ke iska iski uska uski ye yeh woh main mein mujhe batao please about tell me we they them then than price pricing per month monthly plan plans service services product products policy available availability tell".split())
SYNONYMS = {"cost": "price", "costs": "price", "plans": "plan", "services": "service", "fees": "fee", "monthly": "month", "annually": "annual", "refunds": "refund", "charges": "charge"}
_NUMBER_RE = re.compile(r"(£|AUD\s*\$|\$|€)?\s*(\d+(?:[.,]\d+)?)(?:\s*%|\s*(?:per|a)\s*(month|year|day|week))?", re.I)

def tokens(text: str) -> list[str]:
    return [SYNONYMS.get(t, t) for t in re.findall(r"[^\W_]+", (text or "").lower(), flags=re.UNICODE) if t not in STOPWORDS and len(t) > 1]

def comparable(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def overlap(query_terms: set[str], text: str) -> int:
    return len(query_terms.intersection(tokens(text)))

def deduplicate(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set(); output = []
    for chunk in chunks:
        key = comparable(chunk.get("text", ""))
        if key and key not in seen:
            seen.add(key); output.append(chunk)
    return output

def exact_search(query: str, chunks: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    normalized = comparable(query); terms = set(tokens(query))
    phrases = [c for c in chunks if normalized and normalized in comparable(c.get("text", ""))]
    ids = {c["id"] for c in phrases}
    rest = sorted((c for c in chunks if c["id"] not in ids and overlap(terms, c.get("text", "")) > 0), key=lambda c: (-overlap(terms, c.get("text", "")), str(c["id"])))
    return (phrases + rest)[:limit]

def keyword_search(query: str, chunks: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    terms = set(tokens(query))
    return sorted(chunks, key=lambda c: (-overlap(terms, c.get("text", "")), len(c.get("text", "")), str(c["id"])))[:limit]

def bm25_search(query: str, chunks: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    terms = tokens(query)
    docs = [tokens(c.get("text", "")) for c in chunks]
    avg = sum(map(len, docs)) / max(1, len(docs))
    df = Counter(term for doc in docs for term in set(doc))
    scored = []
    for chunk, doc in zip(chunks, docs):
        freq = Counter(doc); score = 0.0
        for term in terms:
            tf = freq.get(term, 0)
            if tf:
                n = df.get(term, 0)
                idf = math.log(1 + (len(docs) - n + 0.5) / (n + 0.5))
                score += idf * tf * 2 / (tf + 1.5 * (0.25 + 0.75 * len(doc) / max(avg, 1)))
        scored.append((score, chunk))
    return [c for _, c in sorted(scored, key=lambda x: (-x[0], str(x[1]["id"])))[:limit]]

def reciprocal_rank_fusion(rankings: list[list[dict[str, Any]]], limit: int = 100) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}; found: dict[str, dict[str, Any]] = {}
    for ranklist in rankings:
        for rank, chunk in enumerate(ranklist):
            cid = str(chunk["id"]); found[cid] = chunk
            scores[cid] = scores.get(cid, 0) + 1 / (60 + rank + 1)
    return [{**found[cid], "score": scores[cid]} for cid in sorted(found, key=lambda i: (-scores[i], i))[:limit]]

def rerank(query: str, chunks: list[dict[str, Any]], vocabulary: list[str]) -> list[dict[str, Any]]:
    qterms = set(tokens(query)); vocab = set(vocabulary)
    domain_score = len(qterms & vocab) / max(1, len(qterms))
    ranked = []
    for c in chunks:
        lexical = overlap(qterms, c.get("text", "")) / max(1, len(qterms))
        phrase = 1.0 if comparable(query) and comparable(query) in comparable(c.get("text", "")) else 0.0
        ranked.append({**c, "score": 0.65 * lexical + 0.25 * phrase + 0.1 * domain_score})
    return sorted(ranked, key=lambda c: (-c["score"], str(c["id"])))

def _period_for(text: str) -> str | None:
    if re.search(r"\b(monthly|per month|each month|every month|a month|month-to-month)\b", text, re.I):
        return "month"
    if re.search(r"\b(annual(?:ly)?|yearly|per year|each year|every year|a year)\b", text, re.I):
        return "year"
    if re.search(r"\b(per week|weekly|each week|a week)\b", text, re.I):
        return "week"
    if re.search(r"\b(per day|daily|each day|a day)\b", text, re.I):
        return "day"
    return None


def _conflicting_numeric_evidence(query: str, chunks: list[dict[str, Any]]) -> bool:
    """Conservatively detect different amounts for the same named topic and billing period."""
    generic_terms = {"price", "cost", "fee", "charge", "plan", "service", "product", "month", "annual", "year", "week", "day", "available", "included"}
    query_terms = set(tokens(query)) - generic_terms
    if not query_terms:
        return False
    requested_period = _period_for(query)
    observed: dict[tuple[str, str | None], set[str]] = {}
    for chunk in chunks:
        text = str(chunk.get("text", ""))
        for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
            sentence = sentence.strip()
            if not sentence:
                continue
            sentence_terms = set(tokens(sentence))
            # Require a specific topic overlap instead of flagging different plans or
            # unrelated amounts that happen to occur in the same retrieved context.
            if len(query_terms & sentence_terms) < min(2, len(query_terms)):
                continue
            period = _period_for(sentence)
            if requested_period and period != requested_period:
                continue
            for match in _NUMBER_RE.finditer(sentence):
                currency = re.sub(r"\s+", "", match.group(1) or "").lower()
                qualifier = (match.group(3) or "").lower() or period
                # Ignore incidental numerals such as product IDs unless they look like
                # amounts (currency) or have an explicit billing/time qualifier.
                if not currency and not qualifier and "%" not in match.group(0):
                    continue
                value = match.group(2).replace(",", "")
                observed.setdefault((currency, qualifier), set()).add(value)
    return any(len(values) > 1 for values in observed.values())


def evidence_decision(query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    qterms = set(tokens(query))
    coverage = max([overlap(qterms, c.get("text", "")) / max(1, len(qterms)) for c in chunks] or [0.0])
    exact = any(comparable(query) in comparable(c.get("text", "")) for c in chunks) if comparable(query) else False
    strong = sum(1 for c in chunks if float(c.get("score", 0)) >= 0.2)
    status = "SUPPORTED" if exact or coverage >= 0.55 or strong >= 2 else "PARTIALLY_SUPPORTED" if coverage >= 0.2 and chunks else "UNCERTAIN" if coverage > 0 and chunks else "NOT_SUPPORTED"
    result = {"status": status, "coverage": round(coverage, 4), "count": len(chunks), "sources": len({c.get("source") for c in chunks}), "sufficient": status in {"SUPPORTED", "PARTIALLY_SUPPORTED"}}
    if chunks and _conflicting_numeric_evidence(query, chunks):
        result.update({"status": "UNCERTAIN", "sufficient": False, "conflict": True})
    return result

def corpus_profile(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    frequencies = Counter(t for c in chunks for t in tokens(c.get("text", "")) if len(t) > 2)
    return {"documents": len({c.get("source") for c in chunks}), "chunks": len(chunks), "vocabulary": len(frequencies), "topTerms": [x[0] for x in frequencies.most_common(50)]}

def select_context(chunks: list[dict[str, Any]], max_chars: int = 7000) -> list[dict[str, Any]]:
    selected = []; used = 0
    for chunk in deduplicate(chunks):
        candidate = chunk.get("text", "")
        label_len = len(f"[Source {len(selected)+1}: {chunk.get('source','unknown')} | chunk {chunk.get('id','')} ]\n")
        if used + label_len + len(candidate) > max_chars:
            continue
        selected.append(chunk); used += label_len + len(candidate) + 2
        if len(selected) >= 3:
            break
    return selected

def retrieve_advanced(question: str, corpus: list[dict[str, Any]], dense: list[dict[str, Any]]) -> dict[str, Any]:
    corpus = deduplicate(corpus)
    def run(query: str, dense_hits: list[dict[str, Any]]) -> dict[str, Any]:
        exact = exact_search(query, corpus)
        keyword = keyword_search(query, corpus)
        bm25 = bm25_search(query, corpus)
        fused = reciprocal_rank_fusion([exact, keyword, bm25, dense_hits[:20]])
        ranked = rerank(query, fused, corpus_profile(corpus)["topTerms"])[:12]
        return {"exact": exact, "keyword": keyword, "bm25": bm25, "fused": fused, "ranked": ranked}
    first = run(question, dense)
    selected = select_context(first["ranked"])
    decision = evidence_decision(question, selected)
    counts = {"exact": len(first["exact"]), "keyword": len(first["keyword"]), "bm25": len(first["bm25"]), "dense": len(dense), "fused": len(first["fused"])}
    expanded = False
    if decision["status"] in {"UNCERTAIN", "NOT_SUPPORTED"} and corpus:
        expanded = True
        current = set(tokens(question))
        additions = Counter(t for c in corpus for t in tokens(c.get("text", "")) if t not in current and len(t) > 2)
        expanded_query = question + " " + " ".join(t for t, _ in additions.most_common(5))
        second = run(expanded_query.strip(), [])
        selected = select_context(rerank(question, reciprocal_rank_fusion([first["fused"], second["keyword"], second["bm25"]]), corpus_profile(corpus)["topTerms"])[:12])
        decision = evidence_decision(question, selected)
        counts = {"exact": len(first["exact"]) + len(second["exact"]), "keyword": len(first["keyword"]) + len(second["keyword"]), "bm25": len(first["bm25"]) + len(second["bm25"]), "dense": len(dense), "fused": min(100, len(first["fused"]) + len(second["fused"]))}
    return {"evidence": selected, "decision": decision, "diagnostics": {"query": question, "expanded": expanded, "profile": corpus_profile(corpus), "candidateCounts": counts, "evidence": decision, "rejected": [{"id": c["id"], "reason": "low deterministic rerank score"} for c in selected if c.get("score", 0) < 0.2]}}

def clean_answer(answer: str) -> str:
    text = re.sub(r"^\s*(?:#{1,6}\s*)?(?:faq|answer)\s*:?\s*", "", answer, flags=re.I)
    text = re.sub(r"(?:^|\n)\s*[QA]:\s*", " ", text, flags=re.I)
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    seen = set(); result = []
    for sentence in sentences:
        key = comparable(sentence)
        if key and key not in seen:
            seen.add(key); result.append(sentence.strip())
    return " ".join(result).strip()

def validate_grounding(question: str, answer: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    if not evidence:
        return {"ok": True, "reasons": []}
    source = "\n".join(str(c.get("text", "")) for c in evidence)
    def nums(text: str):
        out = []
        for match in _NUMBER_RE.finditer(text):
            currency = re.sub(r"\s+", "", (match.group(1) or "")).lower()
            value = match.group(2).replace(",", "")
            qualifier = "%" if "%" in match.group(0) else (match.group(3) or "").lower()
            out.append((currency, value, qualifier))
        return out
    answer_numbers, source_numbers = nums(answer), nums(source)
    reasons = []
    unsupported = [a for a in answer_numbers if not any(s[1] == a[1] and (not a[0] or not s[0] or a[0] == s[0]) and (not a[2] or not s[2] or a[2] == s[2]) for s in source_numbers)]
    if unsupported:
        reasons.append("unsupported numeric claim")
    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE) if len(w) >= 3 and w not in {"what", "does", "have", "with", "from", "that", "this", "about", "are", "the"}}
    qwords = words(question)
    unknown = [line for line in re.split(r"(?<=[.!?])\s+|\n", source) if re.search(r"\bunknown\b|not available|not specified|cannot be verified", line, re.I)]
    if answer_numbers and any(len(qwords & words(line)) >= 2 for line in unknown) and not re.search(r"unknown|not available|not specified|cannot verify|check the official|support", answer, re.I):
        reasons.append("answer supplies a value where relevant evidence is unknown")
    negative = [line for line in re.split(r"(?<=[.!?])\s+|\n", source) if re.search(r"\b(no|not|does not|do not|never|cannot|must not|without)\b", line, re.I)]
    qualifications = [line for line in re.split(r"(?<=[.!?])\s+|\n", source) if re.search(r"\b(most|some|vary|varies|depends|subject to|may|can differ)\b", line, re.I)]
    affirmative = bool(re.search(r"\b(is|are|does|do|offers?|provides?|guarantees?|available|included|open|free)\b", answer, re.I)) and not bool(re.search(r"\b(not|no|cannot|unavailable|unknown|should not)\b", answer, re.I))
    if affirmative and any(qwords & words(line) for line in negative): reasons.append("possible contradiction with negative evidence")
    if re.search(r"\b(all|every|always|never)\b", answer, re.I) and any(qwords & words(line) for line in qualifications): reasons.append("answer drops an evidence qualification")
    return {"ok": not reasons, "reasons": reasons}


def grounding_correction(reasons: list[str]) -> str:
    return (f"Grounding check failed ({'; '.join(reasons)}). Re-read TENANT KNOWLEDGE as factual evidence only. "
            "Correct or remove unsupported claims, numbers, prices, availability statements, guarantees, or policy claims. "
            "If the requested fact is missing or marked UNKNOWN, state that it is not available in the current tenant knowledge. "
            "Return only the corrected customer-facing answer.")
