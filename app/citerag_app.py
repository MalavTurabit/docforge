import streamlit as st
import requests
import logging
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

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
    "rag_history":         [],
    "rag_chat_title":      "New Chat",
    "rag_editing_title":   False,
    "rag_filter_industry": "All",
    "rag_filter_dept":     "All",
    "_cached_industries":  None,
    "_cached_status":      None,
    "rag_last_scores":     None,
    "rag_editing_idx":     None,
    "rag_edit_text":       "",
    "rag_rename_idx":      None,
    # New
    "rag_last_ticket":       None,
    "rag_tickets_filter":    "All",
    "rag_eval_scores":       None,
    "rag_eval_query":        "",
    "rag_session_id":        None,
    "rag_pending_tickets":    [],
    "rag_awaiting_selection": False,
    "rag_last_created_ticket": None,
    "rag_current_chat_id":    None,  # ID of currently open chat in history
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Auto-generate session ID if not set
if not st.session_state.rag_session_id:
    import uuid
    st.session_state.rag_session_id = str(uuid.uuid4())


# ── API helper ────────────────────────────────────────────────
def api(method, path, **kwargs):
    try:
        r = getattr(requests, method)(f"{API_BASE}{path}", timeout=180, **kwargs)
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


def fetch_industries() -> list[str]:
    if st.session_state._cached_industries is not None:
        return st.session_state._cached_industries
    data, err = api("get", "/rag/industries")
    result = data.get("industries", []) if (data and not err) else []
    st.session_state._cached_industries = result
    return result


def fetch_rag_status() -> dict:
    if st.session_state._cached_status is not None:
        return st.session_state._cached_status
    data, _ = api("get", "/rag/status")
    result = data or {}
    st.session_state._cached_status = result
    return result


def _save_current_chat():
    msgs = st.session_state.rag_messages
    if not msgs:
        return
    title = st.session_state.rag_chat_title
    if title == "New Chat":
        first_q = next((m["content"] for m in msgs if m["role"] == "user"), "Chat")
        title = first_q[:46] + ("…" if len(first_q) > 46 else "")

    # Update existing entry if already saved
    chat_id = st.session_state.get("rag_current_chat_id")
    if chat_id:
        for i, item in enumerate(st.session_state.rag_history):
            if item.get("id") == chat_id:
                st.session_state.rag_history[i]["messages"] = msgs.copy()
                st.session_state.rag_history[i]["chunks"]   = st.session_state.rag_last_chunks.copy()
                st.session_state.rag_history[i]["title"]    = title
                return

    # New entry
    new_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    st.session_state.rag_current_chat_id = new_id
    st.session_state.rag_history.insert(0, {
        "id":         new_id,
        "title":      title,
        "messages":   msgs.copy(),
        "chunks":     st.session_state.rag_last_chunks.copy(),
        "created_at": datetime.now().strftime("%b %d, %H:%M"),
    })


def _load_chat(idx: int):
    item = st.session_state.rag_history[idx]
    st.session_state.rag_messages    = item["messages"].copy()
    st.session_state.rag_last_chunks = item["chunks"].copy()
    st.session_state.rag_chat_title  = item["title"]
    st.session_state.rag_editing_title = False


def _build_history_payload() -> list[dict]:
    msgs = st.session_state.rag_messages
    history = []
    for m in msgs[-6:]:
        role    = m.get("role", "user")
        content = m.get("content", "")
        if role in ("user", "assistant") and content.strip():
            history.append({"role": role, "content": content})
    return history


def _is_ticket_confirmation(text: str) -> bool:
    """
    Use LLM to detect if the user wants to confirm ticket creation.
    Makes a direct Azure OpenAI call — no app module imports needed.
    """
    try:
        from openai import AzureOpenAI
        import os
        client = AzureOpenAI(
            api_key       = os.getenv("AZURE_OPENAI_LLM_KEY"),
            azure_endpoint= os.getenv("AZURE_LLM_ENDPOINT"),
            api_version   = os.getenv("AZURE_LLM_API_VERSION", "2024-02-01"),
        )
        deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI", "gpt-4o-mini")
        prompt = (
            f"The user was just asked: 'Would you like me to raise a support ticket?'\n"
            f"Their reply was: \"{text.strip()}\"\n\n"
            f"Does their reply mean YES they want the ticket created?\n"
            f"Consider any affirmative, agreement, or ticket-related intent as YES.\n"
            f"Consider new questions, greetings, or unrelated replies as NO.\n\n"
            f"Answer with exactly one word: YES or NO."
        )
        resp = client.chat.completions.create(
            model      = deployment,
            messages   = [{"role": "user", "content": prompt}],
            temperature= 0,
            max_tokens = 5,
        )
        result = resp.choices[0].message.content.strip().upper()
        confirmed = result.startswith("YES")
        logging.info(f"[confirm_check] input='{text}' llm='{result}' confirmed={confirmed}")
        return confirmed
    except Exception as e:
        logging.error(f"[confirm_check] failed: {e}")
        return False


def _detect_ticket_update(text: str) -> dict | None:
    """
    Detect if user wants to update the last created ticket's PRIORITY.
    Status can only be changed by the team in Notion — never from chat.
    Returns {priority} if update detected, None otherwise.
    """
    text_lower = text.strip().lower()

    # Fast reject — short ambiguous words that are NOT update requests
    ambiguous = {"done", "ok", "okay", "thanks", "thank you", "got it", "noted",
                 "yes", "no", "sure", "fine", "good", "great", "cool", "alright"}
    if text_lower in ambiguous:
        return None

    # Must contain explicit priority-related keywords
    priority_keywords = ["priority", "urgent", "high", "medium", "low",
                         "update priority", "change priority", "modify priority", "set priority"]
    if not any(kw in text_lower for kw in priority_keywords):
        return None

    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key        = os.getenv("AZURE_OPENAI_LLM_KEY"),
            azure_endpoint = os.getenv("AZURE_LLM_ENDPOINT"),
            api_version    = os.getenv("AZURE_LLM_API_VERSION", "2024-02-01"),
        )
        prompt = (
            f"Does the following message ask to change a ticket's PRIORITY?\n\n"
            f"Message: \"{text.strip()}\"\n\n"
            f"Valid priorities: High, Medium, Low.\n\n"
            f"Note: Only extract priority — ignore any status-related words.\n\n"
            f"Respond with JSON only: "
            f"{{\"is_update\": true/false, \"priority\": \"High/Medium/Low or null\"}}"
        )
        resp = client.chat.completions.create(
            model       = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0,
            max_tokens  = 40,
        )
        import json as _json
        raw   = resp.choices[0].message.content.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = _json.loads(clean)
        if result.get("is_update") and result.get("priority"):
            return {"priority": result.get("priority"), "status": None}
    except Exception as e:
        logging.error(f"[update_detect] failed: {e}")
    return None


def _call_graph(
    query: str,
    run_eval: bool = False,
    confirm_ticket: bool = False,
    session_summary: str = "",
) -> tuple[dict | None, str | None]:
    """Call the /chat LangGraph endpoint."""
    dept = st.session_state.rag_filter_dept
    return api("post", "/chat", json={
        "query":           query,
        "industry":        None if dept == "All" else dept,
        "doc_type":        "",
        "chat_history":    _build_history_payload(),
        "session_summary": session_summary,
        "run_eval":        run_eval,
        "confirm_ticket":  confirm_ticket,
        "session_id":      st.session_state.rag_session_id or "",
    })


def _build_sources_with_links(chunks: list[dict]) -> list[dict]:
    sources_with_links = []
    seen = set()
    for c in chunks:
        label = (f"{c.get('doc_title','')} → {c.get('section_heading','')}"
                 if c.get("section_heading") else c.get("doc_title", ""))
        pid  = c.get("page_id", "")
        url  = f"https://notion.so/{pid.replace('-','')}" if pid else ""
        if label not in seen:
            seen.add(label)
            sources_with_links.append({"label": label, "url": url})
    return sources_with_links


# ── Priority badge ─────────────────────────────────────────────
def _priority_badge(priority: str) -> str:
    return {"High": "🔴 High", "Medium": "🟡 Medium", "Low": "🟢 Low"}.get(priority, priority)


def _status_badge(status: str) -> str:
    return {"Open": "🔵 Open", "In Progress": "🟡 In Progress", "Resolved": "✅ Resolved"}.get(status, status)


# ── Sidebar ────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
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

        if st.button("⚡ Sync Knowledge Base", use_container_width=True, key="sync_btn"):
            with st.spinner("Syncing…"):
                data, err = api("post", "/sync/run")
            st.session_state.rag_sync_status = "error" if err else "ok"
            st.session_state._cached_status = None
            st.session_state._cached_industries = None
            st.rerun()
        if st.session_state.rag_sync_status == "ok":
            st.success("✓ Synced")
        elif st.session_state.rag_sync_status == "error":
            st.error("Sync failed")

        if st.button("＋ New Chat", use_container_width=True, key="new_chat_btn"):
            _save_current_chat()
            st.session_state.rag_messages        = []
            st.session_state.rag_last_chunks     = []
            st.session_state.rag_chat_title      = "New Chat"
            st.session_state.rag_editing_title   = False
            st.session_state.rag_last_ticket     = None
            st.session_state.rag_pending_tickets    = []
            st.session_state.rag_awaiting_selection  = False
            st.session_state.rag_last_created_ticket = None
            st.session_state.rag_current_chat_id     = None
            st.session_state["_last_streamed_idx"]   = -1
            import uuid
            st.session_state.rag_session_id = str(uuid.uuid4())
            st.rerun()

        st.divider()
        st.caption("**Filters**")
        industries  = fetch_industries()
        ind_options = ["All"] + industries
        cur_dept    = st.session_state.rag_filter_dept
        if cur_dept not in ind_options:
            cur_dept = "All"
        st.session_state.rag_filter_dept = st.selectbox(
            "Department", ind_options,
            index=ind_options.index(cur_dept),
            key="fil_dept")

        st.divider()
        st.session_state.rag_inspector_open = st.toggle(
            "Retrieval Inspector",
            value=st.session_state.rag_inspector_open,
            key="insp_tog")

        st.divider()
        st.caption("**Chat History**")
        history = st.session_state.rag_history

        if not history:
            st.caption("_No previous chats yet._")
        else:
            for i, item in enumerate(history[:20]):
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
                    label = item.get("title", "Chat")
                    meta  = item.get("created_at", "")
                    if st.button(f"💬 {label}", key=f"load_chat_{i}",
                                 use_container_width=True, help=meta):
                        _load_chat(i)
                        st.rerun()
                    rc1, rc2 = st.columns(2, gap="small")
                    with rc1:
                        if st.button("✏️ Rename", key=f"rename_btn_{i}", use_container_width=True):
                            st.session_state.rag_rename_idx = i
                            st.rerun()
                    with rc2:
                        if st.button("🗑 Delete", key=f"delete_btn_{i}", use_container_width=True):
                            st.session_state.rag_history.pop(i)
                            st.rerun()

        st.divider()
        st.caption("**Status**")
        status_data = fetch_rag_status()
        milvus_ok   = status_data.get("milvus_connected", False)
        count       = status_data.get("docs_indexed", 0)
        milvus_str  = ":green[connected]" if milvus_ok else ":orange[not connected]"
        st.caption(f"🗄 Milvus — {milvus_str}")
        st.caption(f"📚 Docs indexed — {count}")


# ── Tab 1: Chat ────────────────────────────────────────────────
RAG_SUGGESTIONS = [
    "What are the key risks in the Security Risk Assessment?",
    "What financial controls are in place?",
    "Summarise the incident response process",
    "What compliance requirements appear across all policies?",
    "What vulnerabilities were identified in IT infrastructure?",
]

def _render_message_sources(msg: dict):
    """Render clickable source links below an assistant message."""
    content = msg.get("content", "")
    content_lower = content.lower()

    # Only hide sources for FULLY unanswered responses
    # Partial answers that found some info should still show sources
    fully_not_found = any(phrase in content_lower for phrase in [
        "i wasn't able to find this information in the available documents",
        "would you like me to raise a support ticket",
        "i can only answer questions about company documents",
        "outside company documents",
        "a support ticket already exists",
        "support ticket created successfully",
    ])
    sources_with_links = msg.get("sources_with_links", [])
    sources            = msg.get("sources", [])
    if sources_with_links and not fully_not_found:
        parts = []
        for i, s in enumerate(sources_with_links):
            label = s["label"]
            url   = s.get("url", "")
            parts.append(f"[[{i+1}] {label}]({url})" if url else f"[{i+1}] {label}")
        st.markdown("**Sources:** " + "  ·  ".join(parts))
    elif sources and not fully_not_found:
        parts = [f"[{i+1}] {s}" for i, s in enumerate(sources)]
        st.markdown("**Sources:** " + "  ·  ".join(parts))

    # Ticket confirmation inline
    ticket = msg.get("ticket")
    if ticket and ticket.get("ticket_status") not in (None, "pending_confirmation"):
        notion_url = ticket.get("notion_url", "")
        st.success(
            f"🎫 Ticket **{ticket.get('title', ticket.get('ticket_id',''))}** created "
            f"| Priority: {_priority_badge(ticket.get('priority',''))} "
            + (f"| [View in Notion]({notion_url})" if notion_url else "")
        )


def _handle_graph_response(data: dict, query: str):
    """Process /chat response and append assistant message to session."""
    chunks        = data.get("chunks", [])
    can_answer    = data.get("can_answer", True)
    ticket_id     = data.get("ticket_id")
    ticket_status = data.get("ticket_status")

    sources_with_links = _build_sources_with_links(chunks)

    # ── Track pending unanswered questions ────────────────────
    if ticket_status == "pending_confirmation":
        # Add to pending list if not already there
        pending = st.session_state.rag_pending_tickets
        already = any(p["question"] == query for p in pending)
        if not already:
            pending.append({
                "question":  query,
                "timestamp": datetime.now().strftime("%H:%M"),
            })
            st.session_state.rag_pending_tickets = pending

    # ── Build ticket info for inline display ──────────────────
    ticket_info = None
    if ticket_id:
        ticket_info = {
            "ticket_id":  ticket_id,
            "title":      ticket_id,
            "priority":   data.get("priority", ""),
            "notion_url": f"https://notion.so/{ticket_id.replace('-','')}",
            "status":     ticket_status,
        }
        st.session_state.rag_last_ticket = ticket_info
        # Store for potential update — include ticket_title
        st.session_state.rag_last_created_ticket = {
            "ticket_id":    ticket_id,
            "ticket_title": data.get("ticket_title", ticket_id),
            "notion_url":   f"https://notion.so/{ticket_id.replace('-','')}",
            "priority":     data.get("priority", ""),
        }
        # Remove from pending once ticket is created
        created_question = query
        st.session_state.rag_pending_tickets = [
            p for p in st.session_state.rag_pending_tickets
            if p["question"] != created_question
        ]

    msg = {
        "role":               "assistant",
        "content":            data["answer"],
        "sources":            data.get("sources", []),
        "sources_with_links": sources_with_links,
        "ticket":             ticket_info,
        "ticket_status":      ticket_status,
        "path":               data.get("path", ""),
        "can_answer":         can_answer,
    }
    st.session_state.rag_messages.append(msg)

    # Store refined query on the preceding user message
    refined = data.get("refined_query", "")
    if refined:
        msgs = st.session_state.rag_messages
        for i in range(len(msgs) - 2, -1, -1):
            if msgs[i]["role"] == "user":
                msgs[i]["refined_query"] = refined
                break
    st.session_state.rag_last_chunks = chunks
    st.session_state.rag_last_scores = data.get("ragas_scores")

    if st.session_state.rag_chat_title == "New Chat":
        st.session_state.rag_chat_title = query[:46] + ("…" if len(query) > 46 else "")


def page_chat():
    messages  = st.session_state.rag_messages
    inspector = st.session_state.rag_inspector_open
    dept      = st.session_state.rag_filter_dept

    # ── Sticky layout + auto-scroll CSS ───────────────────────
    st.markdown("""
    <style>
    /* Stick the tab bar + header to top */
    .stTabs [data-baseweb="tab-list"] {
        position: sticky;
        top: 0;
        z-index: 100;
        background: var(--background-color);
        padding-top: 0.5rem;
    }

    /* Stick chat input to bottom */
    .stChatInput {
        position: fixed !important;
        bottom: 0 !important;
        left: 0 !important;
        right: 0 !important;
        z-index: 999 !important;
        background: var(--background-color) !important;
        padding: 0.75rem 1.5rem 1rem 1.5rem !important;
        border-top: 1px solid rgba(128,128,128,0.2) !important;
        margin-left: 245px !important;
    }

    /* Add bottom padding so last message isn't hidden behind input */
    .main .block-container {
        padding-bottom: 6rem !important;
    }

    /* Spinner above chat bar */
    .stSpinner {
        position: fixed !important;
        bottom: 5rem !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 1000 !important;
        background: var(--background-color) !important;
        padding: 0.5rem 1rem !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15) !important;
    }
    </style>

    <!-- Auto-scroll to bottom using anchor — works inside Streamlit iframe -->
    <div id="chat-bottom-anchor"></div>
    <script>
        const anchor = document.getElementById('chat-bottom-anchor');
        if (anchor) anchor.scrollIntoView({ behavior: 'smooth', block: 'end' });
    </script>
    """, unsafe_allow_html=True)

    # ── Chat title bar ─────────────────────────────────────────
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

    if dept != "All":
        st.caption(f"Filters active: 🏢 {dept}")

    st.divider()

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
                                {"role": "user", "content": q, "sources": []})
                            with st.spinner("Searching docs…"):
                                data, err = _call_graph(q, run_eval=inspector)
                            if err:
                                st.session_state.rag_messages.append(
                                    {"role": "assistant", "content": f"❌ {err}", "sources": []})
                            else:
                                _handle_graph_response(data, q)
                            st.rerun()
        else:
            for idx, msg in enumerate(messages):
                with st.chat_message(msg["role"]):
                    if st.session_state.rag_editing_idx == idx and msg["role"] == "user":
                        edited = st.text_area(
                            "Edit message", value=msg["content"],
                            key=f"edit_input_{idx}", label_visibility="collapsed")
                        col_save, col_cancel = st.columns(2, gap="small")
                        with col_save:
                            if st.button("✓ Resend", key=f"resend_{idx}",
                                         use_container_width=True, type="primary"):
                                st.session_state.rag_messages[idx]["content"] = edited
                                st.session_state.rag_messages = st.session_state.rag_messages[:idx+1]
                                st.session_state.rag_editing_idx = None
                                with st.spinner("Searching docs…"):
                                    data, err = _call_graph(edited, run_eval=inspector)
                                if err:
                                    st.session_state.rag_messages.append(
                                        {"role": "assistant", "content": f"❌ {err}", "sources": []})
                                else:
                                    _handle_graph_response(data, edited)
                                st.rerun()
                        with col_cancel:
                            if st.button("✕ Cancel", key=f"cancel_edit_{idx}",
                                         use_container_width=True):
                                st.session_state.rag_editing_idx = None
                                st.rerun()
                    else:
                        # Stream the latest assistant message, render others normally
                        is_latest = (msg["role"] == "assistant" and idx == len(messages) - 1)
                        already_streamed = st.session_state.get("_last_streamed_idx") == idx

                        if is_latest and not already_streamed:
                            def _stream_text(text):
                                import time
                                for word in text.split(" "):
                                    yield word + " "
                                    time.sleep(0.012)
                            st.write_stream(_stream_text(msg["content"]))
                            st.session_state["_last_streamed_idx"] = idx
                        else:
                            st.markdown(msg["content"])

                        # Auto-open DocForge for create_doc path
                        if msg.get("path") == "create_doc":
                            import streamlit.components.v1 as components
                            components.html("""
                                <script>
                                    window.open('http://localhost:8501', '_blank');
                                </script>
                            """, height=0)

                _render_message_sources(msg)

                # Action buttons
                if st.session_state.rag_editing_idx != idx:
                    btn_cols = st.columns(4, gap="small")
                    with btn_cols[0]:
                        if st.button("📋 Copy", key=f"copy_{idx}",
                                     use_container_width=True):
                            st.session_state[f"show_copy_{idx}"] = not st.session_state.get(f"show_copy_{idx}", False)

                    # Show copyable code block when copy clicked
                    if st.session_state.get(f"show_copy_{idx}", False):
                        st.code(msg["content"], language=None)
                    if msg["role"] == "user":
                        with btn_cols[1]:
                            if st.button("✏️ Edit", key=f"edit_{idx}",
                                         use_container_width=True):
                                st.session_state.rag_editing_idx = idx
                                st.rerun()
                        with btn_cols[2]:
                            if st.button("🔄 Resend", key=f"resend_direct_{idx}",
                                         use_container_width=True):
                                st.session_state.rag_messages = st.session_state.rag_messages[:idx+1]
                                with st.spinner("Searching docs…"):
                                    data, err = _call_graph(msg["content"], run_eval=inspector)
                                if err:
                                    st.session_state.rag_messages.append(
                                        {"role": "assistant", "content": f"❌ {err}", "sources": []})
                                else:
                                    _handle_graph_response(data, msg["content"])
                                st.rerun()

                    # Show refined query below user message if different from original
                    if msg["role"] == "user":
                        refined = msg.get("refined_query", "")
                        if refined and refined.lower() != msg["content"].lower():
                            st.caption(f"🔍 *Searched as:* {refined}")

    # ── Scroll anchor — auto-scrolls to bottom after new messages ──
    with chat_col:
        st.markdown('<div id="chat-end"></div>', unsafe_allow_html=True)
        st.markdown("""
        <script>
            setTimeout(function() {
                const el = document.getElementById('chat-end');
                if (el) el.scrollIntoView({behavior: 'smooth'});
            }, 200);
        </script>
        """, unsafe_allow_html=True)

    # ── Inspector panel ────────────────────────────────────────
    if insp_col:
        with insp_col:
            st.subheader("🔎 Retrieval Inspector")
            scores = st.session_state.rag_last_scores
            if scores:
                st.markdown("**📊 RAGAS Scores**")
                for name, key in [
                    ("Faithfulness",      "faithfulness"),
                    ("Answer Relevancy",  "answer_relevancy"),
                    ("Context Precision", "context_precision"),
                    ("Context Recall",    "context_recall"),
                ]:
                    val = scores.get(key)
                    if val is not None:
                        emoji = "🟢" if val >= 0.8 else ("🟡" if val >= 0.6 else "🔴")
                        st.progress(val, text=f"{emoji} {name}: {val:.2f}")
                    else:
                        st.caption(f"⚪ {name}: N/A")
                st.divider()

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

    # ── Chat input ─────────────────────────────────────────────
    hint = f" [{dept}]" if dept != "All" else ""
    user_input = st.chat_input(f"Ask a question about your docs{hint}…")
    if user_input:
        st.session_state.rag_messages.append(
            {"role": "user", "content": user_input, "sources": []})

        # ── Check last bot message state ──────────────────────
        last_bot = next(
            (m for m in reversed(st.session_state.rag_messages[:-1])
             if m["role"] == "assistant"), None
        )
        last_status = last_bot.get("ticket_status") if last_bot else None
        pending     = st.session_state.rag_pending_tickets

        # ── Detect if user wants to create a ticket (UI-level check) ──
        # This runs BEFORE sending to API when pending tickets exist
        wants_ticket = (
            pending and (
                last_status == "pending_confirmation" or
                last_status == "awaiting_selection"
            ) and _is_ticket_confirmation(user_input)
        )

        # Also intercept explicit "create ticket" phrases when pending exist
        if not wants_ticket and pending:
            ticket_phrases = ["create ticket", "create a ticket", "raise ticket",
                              "raise a ticket", "creat ticket", "make ticket",
                              "open ticket", "log ticket", "submit ticket"]
            wants_ticket = any(p in user_input.lower() for p in ticket_phrases)

        # ── Intercept ticket status change attempts ───────────────────────
        status_phrases = ["mark as resolved", "mark resolved", "resolve ticket",
                          "close ticket", "reopen ticket", "mark as open",
                          "mark as in progress", "change status", "update status",
                          "set status", "mark it as"]
        if any(p in user_input.lower() for p in status_phrases):
            last_ticket = st.session_state.rag_last_created_ticket
            notion_url  = last_ticket.get("notion_url", "") if last_ticket else ""
            st.session_state.rag_messages.append({
                "role": "assistant",
                "content": (
                    "Ticket status can only be changed by your team directly in Notion — "
                    "not from this chat.\n\n"
                    "You can only update the **priority** (High / Medium / Low) from here.\n\n"
                    + (f"[Open ticket in Notion ↗]({notion_url})" if notion_url else "")
                ),
                "sources": [],
            })
            _save_current_chat()
            st.rerun()

        # ── Case 1: Waiting for ticket selection ──────────────────────────
        if st.session_state.rag_awaiting_selection:

            # Detect cancel intent first — user doesn't want to create a ticket
            user_lower = user_input.strip().lower()
            cancel_phrases = ["no", "nope", "cancel", "nevermind", "never mind",
                              "don't want", "dont want", "not now", "skip",
                              "forget it", "forget", "no thanks", "nah", "stop",
                              "exit", "hello", "hi", "no i don't", "no i dont",
                              "not create", "i don't want", "i dont want"]
            is_cancel = (
                user_lower in cancel_phrases or
                any(phrase in user_lower for phrase in
                    ["don't want", "dont want", "no i", "not create",
                     "cancel", "don't need", "dont need"])
            )
            if is_cancel:
                st.session_state.rag_awaiting_selection = False
                st.session_state.rag_messages.append({
                    "role": "assistant",
                    "content": "No problem! Your pending questions are saved if you change your mind later. What else can I help you with?",
                    "sources": [],
                })
                _save_current_chat()
                st.rerun()

            selected_question = None
            stripped = user_input.strip()

            if stripped.isdigit():
                idx = int(stripped) - 1
                if 0 <= idx < len(pending):
                    selected_question = pending[idx]["question"]
            else:
                try:
                    from openai import AzureOpenAI
                    client = AzureOpenAI(
                        api_key        = os.getenv("AZURE_OPENAI_LLM_KEY"),
                        azure_endpoint = os.getenv("AZURE_LLM_ENDPOINT"),
                        api_version    = os.getenv("AZURE_LLM_API_VERSION", "2024-02-01"),
                    )
                    options = "\n".join(f"{i+1}. {p['question']}" for i, p in enumerate(pending))
                    prompt  = (
                        f"The user was asked to pick one of these unanswered questions:\n"
                        f"{options}\n\n"
                        f"User replied: \"{user_input}\"\n\n"
                        f"Which number (1-{len(pending)}) are they referring to? "
                        f"If none match clearly, reply 0."
                    )
                    resp = client.chat.completions.create(
                        model       = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
                        messages    = [{"role": "user", "content": prompt}],
                        temperature = 0,
                        max_tokens  = 5,
                    )
                    num = resp.choices[0].message.content.strip()
                    if num.isdigit():
                        idx = int(num) - 1
                        if 0 <= idx < len(pending):
                            selected_question = pending[idx]["question"]
                except Exception as e:
                    logging.error(f"[selection] LLM failed: {e}")

            if selected_question:
                st.session_state.rag_awaiting_selection = False
                with st.spinner("Creating ticket…"):
                    data, err = _call_graph(
                        selected_question,
                        confirm_ticket=True,
                        session_summary=f"User asked: {selected_question}",
                    )
                if err:
                    st.session_state.rag_messages.append(
                        {"role": "assistant", "content": f"❌ Error: {err}", "sources": []})
                else:
                    st.session_state.rag_pending_tickets = [
                        p for p in pending if p["question"] != selected_question
                    ]
                    _handle_graph_response(data, selected_question)
            else:
                options_text = "\n".join(
                    f"**{i+1}.** {p['question']}" for i, p in enumerate(pending)
                )
                st.session_state.rag_messages.append({
                    "role": "assistant",
                    "content": f"Please reply with a number:\n\n{options_text}",
                    "sources": [], "ticket_status": "awaiting_selection",
                })
            st.rerun()

        # ── Case 2: User wants to create ticket + pending questions exist ──
        elif wants_ticket and pending:
            if len(pending) == 1:
                # Only one — create directly
                question = pending[0]["question"]
                with st.spinner("Creating ticket…"):
                    data, err = _call_graph(
                        question,
                        confirm_ticket=True,
                        session_summary=f"User asked: {question}",
                    )
                if err:
                    st.session_state.rag_messages.append(
                        {"role": "assistant", "content": f"❌ Error: {err}", "sources": []})
                else:
                    st.session_state.rag_pending_tickets = []
                    _handle_graph_response(data, question)
            else:
                # Multiple — show selection
                st.session_state.rag_awaiting_selection = True
                options_text = "\n".join(
                    f"**{i+1}.** {p['question']}" for i, p in enumerate(pending)
                )
                st.session_state.rag_messages.append({
                    "role": "assistant",
                    "content": (
                        f"You have **{len(pending)} unanswered questions**. "
                        f"Which one should I raise a ticket for?\n\n"
                        f"{options_text}\n\n"
                        f"_Reply with the number or describe which one._"
                    ),
                    "sources": [], "ticket_status": "awaiting_selection",
                })
            st.rerun()

        # ── Case 3: Normal query ───────────────────────────────
        else:
            st.session_state.rag_awaiting_selection = False

            # Check if user wants to update the last created ticket
            last_ticket = st.session_state.rag_last_created_ticket
            if last_ticket:
                update = _detect_ticket_update(user_input)
                if update and (update.get("priority") or update.get("status")):
                    ticket_id  = last_ticket["ticket_id"]
                    notion_url = last_ticket["notion_url"]
                    payload = {}
                    if update.get("priority"):
                        payload["priority"] = update["priority"]
                    if update.get("status"):
                        payload["status"] = update["status"]

                    data, err = api("patch", f"/tickets/{ticket_id}", json=payload)
                    if err:
                        st.session_state.rag_messages.append({
                            "role": "assistant",
                            "content": f"❌ Failed to update ticket: {err}",
                            "sources": [],
                        })
                    else:
                        changes = []
                        if update.get("priority"):
                            changes.append(f"Priority → **{update['priority']}**")
                            st.session_state.rag_last_created_ticket["priority"] = update["priority"]
                        ticket_title = last_ticket.get("ticket_title", ticket_id)
                        st.session_state.rag_messages.append({
                            "role": "assistant",
                            "content": (
                                f"✅ Ticket **`{ticket_title}`** updated successfully!\n\n"
                                f"{chr(10).join(changes)}\n\n"
                                f"[View ticket in Notion ↗]({notion_url})\n\n"
                                f"_Note: Ticket status can only be changed by your team in Notion._"
                            ),
                            "sources": [],
                        })
                    st.rerun()

            with st.spinner("Searching docs and generating answer…"):
                data, err = _call_graph(user_input, run_eval=inspector)
            if err:
                st.session_state.rag_messages.append(
                    {"role": "assistant", "content": f"❌ Error: {err}", "sources": []})
            else:
                _handle_graph_response(data, user_input)
            _save_current_chat()
            st.rerun()


# ── Tab 2: Retrieval Inspector ─────────────────────────────────
def page_retrieval_inspector():
    st.subheader("🔎 Retrieval Inspector")
    st.caption("Detailed view of chunks retrieved for the last query.")

    chunks = st.session_state.rag_last_chunks
    scores = st.session_state.rag_last_scores

    if not chunks:
        st.info("Ask a question in the Chat tab first to see retrieval details here.")
        return

    # RAGAS scores
    if scores:
        st.markdown("#### 📊 RAGAS Quality Scores")
        c1, c2, c3, c4 = st.columns(4)
        for col, name, key in [
            (c1, "Faithfulness",      "faithfulness"),
            (c2, "Answer Relevancy",  "answer_relevancy"),
            (c3, "Context Precision", "context_precision"),
            (c4, "Context Recall",    "context_recall"),
        ]:
            val = scores.get(key)
            with col:
                if val is not None:
                    emoji = "🟢" if val >= 0.8 else ("🟡" if val >= 0.6 else "🔴")
                    st.metric(label=f"{emoji} {name}", value=f"{val:.2f}")
                else:
                    st.metric(label=f"⚪ {name}", value="N/A")
        st.divider()

    # Chunk details
    st.markdown(f"#### 📄 Retrieved Chunks ({len(chunks)})")
    for i, c in enumerate(chunks, 1):
        doc_t = c.get("doc_title", "Unknown")
        sec   = c.get("section_heading", "")
        score = c.get("score", 0.0)
        text  = c.get("raw_text", "")
        pid   = c.get("page_id", "")
        meta  = f"{doc_t} → {sec}" if sec else doc_t
        url   = f"https://notion.so/{pid.replace('-','')}" if pid else ""

        with st.expander(f"#{i} · {meta}  —  score: {score:.4f}"):
            col_text, col_meta = st.columns([3, 1])
            with col_text:
                st.markdown(f"```\n{text[:600]}{'…' if len(text) > 600 else ''}\n```")
            with col_meta:
                st.caption(f"**Doc:** {doc_t}")
                st.caption(f"**Section:** {sec or '—'}")
                st.caption(f"**Score:** {score:.4f}")
                if url:
                    st.markdown(f"[Open in Notion]({url})")


# ── Tab 3: My Tickets ──────────────────────────────────────────
def page_tickets():
    st.subheader("🎫 My Tickets")
    st.caption("Support tickets created when CiteRAG couldn't answer a question.")

    # Status filter
    col_filter, col_refresh = st.columns([3, 1])
    with col_filter:
        status_options = ["All", "Open", "In Progress", "Resolved"]
        selected_status = st.selectbox(
            "Filter by status",
            status_options,
            index=status_options.index(st.session_state.rag_tickets_filter),
            key="tickets_status_filter",
            label_visibility="collapsed",
        )
        st.session_state.rag_tickets_filter = selected_status

    with col_refresh:
        refresh = st.button("🔄 Refresh", use_container_width=True, key="tickets_refresh")

    # Fetch tickets
    path = "/tickets" if selected_status == "All" else f"/tickets?status={selected_status}"
    data, err = api("get", path)

    if err:
        st.error(f"Failed to load tickets: {err}")
        return

    tickets = data or []

    if not tickets:
        st.info("No tickets found." if selected_status == "All" else f"No {selected_status} tickets found.")
        return

    st.caption(f"{len(tickets)} ticket(s) found")
    st.divider()

    for t in tickets:
        priority    = t.get("priority", "")
        status      = t.get("status", "")
        title       = t.get("title", t.get("ticket_id", ""))
        question    = t.get("question", "")
        industry    = t.get("industry", "")
        doc_type    = t.get("doc_type", "")
        attempts    = t.get("retrieved_attempts", "")
        summary     = t.get("session_summary", "")
        notion_url  = t.get("notion_url", "")

        with st.expander(
            f"{_priority_badge(priority)}  ·  {_status_badge(status)}  ·  **{title}**  —  {question[:80]}{'…' if len(question) > 80 else ''}",
            expanded=False,
        ):
            col_q, col_meta = st.columns([3, 1])
            with col_q:
                st.markdown(f"**Question:** {question}")
                if summary:
                    st.caption(f"**Session context:** {summary}")
            with col_meta:
                st.caption(f"**Priority:** {_priority_badge(priority)}")
                st.caption(f"**Status:** {_status_badge(status)}")
                if industry:
                    st.caption(f"**Industry:** {industry}")
                if doc_type:
                    st.caption(f"**Doc Type:** {doc_type}")
                if attempts:
                    st.caption(f"**Retrieval attempts:** {attempts}")
                if notion_url:
                    st.markdown(f"[Open in Notion ↗]({notion_url})")


# ── Tab 4: Evaluation Lab ──────────────────────────────────────
def page_evaluation_lab():
    st.subheader("📊 Evaluation Lab")
    st.caption("Add 5–20 question + ground truth pairs and run RAGAS evaluation across all of them.")

    # ── Session state for eval pairs and results ───────────────
    if "eval_pairs" not in st.session_state:
        st.session_state.eval_pairs = []
    if "eval_results" not in st.session_state:
        st.session_state.eval_results = []

    pairs   = st.session_state.eval_pairs
    MAX_PAIRS = 20
    MIN_PAIRS = 5

    # ── Input section ──────────────────────────────────────────
    st.markdown("#### ➕ Add Evaluation Pairs")

    input_tab1, input_tab2 = st.tabs(["Add one by one", "Paste as CSV"])

    with input_tab1:
        with st.form("add_pair_form", clear_on_submit=True):
            q  = st.text_input("Question", placeholder="e.g. What is the leave policy?")
            gt = st.text_area("Ground Truth Answer", height=80,
                              placeholder="e.g. Employees get 20 days annual leave...")
            col_add, col_info = st.columns([2, 3])
            with col_add:
                add_clicked = st.form_submit_button(
                    "Add Pair", type="primary", use_container_width=True,
                    disabled=len(pairs) >= MAX_PAIRS,
                )
            with col_info:
                st.caption(f"{len(pairs)}/{MAX_PAIRS} pairs added")

        if add_clicked:
            if not q.strip() or not gt.strip():
                st.warning("Both question and ground truth are required.")
            elif len(pairs) >= MAX_PAIRS:
                st.warning(f"Maximum {MAX_PAIRS} pairs allowed.")
            elif any(p["question"].strip().lower() == q.strip().lower() for p in pairs):
                st.warning("This question is already in the list.")
            else:
                st.session_state.eval_pairs.append({
                    "question":     q.strip(),
                    "ground_truth": gt.strip(),
                })
                st.rerun()

    with input_tab2:
        st.caption("Format: one pair per line — `question | ground truth`")
        csv_input = st.text_area(
            "Paste pairs",
            height=150,
            placeholder="What is the leave policy? | Employees get 20 days annual leave per year.\nWhat is the notice period? | Standard notice period is 30 calendar days.",
            label_visibility="collapsed",
        )
        if st.button("Import Pairs", use_container_width=True):
            added = 0
            errors = []
            for i, line in enumerate(csv_input.strip().split("\n"), 1):
                if "|" not in line:
                    errors.append(f"Line {i}: missing '|' separator")
                    continue
                parts = line.split("|", 1)
                q_csv  = parts[0].strip()
                gt_csv = parts[1].strip()
                if not q_csv or not gt_csv:
                    errors.append(f"Line {i}: empty question or ground truth")
                    continue
                if len(pairs) + added >= MAX_PAIRS:
                    errors.append(f"Line {i}: max {MAX_PAIRS} pairs reached")
                    break
                if any(p["question"].lower() == q_csv.lower() for p in pairs):
                    errors.append(f"Line {i}: duplicate question skipped")
                    continue
                st.session_state.eval_pairs.append({
                    "question":     q_csv,
                    "ground_truth": gt_csv,
                })
                added += 1
            if added:
                st.success(f"Added {added} pairs.")
            if errors:
                for e in errors:
                    st.warning(e)
            if added:
                st.rerun()

    # ── Current pairs table ────────────────────────────────────
    if pairs:
        st.divider()
        st.markdown(f"#### 📋 Evaluation Set ({len(pairs)} pairs)")

        for i, pair in enumerate(pairs):
            col_q, col_gt, col_del = st.columns([3, 4, 1])
            with col_q:
                st.caption(f"**Q{i+1}:** {pair['question'][:80]}{'…' if len(pair['question']) > 80 else ''}")
            with col_gt:
                st.caption(f"**GT:** {pair['ground_truth'][:80]}{'…' if len(pair['ground_truth']) > 80 else ''}")
            with col_del:
                if st.button("🗑", key=f"del_pair_{i}", help="Remove"):
                    st.session_state.eval_pairs.pop(i)
                    st.session_state.eval_results = []
                    st.rerun()

        if st.button("🗑 Clear All", use_container_width=False):
            st.session_state.eval_pairs = []
            st.session_state.eval_results = []
            st.rerun()

    # ── Run evaluation ─────────────────────────────────────────
    st.divider()
    can_run = len(pairs) >= MIN_PAIRS

    if not can_run:
        st.info(f"Add at least {MIN_PAIRS} pairs to run evaluation. ({len(pairs)}/{MIN_PAIRS} added)")

    dept = st.session_state.rag_filter_dept

    if st.button(
        f"▶ Run Evaluation ({len(pairs)} pairs)",
        type="primary",
        use_container_width=True,
        disabled=not can_run,
    ):
        st.session_state.eval_results = []
        results = []

        progress_bar  = st.progress(0, text="Starting evaluation…")
        results_placeholder = st.empty()

        for i, pair in enumerate(pairs):
            progress_bar.progress(
                (i) / len(pairs),
                text=f"Evaluating {i+1}/{len(pairs)}: {pair['question'][:50]}…"
            )

            try:
                data, err = api("post", "/chat", json={
                    "query":    pair["question"],
                    "industry": None if dept == "All" else dept,
                    "run_eval": True,
                    "session_id": "",
                })

                if err or not data:
                    results.append({
                        "question":     pair["question"],
                        "ground_truth": pair["ground_truth"],
                        "answer":       f"Error: {err}",
                        "scores":       None,
                        "status":       "error",
                    })
                else:
                    scores = data.get("ragas_scores") or {}
                    results.append({
                        "question":     pair["question"],
                        "ground_truth": pair["ground_truth"],
                        "answer":       data.get("answer", ""),
                        "scores":       scores,
                        "status":       "ok",
                    })
            except Exception as e:
                results.append({
                    "question":     pair["question"],
                    "ground_truth": pair["ground_truth"],
                    "answer":       f"Exception: {str(e)}",
                    "scores":       None,
                    "status":       "error",
                })

        progress_bar.progress(1.0, text=f"✓ Evaluation complete — {len(pairs)} pairs")
        st.session_state.eval_results = results
        st.rerun()

    # ── Show results ───────────────────────────────────────────
    results = st.session_state.eval_results
    if results:
        st.divider()

        # Aggregate scores
        metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
        agg = {}
        for key in metric_keys:
            vals = [r["scores"].get(key) for r in results
                    if r.get("scores") and r["scores"].get(key) is not None]
            agg[key] = round(sum(vals) / len(vals), 3) if vals else None

        st.markdown("#### 📊 Aggregate RAGAS Scores")
        c1, c2, c3, c4 = st.columns(4)
        for col, name, key in [
            (c1, "Faithfulness",      "faithfulness"),
            (c2, "Answer Relevancy",  "answer_relevancy"),
            (c3, "Context Precision", "context_precision"),
            (c4, "Context Recall",    "context_recall"),
        ]:
            val = agg.get(key)
            with col:
                if val is not None:
                    emoji = "🟢" if val >= 0.8 else ("🟡" if val >= 0.6 else "🔴")
                    st.metric(label=f"{emoji} {name}", value=f"{val:.3f}")
                else:
                    st.metric(label=f"⚪ {name}", value="N/A")

        # Per-question breakdown
        st.divider()
        st.markdown(f"#### 📋 Per-Question Results ({len(results)} pairs)")

        for i, r in enumerate(results):
            scores  = r.get("scores") or {}
            status  = r.get("status", "ok")
            f_val   = scores.get("faithfulness")
            ar_val  = scores.get("answer_relevancy")
            cp_val  = scores.get("context_precision")
            cr_val  = scores.get("context_recall")

            def _fmt(v):
                if v is None: return "⚪ N/A"
                e = "🟢" if v >= 0.8 else ("🟡" if v >= 0.6 else "🔴")
                return f"{e} {v:.2f}"

            label = (
                f"**Q{i+1}** — {r['question'][:60]}{'…' if len(r['question']) > 60 else ''}  "
                f"| F:{_fmt(f_val)} AR:{_fmt(ar_val)} CP:{_fmt(cp_val)} CR:{_fmt(cr_val)}"
            )

            with st.expander(label, expanded=False):
                st.markdown(f"**Question:** {r['question']}")
                st.markdown(f"**Ground Truth:** {r['ground_truth']}")
                st.markdown(f"**Generated Answer:** {r['answer'][:500]}{'…' if len(r['answer']) > 500 else ''}")
                if status == "error":
                    st.error("Evaluation failed for this pair.")

        # ── Print Report button ────────────────────────────────
        st.divider()
        if st.button("🖨 Download PDF Report", use_container_width=True, type="secondary"):
            from datetime import datetime
            payload = {
                "results": [
                    {
                        "question":     r["question"],
                        "ground_truth": r["ground_truth"],
                        "answer":       r.get("answer", ""),
                        "scores":       r.get("scores"),
                        "status":       r.get("status", "ok"),
                    }
                    for r in results
                ],
                "generated_at": datetime.now().strftime("%B %d, %Y at %H:%M"),
            }
            with st.spinner("Generating PDF report…"):
                try:
                    import requests as _req
                    resp = _req.post(
                        f"{API_BASE}/evaluation/report",
                        json=payload,
                        timeout=60,
                    )
                    if resp.status_code == 200:
                        st.download_button(
                            label      = "📥 Click to download report",
                            data       = resp.content,
                            file_name  = f"citerag_eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime       = "application/pdf",
                            use_container_width=True,
                        )
                    else:
                        st.error(f"Report generation failed: {resp.status_code}")
                except Exception as e:
                    st.error(f"Failed to generate report: {e}")


# ── Main ───────────────────────────────────────────────────────
render_sidebar()

tab_chat, tab_tickets, tab_eval = st.tabs([
    "💬 Chat",
    "🎫 My Tickets",
    "📊 Evaluation Lab",
])

with tab_chat:
    page_chat()

with tab_tickets:
    page_tickets()

with tab_eval:
    page_evaluation_lab()