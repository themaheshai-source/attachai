"""Knowledge-base profiling used as a soft signal, never a retrieval gate."""
from collections import Counter
import re

def profile(chunks):
    text=" ".join(c.text for c in chunks); words=re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    stop={"the","and","for","with","that","this","are","from","you","will","not","was","have","has","into","what","how"}
    terms=Counter(w for w in words if w not in stop)
    return {"documents":len({c.source for c in chunks}),"chunks":len(chunks),"characters":len(text),"top_terms":[x for x,_ in terms.most_common(50)],"vocabulary":len(set(words))}

def domain_score(query, prof):
    if not query or not prof: return 0.0
    q=set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", query.lower())); terms=set(prof.get("top_terms", []))
    return len(q & terms)/max(1,len(q))
class KnowledgeProfiler:
    def profile(self,chunks): return profile(chunks)
    def score(self,query,prof): return domain_score(query,prof)
