import json

from advanced_rag.app import RAGApp
from advanced_rag.config import Settings
from advanced_rag.ingestion import Chunk
from advanced_rag.llm import LLMResponse
from advanced_rag.profiling import profile
from advanced_rag.query_understanding import QueryUnderstandingService


class SequenceLLM:
    def __init__(self, structured=None, answer="AttachAI answers website visitors' questions. [Source 1]"):
        self.structured = structured
        self.answer = answer
        self.calls = []

    def generate(self, prompt, **kwargs):
        self.calls.append(prompt)
        if "You are a query-understanding component" in prompt:
            return LLMResponse(json.dumps(self.structured or {}), "mock-model")
        if "Update the concise rolling summary" in prompt:
            return LLMResponse("Summary of conversation with role attribution.", "mock-model")
        return LLMResponse(self.answer, "mock-model")


def make_app(tmp_path, provider="none"):
    settings = Settings.from_env(
        knowledge_dir=tmp_path / "knowledge",
        data_dir=tmp_path / "data",
        conversation_db_path=tmp_path / "data" / "memory.sqlite3",
        embedding_model="lexical",
        llm_provider=provider,
        query_understanding_enabled=True,
        partial_recovery_threshold=0.35,
        chat_full_history_threshold=4,
        chat_recent_turns=2,
    )
    app = RAGApp(settings)
    app.chunks = [Chunk(
        "AttachAI is a personalized AI assistant for a business website. It answers website visitors' questions and helps customers find information.",
        "chunk-1", "attachai.md",
    )]
    app.profile_data = profile(app.chunks)
    return app


def test_supported_query_skips_query_understanding(tmp_path):
    app = make_app(tmp_path)
    app.query_understanding.understand = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not rewrite supported query"))
    result = app.query("What does the website assistant do?")
    assert result["status"] == "SUPPORTED"
    assert result["session_id"]
    assert result["sources"][0]["file"] == "attachai.md"
    assert len(app.session_history(result["session_id"])) == 2


def test_hindi_follow_up_recovers_english_evidence_and_cites_source(tmp_path):
    app = make_app(tmp_path, provider="openai")
    structured = {
        "intent": "follow_up_question",
        "normalized_question": "How does AttachAI help website visitors?",
        "input_language": "Hindi (Devanagari)",
        "knowledge_base_language": "English",
        "entities": ["AttachAI"],
        "keywords": ["website assistant", "visitor questions", "customer help"],
        "query_variants": [
            "AttachAI website assistant capabilities",
            "How AttachAI answers website visitors' questions",
            "AttachAI helps customers find information",
        ],
        "information_need": "Find how the assistant helps website visitors",
    }
    fake = SequenceLLM(structured)
    app.llm = fake
    app.query_understanding = QueryUnderstandingService(fake, enabled=True, max_variants=4, provider="openai")
    sid = app.new_session()
    app.memory.add_message(sid, "user", "What is AttachAI?")
    app.memory.add_message(sid, "assistant", "AttachAI is a personalized AI assistant for a business website.")
    result = app.query("यह ग्राहकों की सहायता कैसे करता है?", session_id=sid)
    assert app.last_debug["recovered"]
    assert app.last_debug["query_understanding"]["used_llm"]
    assert result["status"] == "SUPPORTED"
    assert "[Source 1]" in result["answer"]
    assert result["sources"][0]["file"] == "attachai.md"
    assert result["session_id"] == sid


def test_greeting_works_without_knowledge_base_or_remote_llm(tmp_path):
    app = make_app(tmp_path)
    app.chunks = []
    app.profile_data = {}
    result = app.query("Hi")
    assert result["status"] == "CONVERSATIONAL"
    assert result["model"] == "local-rule-fallback"
    assert "Hello" in result["answer"]
    assert result["sources"] == []


def test_unsupported_policy_does_not_generate_factual_answer(tmp_path):
    app = make_app(tmp_path, provider="openai")
    structured = {
        "intent": "information_seeking",
        "normalized_question": "Does AttachAI offer refunds for annual subscriptions?",
        "input_language": "English",
        "knowledge_base_language": "English",
        "entities": ["AttachAI"],
        "keywords": ["refund", "annual subscription"],
        "query_variants": ["AttachAI annual subscription refund policy"],
        "information_need": "Find documented refund terms for annual subscriptions",
    }
    fake = SequenceLLM(structured, answer="It offers a full refund. [Source 1]")
    app.llm = fake
    app.query_understanding = QueryUnderstandingService(fake, enabled=True, max_variants=4, provider="openai")
    result = app.query("Does AttachAI offer refunds for annual subscriptions?")
    assert result["status"] in {"PARTIALLY_SUPPORTED", "UNCERTAIN", "NOT_SUPPORTED"}
    assert "not found" in result["answer"].lower() or "not establish" in result["answer"].lower()
    # One call was the query-rewrite pass; no final factual-answer generation happened.
    assert len(fake.calls) == 1


def test_provider_failure_is_not_reported_as_successful_generation(tmp_path):
    app = make_app(tmp_path)
    class FailedLLM:
        def generate(self, prompt, **kwargs):
            return LLMResponse("LLM provider unavailable.", "mock", ok=False)
    app.llm = FailedLLM()
    result = app.query("What does the website assistant do?")
    assert result["generation_status"] == "failed"
    assert result["model"] == "unavailable"
    assert "LLM provider unavailable" not in result["answer"]


def test_disabled_query_understanding_uses_legacy_expansion_without_remote_rewrite(tmp_path):
    settings = Settings.from_env(
        knowledge_dir=tmp_path / "knowledge",
        data_dir=tmp_path / "data",
        conversation_db_path=tmp_path / "data" / "memory.sqlite3",
        embedding_model="lexical",
        llm_provider="openai",
        query_understanding_enabled=False,
    )
    app = RAGApp(settings)
    app.chunks = [Chunk("AttachAI is a website assistant that answers visitor questions.", "chunk-1", "attachai.md")]
    app.profile_data = profile(app.chunks)

    class RecordingLLM:
        def __init__(self): self.calls = []
        def generate(self, prompt, **kwargs):
            self.calls.append(prompt)
            return LLMResponse("It provides refunds. [Source 1]", "mock-model")

    fake = RecordingLLM()
    app.llm = fake
    result = app.query("Does AttachAI offer refunds for annual subscriptions?")
    assert fake.calls == []
    assert "not found" in result["answer"].lower() or "not establish" in result["answer"].lower()
