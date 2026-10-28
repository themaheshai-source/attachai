from advanced_rag.ingestion import Chunk
from advanced_rag.retrieval import bm25_search, hybrid_retrieve
from advanced_rag.embeddings import Embedder
from advanced_rag.vector_store import LocalVectorStore

def test_hybrid_finds_exact_and_soft_domain():
    cs=[Chunk("The refund policy allows returns within thirty days.","1","refund.md"),Chunk("Our office is in Berlin.","2","about.txt")]
    assert hybrid_retrieve("refund policy",cs,k=1)[0].chunk_id=="1"

def test_small_kb_vector_fallback(tmp_path):
    e=Embedder(); s=LocalVectorStore(tmp_path/"v.json",embedder=e); cs=[Chunk("Python is a programming language.","1","x.txt")]; s.upsert(cs)
    assert hybrid_retrieve("programming language",cs,s,e,k=1,expand=False)[0].chunk_id=="1"


def test_multi_query_retrieval_fuses_variants_and_deduplicates_stable_ids():
    from advanced_rag.retrieval import multi_query_retrieve
    cs = [
        Chunk("AttachAI answers website visitor questions.", "same-id", "attachai.md"),
        Chunk("AttachAI answers website visitor questions.", "same-id", "attachai.md"),
        Chunk("The office is located in Berlin.", "other-id", "office.md"),
    ]
    found = multi_query_retrieve(
        "यह ग्राहकों की मदद कैसे करता है?",
        ["How does AttachAI help website visitors?", "AttachAI website assistant capabilities"],
        cs,
        k=3,
        normalized_query="How does AttachAI help website visitors?",
    )
    assert len({chunk.chunk_id for chunk in found}) == len(found)
    assert found[0].chunk_id == "same-id"
