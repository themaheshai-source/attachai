"""Evidence quality checks used for the final answer/no-answer decision."""
from .retrieval import tokens

def evaluate_evidence(query,chunks):
    q=set(tokens(query)); coverage=max((len(q & set(tokens(c.text)))/max(1,len(q)) for c in chunks),default=0.0)
    exact=any(query.lower() in c.text.lower() for c in chunks)
    strong=sum(1 for c in chunks if c.score >= .20)
    if exact or coverage>=.55 or strong>=2: status="SUPPORTED"
    elif coverage>=.20 and chunks: status="PARTIALLY_SUPPORTED"
    elif coverage>0 and chunks: status="UNCERTAIN"
    else: status="NOT_SUPPORTED"
    return {"coverage":round(coverage,4),"count":len(chunks),"sources":len({c.source for c in chunks}),"sufficient":status in {"SUPPORTED","PARTIALLY_SUPPORTED"},"status":status,"scores":[round(c.score,4) for c in chunks]}
