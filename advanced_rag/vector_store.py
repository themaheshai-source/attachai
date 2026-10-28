"""Qdrant adapter. JSON local persistence is the dependency-free fallback."""
from pathlib import Path
import json, uuid
from .ingestion.models import Chunk
from .embeddings import Embedder

class LocalVectorStore:
    def __init__(self, path=".rag_data/vectors.json", collection="knowledge", embedder=None):
        self.path=Path(path); self.collection=collection; self.embedder=embedder or Embedder(); self.records=[]; self._load()
    def _load(self):
        try: self.records=json.loads(self.path.read_text())
        except (FileNotFoundError,json.JSONDecodeError): self.records=[]
    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True); self.path.write_text(json.dumps(self.records))
    def upsert(self,chunks):
        ids={c.chunk_id for c in chunks}; self.records=[r for r in self.records if r["id"] not in ids]
        for c,v in zip(chunks,self.embedder.embed([x.text for x in chunks])): self.records.append({"id":c.chunk_id,"text":c.text,"source":c.source,"metadata":c.metadata,"vector":v})
        self._save(); return len(chunks)
    def delete_sources(self,sources):
        s=set(map(str,sources)); self.records=[r for r in self.records if r["source"] not in s]; self._save()
    def search(self, vector, limit=10):
        vals=[(self.embedder.similarity(vector,r["vector"]),r) for r in self.records]; vals.sort(key=lambda x:x[0],reverse=True)
        return [self._chunk(r,score) for score,r in vals[:limit]]
    def _chunk(self,r,score=0): return Chunk(r["text"],r["id"],r["source"],r.get("metadata",{}),score=score)

class QdrantStore(LocalVectorStore):
    """Qdrant-backed store with a durable JSON fallback for minimal installations."""
    def __init__(self,path=".rag_data/vectors.json",collection="knowledge",embedder=None,url="",qdrant_path=None):
        super().__init__(path,collection,embedder); self.url=url; self.qdrant_path=qdrant_path; self._qdrant=None
        try:
            from qdrant_client import QdrantClient, models
            self._qdrant=QdrantClient(url=url) if url else QdrantClient(path=str(self.qdrant_path or Path(path).parent/"qdrant"))
            try: self._qdrant.get_collection(collection)
            except Exception: self._qdrant.create_collection(collection_name=collection, vectors_config=models.VectorParams(size=self.embedder.dimension,distance=models.Distance.COSINE))
        except Exception: self._qdrant=None
    def upsert(self,chunks):
        count=super().upsert(chunks)
        if self._qdrant and chunks:
            try:
                from qdrant_client import models
                vectors=self.embedder.embed([c.text for c in chunks])
                points=[models.PointStruct(id=c.chunk_id,payload=c.as_payload(),vector=v) for c,v in zip(chunks,vectors)]
                self._qdrant.upsert(collection_name=self.collection,points=points)
            except Exception: pass
        return count
    def delete_sources(self,sources):
        super().delete_sources(sources)
        if self._qdrant and sources:
            try:
                from qdrant_client import models
                self._qdrant.delete(collection_name=self.collection, points_selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(key="source",match=models.MatchAny(any=list(map(str,sources))))])))
            except Exception: pass
    def search(self,vector,limit=10):
        if self._qdrant:
            try:
                hits=self._qdrant.search(collection_name=self.collection,query_vector=vector,limit=limit)
                return [Chunk(h.payload.get("text", ""),str(h.id),h.payload.get("source", ""),{k:v for k,v in h.payload.items() if k not in {"text","chunk_id","source"}},score=h.score) for h in hits]
            except Exception: pass
        return super().search(vector,limit)

# Stable descriptive aliases for callers that prefer explicit backend names.
QdrantVectorStore = QdrantStore
PersistentVectorStore = LocalVectorStore
