from advanced_rag.conversation_memory import ConversationMemory, SessionNotFoundError
from advanced_rag.llm import LLMResponse


def test_sessions_are_isolated_and_history_persists_across_instances(tmp_path):
    path = tmp_path / "chat.sqlite3"
    memory = ConversationMemory(path)
    first = memory.create_session()
    second = memory.create_session()
    memory.add_message(first, "user", "The AttachAI refund policy was discussed.")
    memory.add_message(first, "assistant", "The documents describe a refund window.")
    memory.add_message(second, "user", "Tell me about office locations.")

    reloaded = ConversationMemory(path)
    assert len(reloaded.list_messages(first)) == 2
    assert len(reloaded.list_messages(second)) == 1
    assert "refund" in reloaded.build_context(first, "refund", budget_chars=2000).lower()
    assert "refund" not in reloaded.build_context(second, "office", budget_chars=2000).lower()


def test_short_history_is_full_and_long_history_is_bounded(tmp_path):
    memory = ConversationMemory(tmp_path / "chat.sqlite3")
    sid = memory.create_session()
    memory.add_message(sid, "user", "My chosen product is AttachAI.")
    memory.add_message(sid, "assistant", "We will use AttachAI as the example.")
    short_context = memory.build_context(sid, "it", budget_chars=2000, full_history_threshold=8)
    assert "My chosen product is AttachAI." in short_context
    assert "We will use AttachAI as the example." in short_context

    for index in range(12):
        content = "Earlier important refund policy discussion for AttachAI." if index == 0 else f"Unrelated conversation message number {index}."
        memory.add_message(sid, "user" if index % 2 == 0 else "assistant", content)
    memory.maybe_update_summary(sid, full_history_threshold=4, recent_turns=1, max_summary_chars=350)
    long_context = memory.build_context(
        sid, "AttachAI refund policy", budget_chars=900, full_history_threshold=4,
        recent_turns=1, retrieval_top_k=3, max_summary_chars=350,
    )
    assert len(long_context) <= 900
    assert "Most recent conversation messages" in long_context
    assert "Earlier important refund policy discussion" in long_context or "refund policy" in long_context.lower()


def test_failed_summary_generation_falls_back_to_attributed_messages(tmp_path):
    class FailingLLM:
        def generate(self, prompt, **kwargs):
            return LLMResponse("LLM provider unavailable.", "mock", ok=False)

    memory = ConversationMemory(tmp_path / "chat.sqlite3")
    sid = memory.create_session()
    for i in range(10):
        memory.add_message(sid, "user" if i % 2 == 0 else "assistant", f"Message {i} preserves user/assistant attribution.")
    updated = memory.maybe_update_summary(sid, llm=FailingLLM(), remote_llm=True, full_history_threshold=4, recent_turns=1, max_summary_chars=500)
    summary, through = memory.get_summary(sid)
    assert updated
    assert summary
    assert "USER:" in summary or "ASSISTANT:" in summary
    assert through > 0


def test_unknown_session_is_not_silently_created(tmp_path):
    memory = ConversationMemory(tmp_path / "chat.sqlite3")
    try:
        memory.ensure_session("not-a-known-session")
    except SessionNotFoundError:
        pass
    else:
        raise AssertionError("unknown session ID should be rejected")
