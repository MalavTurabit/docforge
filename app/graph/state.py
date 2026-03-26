"""
app/graph/state.py

LangGraph state definition for CiteRAG.
All nodes read from and write to this shared TypedDict.
"""

from typing import TypedDict, Optional


class CiteRAGState(TypedDict):
    # ── Input ─────────────────────────────────────────────────────────────────
    query:               str               # raw user query
    industry:            str               # filter from UI ('' = no filter)
    doc_type:            str               # filter from UI ('' = no filter)
    chat_history:        list[dict]        # last N messages for memory
    session_summary:     str               # running summary of session context
    run_eval:            bool              # True when Retrieval Inspector is ON

    # ── Routing ───────────────────────────────────────────────────────────────
    intent:              str               # no_retrieval | out_of_scope | single_retrieval | multi_step | compare
    path:                str               # final path taken (same as intent, set after routing)
    refined_query:       str               # rewritten query after refine_query tool

    # ── Retrieval ─────────────────────────────────────────────────────────────
    chunks:              list[dict]        # retrieved chunks (single / multi_step paths)
    chunks_a:            list[dict]        # doc A chunks (compare path)
    chunks_b:            list[dict]        # doc B chunks (compare path)
    retrieved_attempts:  int               # number of retrieval attempts made

    # ── Evidence check ────────────────────────────────────────────────────────
    can_answer:          bool              # True → answer_node | False → ticket_node
    grounded:            bool              # judge verdict
    no_answer_reason:    Optional[str]     # "no_chunks" | "judge_failed" | None

    # ── Answer ────────────────────────────────────────────────────────────────
    answer:              str               # final answer string
    sources:             list[str]         # deduplicated source labels for UI

    # ── Evaluation ────────────────────────────────────────────────────────────
    ragas_scores:        Optional[dict]    # {faithfulness, answer_relevancy, context_precision, context_recall}

    # ── Ticket ────────────────────────────────────────────────────────────────
    ticket_id:           Optional[str]     # Notion page ID of created ticket
    ticket_status:       Optional[str]     # "created" | "exists"

    # ── Error ─────────────────────────────────────────────────────────────────
    error:               Optional[str]     # any node-level error message