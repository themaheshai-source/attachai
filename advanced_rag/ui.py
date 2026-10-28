"""Streamlit conversational UI backed by durable SQLite session history."""


def run(rag=None):
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Install streamlit to use the UI") from exc
    try:
        from .app import RAGApp
    except ImportError:
        from advanced_rag.app import RAGApp

    if "rag_service" not in st.session_state:
        st.session_state["rag_service"] = rag or RAGApp()
    service = st.session_state["rag_service"]

    if not st.session_state.get("active_session_id") or not service.memory.session_exists(st.session_state["active_session_id"]):
        st.session_state["active_session_id"] = service.new_session()

    st.title("AttachAI")
    st.caption("Persistent, session-based document chat with grounded citations")

    action_col, ingest_col = st.columns([1, 2])
    with action_col:
        if st.button("＋ New chat", use_container_width=True):
            st.session_state["active_session_id"] = service.new_session()
            st.rerun()
    with ingest_col:
        if st.button("Ingest / refresh knowledge", use_container_width=True):
            with st.spinner("Refreshing the knowledge base…"):
                try:
                    stats = service.ingest()
                    st.success("Knowledge base refreshed.")
                    st.json(stats)
                except Exception:
                    st.error("Ingestion failed. Check the server-side configuration and knowledge files.")

    active_session_id = st.session_state["active_session_id"]
    st.caption(f"Session: {active_session_id[:8]}…")
    history = service.session_history(active_session_id)
    for message in history:
        role = message["role"] if message["role"] in {"user", "assistant"} else "assistant"
        with st.chat_message(role):
            st.markdown(message["content"])
            if role == "assistant":
                metadata = message.get("metadata") or {}
                source_list = metadata.get("sources") or []
                if source_list:
                    with st.expander("Sources", expanded=False):
                        for source in source_list:
                            label = f"[Source {source.get('id', '?')}] {source.get('file', source.get('source', 'unknown source'))}"
                            page = source.get("page")
                            section = source.get("section")
                            details = []
                            if page is not None:
                                details.append(f"page {page}")
                            if section:
                                details.append(str(section))
                            st.markdown(f"- **{label}**" + (f" — {', '.join(details)}" if details else ""))
                status = metadata.get("generation_status")
                if status == "fallback":
                    st.caption("Offline conversational fallback")
                elif status == "failed":
                    st.caption("Model generation failed")

    question = st.chat_input("Ask a question about your documents…")
    if question is not None:
        if not question.strip():
            st.warning("Please enter a question.")
            return
        try:
            with st.spinner("Searching documents and preparing an answer…"):
                service.query(question, session_id=active_session_id)
        except Exception:
            st.error("The message could not be processed. Please check the backend configuration and try again.")
            return
        # Keep rerun outside the broad exception handler: Streamlit implements rerun
        # by raising an internal control-flow exception which must not be swallowed.
        st.rerun()


if __name__ == "__main__":
    run()
