import streamlit as st
import requests

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="CiteRAG Lab",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Defaults ──────────────────────────────────────────────────
DEFAULTS = {
    "rag_messages":       [],
    "rag_inspector_open": False,
    "rag_last_chunks":    [],
    "rag_sync_status":    None,
    "rag_history":        [],
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── API helper ────────────────────────────────────────────────
def api(method, path, **kwargs):
    try:
        r = getattr(requests, method)(f"{API_BASE}{path}", timeout=60, **kwargs)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Cannot connect to API"
    except requests.exceptions.HTTPError as e:
        try:    d = e.response.json().get("detail", str(e))
        except: d = str(e)
        return None, d
    except Exception as e:
        return None, str(e)

# ── Sidebar ───────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        # App switcher
        choice = st.selectbox(
            "Change App",
            ["🔍  CiteRAG Lab", "📋  DocForge"],
            index=0,
            key="app_sw")
        if choice == "📋  DocForge":
            st.markdown('<meta http-equiv="refresh" content="0;url=http://localhost:8501">',
                        unsafe_allow_html=True)
            st.stop()

        st.divider()
        st.subheader("🔍 CiteRAG Lab")

        # Sync
        if st.button("⚡ Sync Knowledge Base", use_container_width=True, key="sync_btn"):
            with st.spinner("Syncing…"):
                data, err = api("post", "/sync/run")
            if err:
                st.session_state.rag_sync_status = "error"
            else:
                st.session_state.rag_sync_status = "ok"
            st.rerun()
        if st.session_state.rag_sync_status == "ok":
            st.success("✓ Synced")

        # New Chat
        if st.button("＋ New Chat", use_container_width=True, key="new_chat_btn"):
            msgs = st.session_state.rag_messages
            if msgs:
                first_q = next((m["content"] for m in msgs if m["role"] == "user"), "Chat")
                st.session_state.rag_history.insert(0, {
                    "label": first_q[:46] + ("…" if len(first_q) > 46 else ""),
                    "messages": msgs.copy(),
                    "chunks": st.session_state.rag_last_chunks.copy(),
                })
            st.session_state.rag_messages    = []
            st.session_state.rag_last_chunks = []
            st.rerun()

        # Inspector toggle
        st.session_state.rag_inspector_open = st.toggle(
            "Retrieval Inspector",
            value=st.session_state.rag_inspector_open,
            key="insp_tog")

        st.divider()

        # Status
        st.caption("**Status**")
        status_data, _ = api("get", "/rag/status")
        if status_data:
            milvus_ok = status_data.get("milvus_connected", False)
            count     = status_data.get("docs_indexed", 0)
            milvus_str = ":green[connected]" if milvus_ok else ":orange[not connected]"
            st.caption(f"🗄 Milvus — {milvus_str}")
            st.caption(f"📚 Docs indexed — {count}")
        else:
            st.caption("🗄 Milvus — :orange[not connected]")
            st.caption("📚 Docs indexed — :orange[0]")

        st.divider()

        # Chat history
        st.caption("**Chat History**")
        history = st.session_state.rag_history
        if not history:
            st.caption("_No previous chats yet._")
        else:
            for i, item in enumerate(history[:20]):
                label = item.get("label", "Chat")
                st.caption(f"💬 {label}")


# ── Suggestion buttons ────────────────────────────────────────
RAG_SUGGESTIONS = [
    "What are the key risks in the Security Risk Assessment?",
    "What financial controls are in place?",
    "Summarise the incident response process",
    "What compliance requirements appear across all policies?",
    "What vulnerabilities were identified in IT infrastructure?",
]

def _fire_suggestion(q: str):
    st.session_state.rag_messages.append({"role": "user", "content": q, "sources": []})
    st.session_state.rag_messages.append({
        "role": "assistant",
        "content": "⚠️ Backend not connected yet — wire `POST /rag/chat` to get real answers.",
        "sources": []})
    st.rerun()


# ── Main page ─────────────────────────────────────────────────
def page_chat():
    messages  = st.session_state.rag_messages
    inspector = st.session_state.rag_inspector_open

    if inspector:
        chat_col, insp_col = st.columns([3, 2], gap="large")
    else:
        chat_col = st.container()
        insp_col = None

    with chat_col:
        if not messages:
            # Empty state
            st.write("")
            st.write("")
            col_l, col_c, col_r = st.columns([1, 4, 1])
            with col_c:
                st.markdown("## 🔍 Ask anything about your document library")
                st.caption("Answers grounded in your Notion docs with source citations")
                st.write("")

                # Suggestion buttons
                b1, b2 = st.columns(2, gap="small")
                b3, b4 = st.columns(2, gap="small")
                _, b5, _ = st.columns([1, 2, 1], gap="small")

                with b1:
                    if st.button(RAG_SUGGESTIONS[0], key="s0", use_container_width=True):
                        _fire_suggestion(RAG_SUGGESTIONS[0])
                with b2:
                    if st.button(RAG_SUGGESTIONS[1], key="s1", use_container_width=True):
                        _fire_suggestion(RAG_SUGGESTIONS[1])
                with b3:
                    if st.button(RAG_SUGGESTIONS[2], key="s2", use_container_width=True):
                        _fire_suggestion(RAG_SUGGESTIONS[2])
                with b4:
                    if st.button(RAG_SUGGESTIONS[3], key="s3", use_container_width=True):
                        _fire_suggestion(RAG_SUGGESTIONS[3])
                with b5:
                    if st.button(RAG_SUGGESTIONS[4], key="s4", use_container_width=True):
                        _fire_suggestion(RAG_SUGGESTIONS[4])

        else:
            # Render chat messages using native st.chat_message
            for msg in messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
                    sources = msg.get("sources", [])
                    if sources:
                        st.caption("Sources: " + " · ".join(f"📄 {s}" for s in sources))

    # Inspector panel
    if insp_col:
        with insp_col:
            st.subheader("🔎 Retrieval Inspector")
            chunks = st.session_state.rag_last_chunks
            if not chunks:
                st.info("Ask a question to see retrieved chunks.")
            else:
                for i, c in enumerate(chunks, 1):
                    doc   = c.get("doc_title", "Unknown")
                    sec   = c.get("section_heading", "")
                    score = c.get("score", 0)
                    text  = c.get("raw_text", "")
                    meta  = f"{doc} → {sec}" if sec else doc
                    with st.expander(f"#{i} · {meta}  —  {score:.3f}"):
                        st.caption(text[:300] + ("…" if len(text) > 300 else ""))

    # Chat input
    user_input = st.chat_input("Ask a question about your docs…")
    if user_input:
        st.session_state.rag_messages.append({"role":"user","content":user_input,"sources":[]})
        # Call real RAG backend
        with st.spinner("Searching docs and generating answer…"):
            data, err = api("post", "/rag/chat", json={
                "query": user_input,
                "top_k": 5,
            })

        if err:
            st.session_state.rag_messages.append({
                "role":    "assistant",
                "content": f"❌ Error: {err}",
                "sources": []
            })
        else:
            st.session_state.rag_messages.append({
                "role":    "assistant",
                "content": data["answer"],
                "sources": data["sources"],
            })
            st.session_state.rag_last_chunks = data.get("chunks", [])
        st.rerun()


# ── Run ───────────────────────────────────────────────────────
render_sidebar()
page_chat()