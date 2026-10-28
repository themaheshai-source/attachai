"""Multi-strategy retrieval with soft domain signals and evidence-first decisions."""
from collections import Counter
import math, re
from .profiling import domain_score

_STOPWORDS={"a","an","the","is","are","was","were","what","which","who","how","much","does","do","did","of","for","to","in","on","and","or","will","can","i","my","it","this","that","with","when","where","why"}
_SYNONYMS={"cancellation":"cancel","canceled":"cancel","cancelled":"cancel","receive":"refund","received":"refund","back":"refund","money":"refund","flat":"property","homes":"property","home":"property"}
def tokens(s):
    return [_SYNONYMS.get(t,t) for t in re.findall(r"[A-Za-z0-9_/-]+", s.lower()) if t not in _STOPWORDS]

def exact_search(query, chunks, k=20):
    q=query.lower().strip()
    # Phrase hits first, then exact entity/term coverage.
    phrase=[c for c in chunks if q and q in c.text.lower()]
    terms=set(tokens(query)); rest=[c for c in chunks if c not in phrase and terms & set(tokens(c.text))]
    return (phrase + sorted(rest,key=lambda c:len(terms & set(tokens(c.text))),reverse=True))[:k]

def keyword_search(query,chunks,k=20):
    q=set(tokens(query))
    return sorted(chunks,key=lambda c:(len(q & set(tokens(c.text))), len(c.text)),reverse=True)[:k]

def bm25_search(query,chunks,k=20):
    q=tokens(query); docs=[tokens(c.text) for c in chunks]; n=len(docs)
    df=Counter(x for d in docs for x in set(d)); avg=sum(map(len,docs))/max(n,1); out=[]
    for c,d in zip(chunks,docs):
        tf=Counter(d); score=0.0
        for t in q:
            if tf[t]:
                idf=math.log(1+(n-df[t]+.5)/(df[t]+.5))
                score += idf*tf[t]*2/(tf[t]+1.5*(.25+.75*len(d)/max(avg,1)))
        out.append((score,c))
    return [c for _,c in sorted(out,key=lambda x:x[0],reverse=True)[:k]]

def rrf(rankings,k=60,limit=20):
    scores={}; objects={}
    for ranking in rankings:
        for rank,c in enumerate(ranking):
            scores[c.chunk_id]=scores.get(c.chunk_id,0)+1/(k+rank+1); objects[c.chunk_id]=c
    result=sorted(objects.values(),key=lambda c:scores[c.chunk_id],reverse=True)[:limit]
    for c in result: c.retrieval["rrf"]=scores[c.chunk_id]; c.score=scores[c.chunk_id]
    return result

def rerank(query,chunks,profile=None):
    q=set(tokens(query)); ds=domain_score(query,profile or {})
    out=[]
    for c in chunks:
        ct=set(tokens(c.text)); overlap=len(q&ct)/max(1,len(q)); phrase=float(query.lower() in c.text.lower())
        c.retrieval.update({"lexical":overlap,"domain":ds})
        c.score=.65*overlap+.25*phrase+.10*ds
        out.append(c)
    return sorted(out,key=lambda c:c.score,reverse=True)

def expand_query(query,chunks,limit=5):
    q=set(tokens(query)); freq=Counter(t for c in chunks for t in tokens(c.text) if t not in q and len(t)>2)
    return query+" "+" ".join(t for t,_ in freq.most_common(limit))

def evaluate_evidence(query,chunks):
    q=set(tokens(query))
    coverage=max((len(q&set(tokens(c.text)))/max(1,len(q)) for c in chunks),default=0.0)
    exact=any(query.lower() in c.text.lower() for c in chunks)
    strong=sum(1 for c in chunks if c.score >= .20)
    if exact or coverage>=.55 or strong>=2: status="SUPPORTED"
    elif coverage>=.20 and chunks: status="PARTIALLY_SUPPORTED"
    elif coverage>0 and chunks: status="UNCERTAIN"
    else: status="NOT_SUPPORTED"
    return {"coverage":coverage,"count":len(chunks),"sources":len({c.source for c in chunks}),"sufficient":status in {"SUPPORTED","PARTIALLY_SUPPORTED"},"status":status}

def hybrid_retrieve(query,chunks,store=None,embedder=None,k=8,profile=None,expand=False):
    rankings=[exact_search(query,chunks),keyword_search(query,chunks),bm25_search(query,chunks)]
    if store and embedder: rankings.append(store.search(embedder.embed([query])[0],max(k*3,20)))
    if expand and chunks:
        q=expand_query(query,chunks)
        rankings.extend([keyword_search(q,chunks),bm25_search(q,chunks)])
    return rerank(query,rrf(rankings,limit=max(k*3,20)),profile)[:k]

class Reranker:
    """Optional cross-encoder with deterministic lexical fallback."""
    def __init__(self,model=None):
        self.model=None
        if model:
            try:
                from sentence_transformers import CrossEncoder
                self.model=CrossEncoder(model)
            except Exception: pass
    def rerank(self,query,chunks,profile=None):
        if self.model is None: return rerank(query,chunks,profile)
        try:
            scores=self.model.predict([(query,c.text) for c in chunks])
            for c,s in zip(chunks,scores):
                c.score=float(s)
                c.retrieval["cross_encoder"]=float(s)
            return sorted(chunks,key=lambda c:c.score,reverse=True)
        except Exception:
            return rerank(query,chunks,profile)

class HybridRetriever:
    def __init__(self,chunks,store=None,embedder=None,profile=None): self.chunks=chunks; self.store=store; self.embedder=embedder; self.profile=profile or {}
    def retrieve(self,query,k=8,expand=False): return hybrid_retrieve(query,self.chunks,self.store,self.embedder,k,self.profile,expand)


def multi_query_retrieve(original_query, variants, chunks, store=None, embedder=None, k=8, profile=None, normalized_query=None):
    """Retrieve across query variants, fuse rankings by stable chunk ID, then rerank.

    All variants contribute retrieval candidates, but the final score is explicitly
    compared with the original user wording and normalized interpretation so a weak
    expansion keyword cannot dominate the result on its own.
    """
    queries = []
    for query in [original_query, *(variants or [])]:
        query = (query or "").strip()
        if query and query.casefold() not in {item.casefold() for item in queries}:
            queries.append(query)
    if not queries or not chunks:
        return []

    rankings = []
    for query in queries:
        rankings.extend([
            exact_search(query, chunks, k=max(k * 3, 20)),
            keyword_search(query, chunks, k=max(k * 3, 20)),
            bm25_search(query, chunks, k=max(k * 3, 20)),
        ])
        if store is not None and embedder is not None:
            try:
                vector = embedder.embed([query])[0]
                rankings.append(store.search(vector, max(k * 3, 20)))
            except Exception:
                # Lexical retrieval remains usable in offline or vector-store failure mode.
                pass

    fused = rrf(rankings, limit=max(k * 5, 30))
    if not fused:
        return []

    p = profile or {}
    original_terms = set(tokens(original_query))
    normalized_terms = set(tokens(normalized_query or original_query))
    domain_original = domain_score(original_query, p)
    domain_normalized = domain_score(normalized_query or original_query, p)
    max_rrf = max((float(c.retrieval.get("rrf", c.score)) for c in fused), default=1.0) or 1.0
    for c in fused:
        chunk_terms = set(tokens(c.text))
        original_overlap = len(original_terms & chunk_terms) / max(1, len(original_terms))
        normalized_overlap = len(normalized_terms & chunk_terms) / max(1, len(normalized_terms))
        original_phrase = float(bool(original_query) and original_query.lower() in c.text.lower())
        normalized_phrase = float(bool(normalized_query) and normalized_query.lower() in c.text.lower())
        original_score = .65 * original_overlap + .25 * original_phrase + .10 * domain_original
        normalized_score = .65 * normalized_overlap + .25 * normalized_phrase + .10 * domain_normalized
        fusion_score = float(c.retrieval.get("rrf", c.score)) / max_rrf
        c.retrieval.update({
            "original_query_relevance": original_score,
            "normalized_query_relevance": normalized_score,
            "multi_query_rrf_normalized": fusion_score,
        })
        c.score = .35 * original_score + .55 * normalized_score + .10 * fusion_score
    # Stable dedupe by chunk ID (RRF already does this; keep the contract explicit).
    unique = {}
    for chunk in fused:
        current = unique.get(chunk.chunk_id)
        if current is None or chunk.score > current.score:
            unique[chunk.chunk_id] = chunk
    return sorted(unique.values(), key=lambda c: c.score, reverse=True)[:k]


def rerank_combined(original_query, normalized_query, chunks, profile=None):
    """Deterministic small-KB fallback scored against both original and normalized wording."""
    unique = {}
    for chunk in chunks:
        unique.setdefault(chunk.chunk_id, chunk)
    candidates = list(unique.values())
    p = profile or {}
    original_terms = set(tokens(original_query))
    normalized_terms = set(tokens(normalized_query or original_query))
    original_domain = domain_score(original_query, p)
    normalized_domain = domain_score(normalized_query or original_query, p)
    for chunk in candidates:
        chunk_terms = set(tokens(chunk.text))
        original_overlap = len(original_terms & chunk_terms) / max(1, len(original_terms))
        normalized_overlap = len(normalized_terms & chunk_terms) / max(1, len(normalized_terms))
        original_phrase = float(bool(original_query) and original_query.lower() in chunk.text.lower())
        normalized_phrase = float(bool(normalized_query) and normalized_query.lower() in chunk.text.lower())
        original_score = .65 * original_overlap + .25 * original_phrase + .10 * original_domain
        normalized_score = .65 * normalized_overlap + .25 * normalized_phrase + .10 * normalized_domain
        chunk.retrieval.update({
            "original_query_relevance": original_score,
            "normalized_query_relevance": normalized_score,
            "small_kb_combined_rerank": True,
        })
        chunk.score = .35 * original_score + .65 * normalized_score
    return sorted(candidates, key=lambda chunk: chunk.score, reverse=True)
