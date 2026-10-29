from orbit_ai.rag import bm25_search, evidence_decision, reciprocal_rank_fusion, retrieve_advanced, validate_grounding


def test_bm25_ranks_relevant_document_first():
    corpus = [
        {"id": "a", "source": "plans.txt", "text": "The standard plan costs $12 per month."},
        {"id": "b", "source": "hours.txt", "text": "Customer support is open Monday through Friday."},
    ]
    hits = bm25_search("standard plan monthly cost", corpus)
    assert hits[0]["id"] == "a"


def test_rank_fusion_deduplicates_candidate_ids():
    a = {"id": "a", "text": "A", "source": "a.txt"}
    b = {"id": "b", "text": "B", "source": "b.txt"}
    fused = reciprocal_rank_fusion([[a, b], [a]])
    assert len([row for row in fused if row["id"] == "a"]) == 1
    assert fused[0]["id"] == "a"


def test_retrieve_advanced_keeps_actual_source_and_evidence():
    corpus = [{"id": "chunk-1", "source": "faq.txt", "text": "Plans cost $12 per month."}]
    result = retrieve_advanced("What do plans cost?", corpus, [])
    assert result["evidence"]
    assert result["evidence"][0]["source"] == "faq.txt"
    assert result["decision"]["status"] in {"SUPPORTED", "PARTIALLY_SUPPORTED"}


def test_numeric_grounding_flags_invented_price():
    evidence = [{"id": "c1", "source": "faq.txt", "text": "Plans cost $12 per month."}]
    verdict = validate_grounding("What do plans cost?", "Plans cost $99 per month.", evidence)
    assert verdict["ok"] is False
    assert "unsupported numeric claim" in verdict["reasons"]


def test_missing_evidence_is_not_supported():
    assert evidence_decision("What is the price?", []) == {
        "status": "NOT_SUPPORTED", "coverage": 0.0, "count": 0, "sources": 0, "sufficient": False
    }


def test_local_vector_rejects_dimension_change_without_deleting_existing_source(tmp_path):
    import asyncio
    from orbit_ai.providers import LocalVector

    async def scenario():
        vector = LocalVector(tmp_path / "vectors.json")
        await vector.replace_source("tenant-a", "first.txt", [{"id": "a1", "clientId": "tenant-a", "text": "one", "source": "first.txt", "embedding": [1.0, 0.0]}])
        await vector.replace_source("tenant-a", "second.txt", [{"id": "b1", "clientId": "tenant-a", "text": "two", "source": "second.txt", "embedding": [0.0, 1.0]}])
        try:
            await vector.replace_source("tenant-a", "first.txt", [{"id": "a2", "clientId": "tenant-a", "text": "changed", "source": "first.txt", "embedding": [1.0, 0.0, 0.0]}])
        except ValueError as exc:
            assert "dimensions changed" in str(exc)
        else:
            raise AssertionError("dimension mismatch should be rejected")
        rows = await vector.list_tenant("tenant-a")
        assert {row["id"] for row in rows} == {"a1", "b1"}

    asyncio.run(scenario())


def test_conflicting_prices_for_the_same_named_plan_are_uncertain():
    evidence = [
        {"id": "a", "source": "plans-a.txt", "text": "Orbit Standard plan costs $12 per month."},
        {"id": "b", "source": "plans-b.txt", "text": "Orbit Standard plan costs $15 per month."},
    ]
    decision = evidence_decision("What does the Orbit Standard plan cost per month?", evidence)
    assert decision["status"] == "UNCERTAIN"
    assert decision["sufficient"] is False
    assert decision["conflict"] is True


def test_conflict_detection_respects_product_and_billing_period():
    evidence = [
        {"id": "a", "source": "plans.txt", "text": "Orbit Standard plan costs $12 per month."},
        {"id": "b", "source": "plans.txt", "text": "Orbit Pro plan costs $18 per month."},
        {"id": "c", "source": "plans.txt", "text": "Orbit Standard annual plan costs $120 per year."},
    ]
    decision = evidence_decision("What does the Orbit Standard plan cost per month?", evidence)
    assert decision["sufficient"] is True
    assert decision.get("conflict") is not True



def test_local_vector_rejects_dimension_change_across_tenants_and_keeps_data(tmp_path):
    import asyncio
    from orbit_ai.providers import LocalVector

    async def scenario():
        path = tmp_path / "vectors.json"
        vector = LocalVector(path)
        await vector.replace_source("tenant-a", "a.txt", [{"id": "a1", "clientId": "tenant-a", "source": "a.txt", "text": "a", "embedding": [1.0, 0.0]}])
        try:
            await vector.replace_source("tenant-b", "b.txt", [{"id": "b1", "clientId": "tenant-b", "source": "b.txt", "text": "b", "embedding": [1.0, 0.0, 0.0]}])
        except ValueError as exc:
            assert "dimensions changed" in str(exc)
        else:
            raise AssertionError("mixing dimensions across tenants should be rejected")
        assert len(LocalVector(path).rows) == 1

    asyncio.run(scenario())


def test_rebuild_embedding_failure_preserves_existing_index(tmp_path):
    import asyncio
    from types import SimpleNamespace

    from orbit_ai.knowledge import KnowledgeService
    from orbit_ai.providers import LocalVector

    class Storage:
        async def list(self, tenant_id):
            return ["replacement.txt"]

        async def read(self, tenant_id, filename):
            return b"new content that would replace the existing index"

    class BrokenEmbedding:
        async def embed(self, texts):
            raise RuntimeError("simulated embedding outage")

    class Repo:
        def knowledge(self, tenant_id):
            return [{"filename": "replacement.txt", "size": 10, "chunks": 1, "status": "ready"}]

        def save_knowledge(self, *args):
            raise AssertionError("metadata must not be updated after embedding failure")

        def remove_knowledge(self, *args):
            raise AssertionError("metadata must not be changed after embedding failure")

    async def scenario():
        vector = LocalVector(tmp_path / "vectors.json")
        old = {"id": "old", "clientId": "tenant-a", "source": "replacement.txt", "text": "old indexed content", "embedding": [1.0, 0.0]}
        await vector.replace_source("tenant-a", "replacement.txt", [old])
        service = KnowledgeService(SimpleNamespace(), Repo(), Storage(), BrokenEmbedding(), vector)
        try:
            await service.rebuild("tenant-a")
        except RuntimeError as exc:
            assert "simulated embedding outage" in str(exc)
        else:
            raise AssertionError("embedding outage must abort a rebuild")
        assert await vector.list_tenant("tenant-a") == [{"id": "old", "text": "old indexed content", "source": "replacement.txt", "score": 0.0}]

    asyncio.run(scenario())
