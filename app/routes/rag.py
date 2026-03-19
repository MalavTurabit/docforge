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

class ChatRequest(BaseModel):
    query:    str
    industry: Optional[str] = None   # filter — None or "All" means no filter
    doc_type: Optional[str] = None   # filter — None or "All" means no filter
    top_k:    Optional[int] = 5


class ChunkOut(BaseModel):
    doc_title:       str
    section_heading: str
    raw_text:        str
    score:           float


class ChatResponse(BaseModel):
    answer:   str
    sources:  list[str]
    chunks:   list[ChunkOut]
    grounded: bool


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

    try:
        result = rag_query(
            query    = req.query,
            industry = industry,
            doc_type = doc_type,
            top_k    = req.top_k or 5,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {str(e)}")

    return ChatResponse(
        answer   = result["answer"],
        sources  = result["sources"],
        chunks   = [ChunkOut(**{k: c[k] for k in ChunkOut.model_fields}) for c in result["chunks"]],
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