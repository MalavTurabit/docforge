"""
app/routes/rag.py
POST /rag/chat   — main RAG query endpoint
GET  /rag/status — collection stats for UI status pills
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.rag_service import rag_query
from app.rag_config import collection_stats

router = APIRouter(prefix="/rag", tags=["RAG"])


# ── Request / Response models ────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    str   # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    query:        str
    industry:     Optional[str] = None
    doc_type:     Optional[str] = None
    top_k:        Optional[int] = 5
    chat_history: Optional[list[ChatMessage]] = None
    run_eval:     Optional[bool] = False    # set True to run RAGAS evaluation


class ChunkOut(BaseModel):
    doc_title:       str
    section_heading: str
    raw_text:        str
    score:           float
    page_id:         Optional[str] = ""


class ChatResponse(BaseModel):
    answer:       str
    sources:      list[str]
    chunks:       list[ChunkOut]
    grounded:     bool
    ragas_scores: Optional[dict] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Main RAG endpoint. Retrieves relevant chunks from Milvus,
    generates a grounded answer via Azure OpenAI, and runs LLM-as-judge.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Normalise filters — treat "All" as None
    industry = req.industry if req.industry and req.industry != "All" else None
    doc_type = req.doc_type if req.doc_type and req.doc_type != "All" else None

    # Convert ChatMessage objects to plain dicts for rag_service
    history = [{"role": m.role, "content": m.content} for m in req.chat_history] if req.chat_history else None

    try:
        result = rag_query(
            query        = req.query,
            industry     = industry,
            doc_type     = doc_type,
            top_k        = req.top_k or 5,
            chat_history = history,
            run_eval     = req.run_eval or False,
        )
    except Exception as e:
        err_str = str(e)
        # Handle Azure content filter (jailbreak/prompt injection detected)
        if "content_filter" in err_str or "ResponsibleAI" in err_str or "jailbreak" in err_str:
            return ChatResponse(
                answer       = "I cannot process this request. It appears to contain content that violates usage policies.",
                sources      = [],
                chunks       = [],
                grounded     = True,
                ragas_scores = None,
            )
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {err_str}")

    return ChatResponse(
        answer       = result["answer"],
        sources      = result["sources"],
        ragas_scores = result.get("ragas_scores"),
        chunks       = [ChunkOut(
                doc_title       = c.get("doc_title", ""),
                section_heading = c.get("section_heading", ""),
                raw_text        = c.get("raw_text", ""),
                score           = c.get("score", 0.0),
                page_id         = c.get("page_id") or "",
            ) for c in result["chunks"]],
        grounded = result["grounded"],
    )


@router.get("/status")
def rag_status():
    """Collection stats — used by the sidebar status pills in CiteRAG UI."""
    stats = collection_stats()
    return {
        "milvus_connected": stats["exists"],
        "docs_indexed":     stats["count"],
    }


@router.get("/industries")
def get_industries():
    """
    Returns all unique industry values stored in Milvus.
    Used by CiteRAG UI to populate the Department filter dynamically.
    """
    from app.rag_config import get_client, COLLECTION_NAME
    try:
        client  = get_client()
        results = client.query(
            collection_name=COLLECTION_NAME,
            filter="chunk_index == 0",
            output_fields=["industry"],
            limit=500,
        )
        industries = sorted(set(
            r["industry"] for r in results
            if r.get("industry") and r["industry"].strip()
        ))
        return {"industries": industries}
    except Exception as e:
        return {"industries": []}