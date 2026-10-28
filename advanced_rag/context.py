"""Context assembly, budget-aware compression, and citation-ready evidence."""
from .ingestion.models import Chunk

def compress(text,max_chars):
    if max_chars<=0: return ""
    if len(text)<=max_chars: return text
    marker="\n...[context compressed]...\n"
    if max_chars<=len(marker): return text[:max_chars]
    head=(max_chars-len(marker))*2//3; tail=max_chars-len(marker)-head
    return text[:head]+marker+text[-tail:]
def build_context(chunks,max_chars=7000):
    blocks=[]; used=0
    for i,c in enumerate(chunks,1):
        block=f"[Source {i}: {c.source} | chunk {c.chunk_id}]\n{c.text}"
        if used+len(block)>max_chars:
            remain=max_chars-used
            if remain>120: blocks.append(compress(block,remain))
            break
        blocks.append(block); used+=len(block)
    return "\n\n".join(blocks)
def sources(chunks):
    return [{"id":i,"file":c.source,"source":c.source,"page":c.metadata.get("page"),"section":c.metadata.get("section",""),"chunk_id":c.chunk_id} for i,c in enumerate(chunks,1)]
