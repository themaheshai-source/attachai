"""Structure-aware, deterministic chunking for prose, markdown and tabular text."""
import re, hashlib, uuid
from .models import Document, Chunk

def _units(text: str):
    lines=text.splitlines(); groups=[]; cur=[]
    for line in lines:
        if cur and (not line.strip() or re.match(r"^#{1,6}\s", line)):
            groups.append("\n".join(cur).strip()); cur=[]
        if line.strip(): cur.append(line)
        elif cur: groups.append("\n".join(cur).strip()); cur=[]
    if cur: groups.append("\n".join(cur).strip())
    return groups or [text]

def chunk_document(doc: Document, size=900, overlap=120) -> list[Chunk]:
    size=max(100,size); overlap=max(0,min(overlap,size//2)); units=_units(doc.text); out=[]; buf=""; section=""
    def emit(txt):
        if txt.strip():
            i=len(out); digest=str(uuid.uuid5(uuid.NAMESPACE_URL,f"{doc.source}:{i}:{txt}"))
            out.append(Chunk(txt.strip(),digest,doc.source,{**doc.metadata,"section":section,"chunk_index":i}))
    for unit in units:
        heading=re.match(r"^(#{1,6})\s+(.+)",unit)
        if heading: section=heading.group(2).strip()
        candidate=f"{buf}\n{unit}".strip() if buf else unit
        if len(candidate)<=size: buf=candidate; continue
        emit(buf); tail=buf[-overlap:] if overlap else ""; buf=(tail+"\n"+unit).strip()
        while len(buf)>size:
            cut=buf.rfind(" ",0,size+1); cut=cut if cut>size//2 else size
            emit(buf[:cut]); buf=buf[max(0,cut-overlap):].lstrip()
    emit(buf); return out
