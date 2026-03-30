"""
app/graph/nodes.py

LangGraph nodes for CiteRAG — real tools wired directly (no placeholders).

Nodes:
    intent_node          — classify query, set intent + path
    retrieval_node       — refine query + retrieve chunks based on path
    evidence_check_node  — judge chunks, set can_answer
    answer_node          — generate answer + optional RAGAS eval
    ticket_node          — create ticket in Notion when can_answer=False
"""

import logging
from dotenv import load_dotenv

from app.graph.state import CiteRAGState
from app.services.rag_service import (
    classify_query,
    generate_answer,
    judge_answer,
)
from app.tools.refine_query import refine_query
from app.tools.search_docs import (
    search_docs,
    search_docs_multi_step,
    search_docs_compare,
)
from app.tools.compare_docs import compare_docs
from app.tools.run_evaluation import run_evaluation
from app.tools.create_ticket import create_ticket

load_dotenv()
logger = logging.getLogger(__name__)


# ── Node 1: Intent ────────────────────────────────────────────────────────────

def intent_node(state: CiteRAGState) -> CiteRAGState:
    """
    Classify the query into one of 6 paths.
    If __CONFIRM_TICKET__ is already in session_summary, skip classification
    and route directly to create_ticket path.
    """
    logger.info(f"[intent_node] query='{state['query'][:60]}'")

    # ── Confirm ticket shortcut — skip classifier entirely ────────────────────
    if "__CONFIRM_TICKET__" in state.get("session_summary", ""):
        logger.info("[intent_node] __CONFIRM_TICKET__ detected — routing to create_ticket")
        return {
            **state,
            "intent": "create_ticket",
            "path":   "create_ticket",
            "error":  None,
        }

    # ── Normal classification ─────────────────────────────────────────────────
    try:
        classification = classify_query(
            state["query"],
            chat_history=state.get("chat_history", [])
        )
        intent = classification.get("path", "single_retrieval")
        logger.info(f"[intent_node] intent={intent} reason={classification.get('reasoning', '')[:60]}")
    except Exception as e:
        logger.error(f"[intent_node] classify_query failed: {e} — defaulting to single_retrieval")
        intent = "single_retrieval"

    # For explicit ticket creation — extract topic and set confirm marker
    if intent == "create_ticket":
        from app.services.rag_service import extract_ticket_topic
        topic = extract_ticket_topic(state["query"])
        return {
            **state,
            "intent":          "create_ticket",
            "path":            "create_ticket",
            "query":           topic,
            "session_summary": f"__CONFIRM_TICKET__ User explicitly requested ticket: {state['query']}",
            "error":           None,
        }

    return {
        **state,
        "intent": intent,
        "path":   intent,
        "error":  None,
    }


# ── Node 2: Retrieval ─────────────────────────────────────────────────────────

def retrieval_node(state: CiteRAGState) -> CiteRAGState:
    """
    Refine the query and retrieve chunks based on the intent path.

    - no_retrieval / out_of_scope → skip retrieval, return empty chunks
    - single_retrieval            → refine_query → search_docs
    - multi_step                  → refine_query → search_docs_multi_step
    - compare                     → search_docs_compare (no refinement needed)

    Sets: refined_query, chunks, chunks_a, chunks_b, retrieved_attempts
    """
    intent = state.get("intent", "single_retrieval")
    query  = state["query"]

    logger.info(f"[retrieval_node] intent={intent} query='{query[:60]}'")

    # Skip retrieval for these paths
    if intent in ("no_retrieval", "out_of_scope", "create_ticket"):
        return {
            **state,
            "refined_query":      query,
            "chunks":             [],
            "chunks_a":           [],
            "chunks_b":           [],
            "retrieved_attempts": 0,
        }

    try:
        # ── Compare path ──────────────────────────────────────────────────────
        if intent == "compare":
            result = search_docs_compare.invoke({"query": query})
            chunks_a = result.get("chunks_a", [])
            chunks_b = result.get("chunks_b", [])
            logger.info(f"[retrieval_node] compare → doc_a={len(chunks_a)} doc_b={len(chunks_b)}")
            return {
                **state,
                "refined_query":      query,
                "chunks":             [],
                "chunks_a":           chunks_a,
                "chunks_b":           chunks_b,
                "retrieved_attempts": 1,
            }

        # ── Refine query with memory context ─────────────────────────────────
        chat_history = state.get("chat_history", [])

        if chat_history:
            recent = [
                m for m in chat_history[-4:]
                if m.get("role") in ("user", "assistant") and m.get("content", "").strip()
            ]
            if recent:
                # Only use user messages for context — strip assistant responses
                # to avoid citation artifacts ([1], [2]) polluting the refined query
                user_context = "\n".join(
                    f"User: {m['content'][:120]}"
                    for m in recent
                    if m.get("role") == "user"
                )
                if user_context:
                    context_aware_query = (
                        f"Previous user questions:\n{user_context}\n\n"
                        f"New question: {query}"
                    )
                else:
                    context_aware_query = query
            else:
                context_aware_query = query
        else:
            context_aware_query = query

        refined = refine_query.invoke({"query": context_aware_query})

        # Ensure we get a clean single-line query back
        if "\n" in refined:
            refined = refined.strip().split("\n")[-1].strip()
        if not refined or len(refined) < 5:
            refined = query

        # Strip any citation artifacts like [1], [2] that crept in from chat history
        import re
        refined = re.sub(r'\s*according to documents?\s*(\[\d+\][,\s]*)+', '', refined, flags=re.IGNORECASE).strip()
        refined = re.sub(r'\[\d+\]', '', refined).strip()
        if not refined or len(refined) < 5:
            refined = query

        # ── Multi-step path ───────────────────────────────────────────────────
        if intent == "multi_step":
            chunks = search_docs_multi_step.invoke({
                "query": refined,
            })
            logger.info(f"[retrieval_node] multi_step → {len(chunks)} chunks")
            return {
                **state,
                "refined_query":      refined,
                "chunks":             chunks,
                "chunks_a":           [],
                "chunks_b":           [],
                "retrieved_attempts": 1,
            }

        # ── Single retrieval path (default) ───────────────────────────────────
        # Use multi-query for complex questions (multiple aspects, long, contains 'and')
        is_complex = (
            " and " in query.lower() or
            " also " in query.lower() or
            query.count("?") > 1 or
            len(query.split()) > 8
        )

        if is_complex:
            from app.services.rag_service import retrieve_chunks_multi_query
            industry_filter = state.get("industry") or None
            doc_type_filter = state.get("doc_type") or None
            if industry_filter == "All": industry_filter = None
            if doc_type_filter == "All": doc_type_filter = None
            chunks = retrieve_chunks_multi_query(
                query    = refined,
                top_k    = 7,   # extra chunks for multi-query merging
                industry = industry_filter,
                doc_type = doc_type_filter,
            )
            logger.info(f"[retrieval_node] multi-query single_retrieval → {len(chunks)} chunks")
        else:
            chunks = search_docs.invoke({
                "query":    refined,
                "industry": state.get("industry", ""),
                "doc_type": state.get("doc_type", ""),
            })
            logger.info(f"[retrieval_node] single_retrieval → {len(chunks)} chunks")
        return {
            **state,
            "refined_query":      refined,
            "chunks":             chunks,
            "chunks_a":           [],
            "chunks_b":           [],
            "retrieved_attempts": 1,
        }

    except Exception as e:
        logger.error(f"[retrieval_node] Retrieval failed: {e}")
        return {
            **state,
            "refined_query":      query,
            "chunks":             [],
            "chunks_a":           [],
            "chunks_b":           [],
            "retrieved_attempts": 0,
            "error":              f"Retrieval failed: {str(e)}",
        }


# ── Node 3: Evidence Check ────────────────────────────────────────────────────

def evidence_check_node(state: CiteRAGState) -> CiteRAGState:
    """
    Decide if the system can answer the query based on retrieved evidence.

    can_answer = False if:
        - No chunks retrieved at all, OR
        - judge_answer() returns grounded=False

    Sets: can_answer, grounded, no_answer_reason
    """
    intent = state.get("intent", "single_retrieval")
    logger.info(f"[evidence_check_node] intent={intent}")

    if intent == "no_retrieval":
        return {**state, "can_answer": True, "grounded": True, "no_answer_reason": None}

    if intent == "out_of_scope":
        return {**state, "can_answer": False, "grounded": True, "no_answer_reason": "out_of_scope"}

    # create_ticket — user explicitly asked, go straight to ticket_node
    if intent == "create_ticket":
        return {**state, "can_answer": False, "grounded": True, "no_answer_reason": "explicit_ticket_request"}

    # ── Compare path — check both chunk sets ─────────────────────────────────
    if intent == "compare":
        chunks_a = state.get("chunks_a", [])
        chunks_b = state.get("chunks_b", [])
        if not chunks_a and not chunks_b:
            return {
                **state,
                "can_answer":       False,
                "grounded":         False,
                "no_answer_reason": "no_chunks",
            }
        return {
            **state,
            "can_answer":       True,
            "grounded":         True,
            "no_answer_reason": None,
        }

    # ── Single / multi_step — check chunks + judge ────────────────────────────
    chunks = state.get("chunks", [])

    # Condition 1 — no chunks at all
    if not chunks:
        logger.info("[evidence_check_node] No chunks — can_answer=False")
        return {
            **state,
            "can_answer":       False,
            "grounded":         False,
            "no_answer_reason": "no_chunks",
        }

    # Condition 2 — run judge on a quick preview answer
    try:
        # Generate preview answer WITHOUT chat history to avoid contamination
        # from previous wrong answers in memory
        from app.services.rag_service import generate_answer as _generate_answer
        preview_answer = _generate_answer(
            query        = state.get("refined_query", state["query"]),
            chunks       = chunks,
            chat_history = None,  # no history — pure chunk-based answer
        )

        verdict = judge_answer(
            query  = state.get("refined_query", state["query"]),
            answer = preview_answer,
            chunks = chunks,
        )

        grounded = verdict.get("grounded", True)

        # Condition 3 — answer itself signals not found
        NOT_FOUND_PHRASE = "I could not find this information in the available documents"
        answer_signals_not_found = NOT_FOUND_PHRASE.lower() in preview_answer.lower()

        if not grounded or answer_signals_not_found:
            reason = "judge_failed" if not grounded else "not_found_in_docs"
            logger.info(f"[evidence_check_node] can_answer=False reason={reason}")
            return {
                **state,
                "can_answer":       False,
                "grounded":         False,
                "no_answer_reason": reason,
                "answer":           preview_answer,
            }

        logger.info("[evidence_check_node] Judge passed — can_answer=True")
        return {
            **state,
            "can_answer":       True,
            "grounded":         True,
            "no_answer_reason": None,
            "answer":           preview_answer,
        }

    except Exception as e:
        logger.error(f"[evidence_check_node] Judge failed with exception: {e} — defaulting can_answer=True")
        return {
            **state,
            "can_answer":       True,
            "grounded":         True,
            "no_answer_reason": None,
            "error":            f"Judge error: {str(e)}",
        }


# ── Node 4: Answer ────────────────────────────────────────────────────────────

def answer_node(state: CiteRAGState) -> CiteRAGState:
    """
    Generate the final answer and optionally run RAGAS evaluation.

    For no_retrieval / out_of_scope — returns pre-set canned responses.
    For compare — calls compare_docs tool.
    For single / multi_step — uses pre-generated answer from evidence_check_node.

    Sets: answer, sources, ragas_scores
    """
    intent = state.get("intent", "single_retrieval")
    logger.info(f"[answer_node] intent={intent}")

    # ── No retrieval — memory/greeting response ───────────────────────────────
    if intent == "no_retrieval":
        from app.services.rag_service import _chat

        # Extract first_message and summary from chat_history system message
        chat_history = state.get("chat_history", [])
        sys_content  = next((m["content"] for m in chat_history if m.get("role") == "system"), "")

        system = (
            "You are CiteRAG, a helpful document Q&A assistant for company documents. "
            "Respond warmly to greetings and questions about what you can do. "
            "For questions about the conversation history, answer ONLY from the context provided — "
            "do NOT guess or fabricate. Keep responses short and friendly.\n\n"
            + (f"Conversation context:\n{sys_content}" if sys_content else "")
        )

        messages = [{"role": "system", "content": system}]

        # Add recent raw messages from history
        for msg in chat_history[-6:]:
            if msg.get("role") in ("user", "assistant") and msg.get("content", "").strip():
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": state["query"]})
        answer = _chat(messages)
        return {**state, "answer": answer, "sources": [], "ragas_scores": None}

    # ── Out of scope — canned response ────────────────────────────────────────
    if intent == "out_of_scope":
        answer = (
            "I'm CiteRAG — a document Q&A assistant for company documents. "
            "I can only answer questions about your Notion document library. "
            "Try asking about HR policies, security controls, compliance requirements, or contracts."
        )
        return {**state, "answer": answer, "sources": [], "ragas_scores": None}

    # ── Compare path ──────────────────────────────────────────────────────────
    if intent == "compare":
        chunks_a = state.get("chunks_a", [])
        chunks_b = state.get("chunks_b", [])
        answer = compare_docs.invoke({
            "query":    state["query"],
            "chunks_a": chunks_a,
            "chunks_b": chunks_b,
        })
        # Build sources with matching A/B labels
        sources = []
        for i, c in enumerate(chunks_a, 1):
            label = (f"{c['doc_title']} → {c['section_heading']}"
                     if c.get("section_heading") else c["doc_title"])
            sources.append(f"[A{i}] {label}")
        for i, c in enumerate(chunks_b, 1):
            label = (f"{c['doc_title']} → {c['section_heading']}"
                     if c.get("section_heading") else c["doc_title"])
            sources.append(f"[B{i}] {label}")

        ragas_scores = None
        if state.get("run_eval") and all_chunks:
            try:
                ragas_scores = run_evaluation.invoke({
                    "query":  state.get("refined_query", state["query"]),
                    "answer": answer,
                    "chunks": all_chunks,
                })
            except Exception as e:
                logger.warning(f"[answer_node] RAGAS failed for compare: {e}")

        return {**state, "answer": answer, "sources": sources, "ragas_scores": ragas_scores}

    # ── Single / multi_step — answer already generated in evidence_check_node ─
    chunks = state.get("chunks", [])
    answer = state.get("answer", "")

    # Fallback — regenerate if answer somehow missing
    if not answer:
        try:
            from app.services.rag_service import generate_answer as _generate_answer
            answer = _generate_answer(
                query        = state.get("refined_query", state["query"]),
                chunks       = chunks,
                chat_history = state.get("chat_history", []),
            )
        except Exception as e:
            logger.error(f"[answer_node] Answer generation fallback failed: {e}")
            answer = "I encountered an error while generating the answer. Please try again."

    sources = list(dict.fromkeys(
        f"{c['doc_title']} → {c['section_heading']}" if c.get("section_heading") else c["doc_title"]
        for c in chunks
    ))

    ragas_scores = None
    if state.get("run_eval") and chunks:
        try:
            ragas_scores = run_evaluation.invoke({
                "query":  state.get("refined_query", state["query"]),
                "answer": answer,
                "chunks": chunks,
            })
        except Exception as e:
            logger.warning(f"[answer_node] RAGAS failed: {e}")

    return {**state, "answer": answer, "sources": sources, "ragas_scores": ragas_scores}


# ── Node 5: Ticket ────────────────────────────────────────────────────────────

def ticket_node(state: CiteRAGState) -> CiteRAGState:
    """
    Called when can_answer=False.

    Two modes:
    1. Normal unanswerable query — do NOT auto-create ticket.
       Instead return a confirmation prompt asking the user if they want one.
       Sets: answer, ticket_id=None, ticket_status="pending_confirmation"

    2. User explicitly confirmed ticket creation (session_summary contains
       "__CONFIRM_TICKET__" marker set by the graph runner) — create ticket now.
       Sets: answer, ticket_id, ticket_status="created"|"exists"

    Skipped for out_of_scope — canned response already set in answer_node.
    """
    intent           = state.get("intent", "single_retrieval")
    no_answer_reason = state.get("no_answer_reason")
    session_summary  = state.get("session_summary", "")

    logger.info(f"[ticket_node] intent={intent} reason={no_answer_reason}")

    # out_of_scope — no ticket, answer already set in answer_node
    if intent == "out_of_scope":
        return state

    # ── Mode 2: User confirmed ticket creation ────────────────────────────────
    if "__CONFIRM_TICKET__" in session_summary:
        clean_summary = session_summary.replace("__CONFIRM_TICKET__", "").strip()

        # The actual question to ticket — prefer original query stored in session_summary
        # Format: "User asked: <original question>"
        ticket_question = state["query"]
        if "User asked:" in clean_summary:
            extracted = clean_summary.split("User asked:")[-1].strip()
            if extracted:
                ticket_question = extracted
        elif "User explicitly requested ticket:" in clean_summary:
            extracted = clean_summary.split("User explicitly requested ticket:")[-1].strip()
            if extracted:
                ticket_question = extracted

        logger.info(f"[ticket_node] Creating ticket for: '{ticket_question[:60]}'")

        try:
            result = create_ticket.invoke({
                "question":           ticket_question,
                "industry":           state.get("industry", ""),
                "retrieved_attempts": state.get("retrieved_attempts", 0),
                "session_summary":    clean_summary,
            })

            ticket_id     = result.get("ticket_id")
            ticket_title  = result.get("ticket_title", ticket_id)
            ticket_status = result.get("status")
            priority      = result.get("priority")
            notion_url    = result.get("notion_url", "")

            logger.info(f"[ticket_node] ticket={ticket_id} title={ticket_title} status={ticket_status} priority={priority}")

            if ticket_status == "exists":
                matched = result.get("matched_question", "")
                answer = (
                    "I wasn't able to find this information in the available documents.\n\n"
                    "However, a support ticket already exists for this topic"
                    + (f" — matched to: *\"{matched[:80]}\"*" if matched and matched.lower() != ticket_question.lower() else "")
                    + " — our team will follow up with you shortly.\n\n"
                    + (f"[View existing ticket in Notion ↗]({notion_url})" if notion_url else "")
                )
                return {
                    **state,
                    "answer":        answer,
                    "sources":       [],
                    "chunks":        [],
                    "ragas_scores":  None,
                    "ticket_id":     ticket_id,
                    "ticket_status": ticket_status,
                    "session_summary": clean_summary,
                    "error":         None,
                }
            else:
                answer = (
                    f"✅ Support ticket created successfully!\n\n"
                    f"**Ticket:** `{ticket_title}`\n"
                    f"**Question:** {ticket_question[:120]}\n"
                    f"**Priority:** {priority}\n\n"
                    + (f"[View ticket in Notion ↗]({notion_url})\n\n" if notion_url else "")
                    + "Our team will review it and get back to you."
                )

            return {
                **state,
                "answer":        answer,
                "sources":       [],
                "ragas_scores":  None,
                "ticket_id":     ticket_id,
                "ticket_title":  ticket_title,
                "ticket_status": ticket_status,
                "session_summary": clean_summary,
                "error":         None,
            }

        except Exception as e:
            logger.error(f"[ticket_node] create_ticket failed: {e}")
            return {
                **state,
                "answer":  "I encountered an error while creating the support ticket. Please try again.",
                "sources": [],
                "error":   f"Ticket creation failed: {str(e)}",
            }

    # ── Mode 1: Ask for confirmation — check for semantic duplicate first ────────
    logger.info("[ticket_node] No answer found — checking for semantic duplicate before asking")

    query_text  = state["query"]
    # Skip duplicate check for specific/detailed queries — less likely to be true duplicates
    is_specific = len(query_text.split()) > 6 or any(
        word[0].isupper() for word in query_text.split() if len(word) > 3
    )

    if not is_specific:
        try:
            from app.tools.create_ticket import _find_existing_ticket
            existing_id, matched_q, existing_url = _find_existing_ticket(query_text)
            if existing_id:
                notion_url = existing_url or f"https://notion.so/{existing_id.replace('-', '')}"
                logger.info(f"[ticket_node] Semantic duplicate found: '{matched_q[:60] if matched_q else ''}'")
                answer = (
                    "I wasn't able to find this information in the available documents.\n\n"
                    "However, a support ticket already exists for this topic"
                    + (f" — matched to: *\"{matched_q[:80]}\"*" if matched_q and matched_q.lower() != query_text.lower() else "")
                    + " — our team will follow up with you shortly.\n\n"
                    + (f"[View existing ticket in Notion ↗]({notion_url})" if notion_url else "")
                )
                return {
                    **state,
                    "answer":        answer,
                    "sources":       [],
                    "chunks":        [],
                    "ragas_scores":  None,
                    "ticket_id":     existing_id,
                    "ticket_status": "exists",
                }
        except Exception as e:
            logger.warning(f"[ticket_node] Pre-check duplicate failed: {e} — proceeding with confirmation")

    answer = (
        "I wasn't able to find this information in the available documents.\n\n"
        "Would you like me to raise a support ticket for this question? "
        "Our team will review it and get back to you.\n\n"
        "_Reply with **yes**, **sure**, **raise it**, or anything that confirms — "
        "and I'll create the ticket right away._"
    )
    return {
        **state,
        "answer":        answer,
        "sources":       [],
        "ragas_scores":  None,
        "ticket_id":     None,
        "ticket_status": "pending_confirmation",
    }