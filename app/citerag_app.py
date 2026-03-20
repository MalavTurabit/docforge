import streamlit as st
import requests
from datetime import datetime

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="CiteRAG Lab",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Defaults ──────────────────────────────────────────────────
DEFAULTS = {
    "rag_messages":        [],
    "rag_inspector_open":  False,
    "rag_last_chunks":     [],
    "rag_sync_status":     None,
    "rag_history":         [],     # [{id, title, messages, chunks, created_at}]
    "rag_chat_title":      "New Chat",
    "rag_editing_title":   False,
    "rag_filter_industry": "All",
    "rag_filter_dept":     "All",   # department filter from /departments/
    "rag_rename_idx":      None,   # index of history item being renamed
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

INDUSTRIES = ["All", "IT & Security", "Finance", "Human Resources",
              "Product Management", "Engineering", "Legal & Compliance",
              "Sales & Marketing", "Business Ops"]

# ── Fetch industries from FastAPI ─────────────────────────────
def fetch_industries() -> list[str]:
    """Returns unique industry values from GET /rag/industries"""
    data, err = api("get", "/rag/industries")
    if err or not data:
        return []
    return data.get("industries", [])

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

def _save_current_chat():
    """Save the current chat to history before starting a new one."""
    msgs = st.session_state.rag_messages
    if not msgs:
        return
    title = st.session_state.rag_chat_title
    if title == "New Chat":
        first_q = next((m["content"] for m in msgs if m["role"] == "user"), "Chat")
        title = first_q[:46] + ("…" if len(first_q) > 46 else "")
    st.session_state.rag_history.insert(0, {
        "id":         datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "title":      title,
        "messages":   msgs.copy(),
        "chunks":     st.session_state.rag_last_chunks.copy(),
        "created_at": datetime.now().strftime("%b %d, %H:%M"),
    })

def _load_chat(idx: int):
    """Load a history item back into the active chat."""
    item = st.session_state.rag_history[idx]
    st.session_state.rag_messages    = item["messages"].copy()
    st.session_state.rag_last_chunks = item["chunks"].copy()
    st.session_state.rag_chat_title  = item["title"]
    st.session_state.rag_editing_title = False

# ── Sidebar ───────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        # App switcher
        choice = st.selectbox(
            "Change App",
            ["🔍  CiteRAG Lab", "📋  DocForge"],
            index=0, key="app_sw")
        if choice == "📋  DocForge":
            st.markdown('<meta http-equiv="refresh" content="0;url=http://localhost:8501">',
                        unsafe_allow_html=True)
            st.stop()

        st.divider()
        st.subheader("🔍 CiteRAG Lab")

        # ── Sync ──────────────────────────────────────────────
        if st.button("⚡ Sync Knowledge Base", use_container_width=True, key="sync_btn"):
            with st.spinner("Syncing…"):
                data, err = api("post", "/sync/run")
            st.session_state.rag_sync_status = "error" if err else "ok"
            st.rerun()
        if st.session_state.rag_sync_status == "ok":
            st.success("✓ Synced")
        elif st.session_state.rag_sync_status == "error":
            st.error("Sync failed")

        # ── New Chat ──────────────────────────────────────────
        if st.button("＋ New Chat", use_container_width=True, key="new_chat_btn"):
            _save_current_chat()
            st.session_state.rag_messages      = []
            st.session_state.rag_last_chunks   = []
            st.session_state.rag_chat_title    = "New Chat"
            st.session_state.rag_editing_title = False
            st.rerun()

        # ── Filters ───────────────────────────────────────────
        st.divider()
        st.caption("**Filters**")

        # Industry/Department filter — fetched live from Milvus via API
        industries  = fetch_industries()
        ind_options = ["All"] + industries

        cur_dept = st.session_state.rag_filter_dept
        if cur_dept not in ind_options:
            cur_dept = "All"

        st.session_state.rag_filter_dept = st.selectbox(
            "Department", ind_options,
            index=ind_options.index(cur_dept),
            key="fil_dept")


        # ── Inspector toggle ──────────────────────────────────
        st.divider()
        st.session_state.rag_inspector_open = st.toggle(
            "Retrieval Inspector",
            value=st.session_state.rag_inspector_open,
            key="insp_tog")

        # ── Status ────────────────────────────────────────────
        st.divider()
        st.caption("**Status**")
        status_data, _ = api("get", "/rag/status")
        if status_data:
            milvus_ok  = status_data.get("milvus_connected", False)
            count      = status_data.get("docs_indexed", 0)
            milvus_str = ":green[connected]" if milvus_ok else ":orange[not connected]"
            st.caption(f"🗄 Milvus — {milvus_str}")
            st.caption(f"📚 Docs indexed — {count}")
        else:
            st.caption("🗄 Milvus — :orange[not connected]")
            st.caption("📚 Docs indexed — :orange[0]")

        # ── Chat History ──────────────────────────────────────
        st.divider()
        st.caption("**Chat History**")
        history = st.session_state.rag_history

        if not history:
            st.caption("_No previous chats yet._")
        else:
            for i, item in enumerate(history[:20]):
                # Rename mode for this item
                if st.session_state.rag_rename_idx == i:
                    new_title = st.text_input(
                        "Rename", value=item["title"],
                        key=f"rename_input_{i}", label_visibility="collapsed")
                    c1, c2 = st.columns(2, gap="small")
                    with c1:
                        if st.button("✓ Save", key=f"rename_save_{i}", use_container_width=True):
                            st.session_state.rag_history[i]["title"] = new_title.strip() or item["title"]
                            st.session_state.rag_rename_idx = None
                            st.rerun()
                    with c2:
                        if st.button("✕", key=f"rename_cancel_{i}", use_container_width=True):
                            st.session_state.rag_rename_idx = None
                            st.rerun()
                else:
                    # Normal display
                    label = item.get("title", "Chat")
                    meta  = item.get("created_at", "")

                    # Load button
                    if st.button(f"💬 {label}", key=f"load_chat_{i}",
                                 use_container_width=True, help=meta):
                        _load_chat(i)
                        st.rerun()

                    # Rename + Delete inline
                    rc1, rc2 = st.columns(2, gap="small")
                    with rc1:
                        if st.button("✏️ Rename", key=f"rename_btn_{i}",
                                     use_container_width=True):
                            st.session_state.rag_rename_idx = i
                            st.rerun()
                    with rc2:
                        if st.button("🗑 Delete", key=f"delete_btn_{i}",
                                     use_container_width=True):
                            st.session_state.rag_history.pop(i)
                            st.rerun()


# ── Main page ─────────────────────────────────────────────────
RAG_SUGGESTIONS = [
    "What are the key risks in the Security Risk Assessment?",
    "What financial controls are in place?",
    "Summarise the incident response process",
    "What compliance requirements appear across all policies?",
    "What vulnerabilities were identified in IT infrastructure?",
]

def page_chat():
    messages  = st.session_state.rag_messages
    inspector = st.session_state.rag_inspector_open
    dept      = st.session_state.rag_filter_dept

    # ── Chat title bar ────────────────────────────────────────
    t_col, e_col = st.columns([8, 1], gap="small")
    with t_col:
        if st.session_state.rag_editing_title:
            new_t = st.text_input("Title", value=st.session_state.rag_chat_title,
                                  key="chat_title_input", label_visibility="collapsed")
        else:
            st.subheader(st.session_state.rag_chat_title)
    with e_col:
        if st.session_state.rag_editing_title:
            if st.button("✓", key="title_save"):
                st.session_state.rag_chat_title    = new_t.strip() or "New Chat"
                st.session_state.rag_editing_title = False
                st.rerun()
        else:
            if st.button("✏️", key="title_edit"):
                st.session_state.rag_editing_title = True
                st.rerun()

    # ── Active filters display ────────────────────────────────
    dept = st.session_state.rag_filter_dept
    if dept != "All":
        st.caption(f"Filters active: 🏢 {dept}")

    st.divider()

    # ── Layout ────────────────────────────────────────────────
    if inspector:
        chat_col, insp_col = st.columns([3, 2], gap="large")
    else:
        chat_col = st.container()
        insp_col = None

    with chat_col:
        if not messages:
            st.write("")
            col_l, col_c, col_r = st.columns([1, 4, 1])
            with col_c:
                st.markdown("## 🔍 Ask anything about your document library")
                st.caption("Answers grounded in your Notion docs with source citations")
                st.write("")
                b1, b2 = st.columns(2, gap="small")
                b3, b4 = st.columns(2, gap="small")
                _, b5, _ = st.columns([1, 2, 1], gap="small")
                for col, q, key in [
                    (b1, RAG_SUGGESTIONS[0], "s0"),
                    (b2, RAG_SUGGESTIONS[1], "s1"),
                    (b3, RAG_SUGGESTIONS[2], "s2"),
                    (b4, RAG_SUGGESTIONS[3], "s3"),
                    (b5, RAG_SUGGESTIONS[4], "s4"),
                ]:
                    with col:
                        if st.button(q, key=key, use_container_width=True):
                            st.session_state.rag_messages.append(
                                {"role":"user","content":q,"sources":[]})
                            with st.spinner("Searching docs…"):
                                data, err = api("post", "/rag/chat", json={
                                    "query":    q,
                                    "top_k":    5,
                                    "industry": None if dept == "All" else dept,
                                })
                            if err:
                                st.session_state.rag_messages.append(
                                    {"role":"assistant","content":f"❌ {err}","sources":[]})
                            else:
                                st.session_state.rag_messages.append({
                                    "role":    "assistant",
                                    "content": data["answer"],
                                    "sources": data["sources"],
                                })
                                st.session_state.rag_last_chunks = data.get("chunks", [])
                                # Auto-set title from first question
                                if st.session_state.rag_chat_title == "New Chat":
                                    st.session_state.rag_chat_title = q[:46] + ("…" if len(q) > 46 else "")
                            st.rerun()
        else:
            for msg in messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
                    sources = msg.get("sources", [])
                    if sources:
                        st.caption("Sources: " + " · ".join(f"📄 {s}" for s in sources))

    # ── Inspector ─────────────────────────────────────────────
    if insp_col:
        with insp_col:
            st.subheader("🔎 Retrieval Inspector")
            chunks = st.session_state.rag_last_chunks
            if not chunks:
                st.info("Ask a question to see retrieved chunks.")
            else:
                for i, c in enumerate(chunks, 1):
                    doc_t = c.get("doc_title", "Unknown")
                    sec   = c.get("section_heading", "")
                    score = c.get("score", 0)
                    text  = c.get("raw_text", "")
                    meta  = f"{doc_t} → {sec}" if sec else doc_t
                    with st.expander(f"#{i} · {meta}  —  {score:.3f}"):
                        st.caption(text[:300] + ("…" if len(text) > 300 else ""))

    # ── Chat input ────────────────────────────────────────────
    dept = st.session_state.rag_filter_dept
    hint = f" [{dept}]" if dept != "All" else ""
    user_input = st.chat_input(f"Ask a question about your docs{hint}…")
    if user_input:
        st.session_state.rag_messages.append(
            {"role":"user","content":user_input,"sources":[]})
        dept = st.session_state.rag_filter_dept
        with st.spinner("Searching docs and generating answer…"):
            data, err = api("post", "/rag/chat", json={
                "query":    user_input,
                "top_k":    5,
                "industry": None if dept == "All" else dept,
            })
        if err:
            st.session_state.rag_messages.append(
                {"role":"assistant","content":f"❌ Error: {err}","sources":[]})
        else:
            st.session_state.rag_messages.append({
                "role":    "assistant",
                "content": data["answer"],
                "sources": data["sources"],
            })
            st.session_state.rag_last_chunks = data.get("chunks", [])
            # Auto-set title from first user message
            if st.session_state.rag_chat_title == "New Chat":
                st.session_state.rag_chat_title = user_input[:46] + ("…" if len(user_input) > 46 else "")
        st.rerun()


# ── Run ───────────────────────────────────────────────────────
render_sidebar()
page_chat()