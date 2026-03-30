"""
app/graph/graph.py

LangGraph StateGraph for CiteRAG — wires all 5 nodes with conditional edges.

Flow:
    intent_node
        ↓
    retrieval_node
        ↓
    evidence_check_node
        ↓ can_answer=True        ↓ can_answer=False
    answer_node             ticket_node
        ↓                        ↓
       END                      END
"""

import logging
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

from app.graph.state import CiteRAGState
from app.graph.nodes import (
    intent_node,
    retrieval_node,
    evidence_check_node,
    answer_node,
    ticket_node,
)

load_dotenv()
logger = logging.getLogger(__name__)


# ── Conditional edge — after evidence_check_node ──────────────────────────────

def route_after_evidence(state: CiteRAGState) -> str:
    """
    Route to answer_node or ticket_node based on can_answer flag.

    out_of_scope always goes to answer_node (canned response, no ticket).
    Everything else: can_answer=True → answer_node, False → ticket_node.
    """
    intent     = state.get("intent", "single_retrieval")
    can_answer = state.get("can_answer", True)

    if intent == "out_of_scope":
        logger.info("[route] out_of_scope → answer_node")
        return "answer_node"

    if can_answer:
        logger.info("[route] can_answer=True → answer_node")
        return "answer_node"

    logger.info("[route] can_answer=False → ticket_node")
    return "ticket_node"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Build and compile the CiteRAG LangGraph.
    Call once at app startup and reuse the compiled graph.
    """
    graph = StateGraph(CiteRAGState)

    # ── Add nodes ─────────────────────────────────────────────────────────────
    graph.add_node("intent_node",         intent_node)
    graph.add_node("retrieval_node",      retrieval_node)
    graph.add_node("evidence_check_node", evidence_check_node)
    graph.add_node("answer_node",         answer_node)
    graph.add_node("ticket_node",         ticket_node)

    # ── Entry point ───────────────────────────────────────────────────────────
    graph.set_entry_point("intent_node")

    # ── Edges ─────────────────────────────────────────────────────────────────
    graph.add_edge("intent_node",         "retrieval_node")
    graph.add_edge("retrieval_node",      "evidence_check_node")

    # Conditional split after evidence check
    graph.add_conditional_edges(
        "evidence_check_node",
        route_after_evidence,
        {
            "answer_node": "answer_node",
            "ticket_node": "ticket_node",
        },
    )

    graph.add_edge("answer_node", END)
    graph.add_edge("ticket_node", END)

    compiled = graph.compile()
    logger.info("[graph] CiteRAG graph compiled ✓")
    return compiled


# ── Singleton — compiled once at import ──────────────────────────────────────
citerag_graph = build_graph()


# ── Helper: run the graph ─────────────────────────────────────────────────────

def run_graph(
    query:           str,
    industry:        str  = "",
    doc_type:        str  = "",
    chat_history:    list = None,
    session_summary: str  = "",
    run_eval:        bool = False,
    confirm_ticket:  bool = False,
    session_id:      str  = "",
) -> dict:
    """
    Run the CiteRAG graph with a user query.

    Args:
        query:           User question.
        industry:        Optional industry filter.
        doc_type:        Optional doc type filter.
        chat_history:    Fallback history if no session_id provided.
        session_summary: Running session summary for ticket context.
        run_eval:        Set True when Retrieval Inspector is ON.
        confirm_ticket:  Set True when user confirmed ticket creation.
        session_id:      Session ID for Redis memory. If provided, memory
                         is loaded from Redis and saved back after the graph runs.

    Returns:
        Final CiteRAGState as dict with all fields populated.
    """
    from app.services.memory_service import get_memory, save_memory

    # ── Load memory from Redis if session_id provided ─────────────────────────
    memory = None
    if session_id:
        try:
            memory        = get_memory(session_id)
            redis_history = memory.to_history()

            # Backfill first_message — use current query if this is a fresh session
            # Once set, never overwrite — first_message is immutable
            if not memory.first_message:
                memory.first_message = query
                logger.info(f"[run_graph] Set first_message: '{query[:60]}'")

            # Merge Redis history with UI fallback
            if redis_history and chat_history:
                redis_contents = {m["content"] for m in redis_history if m.get("role") != "system"}
                extra = [
                    m for m in chat_history
                    if m.get("content") not in redis_contents
                    and m.get("role") in ("user", "assistant")
                ]
                history = redis_history + extra
            elif redis_history:
                history = redis_history
            else:
                history = chat_history or []

            logger.info(
                f"[run_graph] Memory loaded for {session_id} — "
                f"redis={len(redis_history)} ui={len(chat_history or [])} merged={len(history)} "
                f"first_msg='{memory.first_message[:40] if memory.first_message else 'none'}'"
            )
        except Exception as e:
            logger.warning(f"[run_graph] Memory load failed: {e} — using fallback history")
            history = chat_history or []
    else:
        history = chat_history or []

    # ── Inject confirm marker ─────────────────────────────────────────────────
    if confirm_ticket:
        session_summary = f"__CONFIRM_TICKET__ {session_summary}".strip()
    initial_state: CiteRAGState = {
        "query":               query,
        "industry":            industry or "",
        "doc_type":            doc_type or "",
        "chat_history":        history,
        "session_summary":     session_summary or "",
        "run_eval":            run_eval,
        "intent":              "",
        "path":                "",
        "refined_query":       "",
        "chunks":              [],
        "chunks_a":            [],
        "chunks_b":            [],
        "retrieved_attempts":  0,
        "can_answer":          True,
        "grounded":            True,
        "no_answer_reason":    None,
        "answer":              "",
        "sources":             [],
        "ragas_scores":        None,
        "ticket_id":           None,
        "ticket_title":        None,
        "ticket_status":       None,
        "error":               None,
    }

    logger.info(f"[run_graph] START query='{query[:80]}'")
    final_state = citerag_graph.invoke(initial_state)

    # ── Save memory back to Redis ─────────────────────────────────────────────
    if session_id and memory is not None:
        try:
            answer = final_state.get("answer", "")
            ticket_status = final_state.get("ticket_status")
            path = final_state.get("path", "")

            # Save on all meaningful paths except pending_confirmation
            # Include no_retrieval so first_message gets persisted on turn 1
            if answer and ticket_status != "pending_confirmation":
                memory.add_exchange(query, answer)
                save_memory(session_id, memory)
            elif not answer and memory.first_message:
                # Even if no answer, save to persist first_message backfill
                save_memory(session_id, memory)
        except Exception as e:
            logger.warning(f"[run_graph] Memory save failed: {e}")

    logger.info(
        f"[run_graph] DONE path={final_state.get('path')} "
        f"can_answer={final_state.get('can_answer')} "
        f"ticket={final_state.get('ticket_id')}"
    )
    return final_state