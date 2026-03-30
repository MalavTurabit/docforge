"""
app/routes/chat.py

POST /chat — full LangGraph CiteRAG pipeline.

Keeps the same request/response shape as /rag/chat so the existing
Streamlit UI can switch to this endpoint with zero changes.

New fields in response:
    path          — routing path taken (single_retrieval, compare, etc.)
    ticket_id     — Notion ticket ID if can_answer=False
    ticket_status — "created" | "exists" | None
    no_answer_reason — why can_answer was False (if applicable)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.graph.graph import run_graph

router = APIRouter(prefix="/chat", tags=["CiteRAG Graph"])


# ── Request / Response models ─────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    str
    content: str


class ChatRequest(BaseModel):
    query:           str
    industry:        Optional[str]  = None
    doc_type:        Optional[str]  = None
    chat_history:    Optional[list[ChatMessage]] = None
    session_summary: Optional[str]  = ""
    run_eval:        Optional[bool] = False
    confirm_ticket:  Optional[bool] = False
    session_id:      Optional[str]  = ""   # for Redis memory


class ChunkOut(BaseModel):
    doc_title:       str
    section_heading: str
    raw_text:        str
    score:           float
    page_id:         Optional[str] = ""


class ChatResponse(BaseModel):
    answer:           str
    sources:          list[str]
    chunks:           list[ChunkOut]
    grounded:         bool
    path:             str
    can_answer:       bool
    refined_query:    Optional[str]  = None
    ragas_scores:     Optional[dict] = None
    ticket_id:        Optional[str]  = None
    ticket_title:     Optional[str]  = None
    ticket_status:    Optional[str]  = None
    no_answer_reason: Optional[str]  = None
    error:            Optional[str]  = None


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Full LangGraph CiteRAG pipeline:
        intent_node → retrieval_node → evidence_check_node
            → answer_node (can_answer=True)
            → ticket_node (can_answer=False)
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Normalise filters — treat "All" as empty
    industry = req.industry if req.industry and req.industry != "All" else ""
    doc_type = req.doc_type if req.doc_type and req.doc_type != "All" else ""

    # Convert ChatMessage objects to plain dicts
    history = (
        [{"role": m.role, "content": m.content} for m in req.chat_history]
        if req.chat_history else []
    )

    try:
        result = run_graph(
            query           = req.query,
            industry        = industry,
            doc_type        = doc_type,
            chat_history    = history,
            session_summary = req.session_summary or "",
            run_eval        = req.run_eval or False,
            confirm_ticket  = req.confirm_ticket or False,
            session_id      = req.session_id or "",
        )
    except Exception as e:
        err_str = str(e)
        # Handle Azure content filter
        if "content_filter" in err_str or "ResponsibleAI" in err_str or "jailbreak" in err_str:
            return ChatResponse(
                answer           = "I cannot process this request. It appears to contain content that violates usage policies.",
                sources          = [],
                chunks           = [],
                grounded         = True,
                path             = "blocked",
                can_answer       = False,
                ragas_scores     = None,
                ticket_id        = None,
                ticket_status    = None,
                no_answer_reason = "content_filter",
                error            = None,
            )
        raise HTTPException(status_code=500, detail=f"Graph pipeline error: {err_str}")

    # Merge chunks from single/multi_step and compare paths
    all_chunks = result.get("chunks", []) or (
        result.get("chunks_a", []) + result.get("chunks_b", [])
    )

    return ChatResponse(
        answer           = result.get("answer", ""),
        sources          = result.get("sources", []),
        grounded         = result.get("grounded", True),
        path             = result.get("path", ""),
        can_answer       = result.get("can_answer", True),
        refined_query    = result.get("refined_query", ""),
        ragas_scores     = result.get("ragas_scores"),
        ticket_id        = result.get("ticket_id"),
        ticket_title     = result.get("ticket_title"),
        ticket_status    = result.get("ticket_status"),
        no_answer_reason = result.get("no_answer_reason"),
        error            = result.get("error"),
        chunks           = [
            ChunkOut(
                doc_title       = c.get("doc_title", ""),
                section_heading = c.get("section_heading", ""),
                raw_text        = c.get("raw_text", ""),
                score           = c.get("score", 0.0),
                page_id         = c.get("page_id") or "",
            )
            for c in all_chunks
        ],
    )