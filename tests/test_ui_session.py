from contextlib import contextmanager
import sys
from types import SimpleNamespace

from advanced_rag.ui import run


class FakeService:
    def __init__(self):
        self.messages = []
        self.query_calls = []
        self.memory = SimpleNamespace(session_exists=lambda sid: sid == "session-1")

    def new_session(self):
        return "session-1"

    def session_history(self, sid):
        assert sid == "session-1"
        return list(self.messages)

    def query(self, question, session_id=None):
        self.query_calls.append((question, session_id))
        self.messages.extend([
            {"role": "user", "content": question, "metadata": {}},
            {"role": "assistant", "content": "Welcome! [Source 1]", "metadata": {"sources": [{"id": 1, "file": "docs.md"}]}},
        ])
        return {"session_id": session_id, "answer": "Welcome!"}

    def ingest(self):
        return {"changed": 0}


class FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.submissions = ["Hey", None]
        self.rendered = []
        self.buttons = []

    def columns(self, _widths):
        return FakeColumn(), FakeColumn()

    def button(self, label, **kwargs):
        self.buttons.append(label)
        return False

    def title(self, *args, **kwargs): pass
    def caption(self, *args, **kwargs): pass
    def markdown(self, value, *args, **kwargs): self.rendered.append(value)
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
    def success(self, *args, **kwargs): pass
    def json(self, *args, **kwargs): pass

    def chat_input(self, *args, **kwargs):
        return self.submissions.pop(0)

    def chat_message(self, role):
        self.rendered.append(f"ROLE:{role}")
        return FakeColumn()

    def expander(self, *args, **kwargs):
        return FakeColumn()

    @contextmanager
    def spinner(self, *args, **kwargs):
        yield

    def rerun(self):
        raise RuntimeError("rerun requested")


def test_ui_uses_persistent_history_and_processes_each_chat_submission_once(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    service = FakeService()

    try:
        run(service)
    except RuntimeError as exc:
        assert str(exc) == "rerun requested"
    else:
        raise AssertionError("a submitted chat message should request one rerun")

    run(service)
    assert service.query_calls == [("Hey", "session-1")]
    assert "ROLE:user" in fake_st.rendered
    assert "ROLE:assistant" in fake_st.rendered
    assert "Welcome! [Source 1]" in fake_st.rendered
    assert "＋ New chat" in fake_st.buttons
