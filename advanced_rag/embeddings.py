"""Embeddings with optional sentence-transformers and deterministic lexical fallback."""
import hashlib, math, re
class Embedder:
    def __init__(self, model="lexical", dimension=384):
        self.model_name=model; self.dimension=dimension; self._model=None
        if model not in ("", "lexical", "hash"):
            try:
                from sentence_transformers import SentenceTransformer
                self._model=SentenceTransformer(model); self.dimension=self._model.get_sentence_embedding_dimension()
            except Exception: self._model=None
    def embed(self, texts):
        texts=list(texts)
        if self._model is not None: return self._model.encode(texts, normalize_embeddings=True).tolist()
        return [self._hash_vector(t) for t in texts]
    def _hash_vector(self,text):
        v=[0.0]*self.dimension
        toks=re.findall(r"[\w-]+", text.lower())
        for tok in toks:
            digest=hashlib.sha256(tok.encode()).digest(); idx=int.from_bytes(digest[:4],"big")%self.dimension; sign=1 if digest[4]&1 else -1
            v[idx]+=sign*(1+math.log1p(len(tok)))
        norm=math.sqrt(sum(x*x for x in v)) or 1
        return [x/norm for x in v]
    def similarity(self,a,b): return sum(x*y for x,y in zip(a,b))
EmbeddingProvider=Embedder
