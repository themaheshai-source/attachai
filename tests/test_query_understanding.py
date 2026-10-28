import json
from types import SimpleNamespace

from advanced_rag.query_understanding import QueryUnderstandingService, detect_language, infer_knowledge_language
from advanced_rag.ingestion import Chunk
from advanced_rag.llm import LLMResponse


class FakeLLM:
    def __init__(self, text, ok=True):
        self.text = text
        self.ok = ok
        self.calls = []

    def generate(self, prompt, **kwargs):
        self.calls.append(prompt)
        return LLMResponse(self.text, "mock-model", ok=self.ok)


def test_structured_hinglish_rewrite_uses_multiple_distinct_variants():
    payload = {
        "intent": "information_seeking",
        "normalized_question": "What does AttachAI do on a business website?",
        "input_language": "Hinglish",
        "knowledge_base_language": "English",
        "entities": ["AttachAI"],
        "keywords": ["website assistant", "visitor questions"],
        "query_variants": [
            "AttachAI business website capabilities",
            "How AttachAI answers website visitors' questions",
            "AttachAI personalized AI assistant services",
        ],
        "information_need": "Find website assistant features and customer benefits",
    }
    llm = FakeLLM(json.dumps(payload))
    service = QueryUnderstandingService(llm, enabled=True, max_variants=4, provider="openai")
    result = service.understand("AttachAI website pe kya karta hai?", chunks=[Chunk("AttachAI helps visitors.", "1", "docs.md")])
    assert result.intent == "information_seeking"
    assert result.normalized_question.startswith("What does AttachAI")
    assert "AttachAI" in result.entities
    assert len(result.query_variants) <= 4
    assert len({q.casefold() for q in result.query_variants}) == len(result.query_variants)
    assert result.used_llm
    assert len(llm.calls) == 1


def test_malformed_json_and_provider_failure_fall_back_safely():
    malformed = QueryUnderstandingService(FakeLLM("not json"), provider="openai")
    result = malformed.understand("What about refunds?", history=[{"role": "user", "content": "What is AttachAI?"}])
    assert result.intent == "follow_up_question"
    assert result.query_variants
    assert not result.used_llm

    failed = QueryUnderstandingService(FakeLLM("LLM provider unavailable.", ok=False), provider="openai")
    safe_result = failed.understand("क्या यह ग्राहकों की मदद करता है?")
    assert safe_result.query_variants
    assert not safe_result.used_llm


def test_language_detection_uses_message_and_indexed_content():
    assert "Hindi" in detect_language("क्या यह काम करता है?")
    assert "Hinglish" in detect_language("ye website pe kaise kaam karta hai")
    assert "English" in infer_knowledge_language([Chunk("The service and the website are available for your customers.", "1", "x.md")])


def test_local_mode_does_not_call_llm_for_understanding():
    llm = FakeLLM('{"intent":"greeting"}')
    service = QueryUnderstandingService(llm, enabled=True, provider="none")
    result = service.understand("Hello")
    assert result.intent == "greeting"
    assert llm.calls == []


def test_substantive_policy_question_is_not_downgraded_to_small_talk():
    payload = {
        "intent": "thanks",
        "normalized_question": "What is the refund policy?",
        "input_language": "English",
        "knowledge_base_language": "English",
        "entities": [],
        "keywords": ["refund policy"],
        "query_variants": ["refund policy"],
        "information_need": "Find the documented refund policy",
    }
    service = QueryUnderstandingService(FakeLLM(json.dumps(payload)), provider="openai")
    result = service.understand("Thanks, and what about refunds?", history=[{"role": "user", "content": "What services do you provide?"}])
    assert result.intent == "follow_up_question"
