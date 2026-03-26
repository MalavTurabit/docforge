"""
app/tools/search_docs.py

LangChain @tool functions for document retrieval.

Wraps the existing retrieve_chunks(), retrieve_multi_step(), and
retrieve_for_compare() from rag_service.py — no logic is duplicated.

Tools:
    search_docs             — single retrieval + MMR (used by retrieval_node)
    search_docs_multi_step  — iterative multi-step retrieval
    search_docs_compare     — splits query into two doc sets for compare path
"""

import logging
from dotenv import load_dotenv
from langchain_core.tools import tool

from app.services.rag_service import (
    retrieve_chunks,
    retrieve_multi_step,
    retrieve_for_compare,
)
from app.rag_config import TOP_K

load_dotenv()

logger = logging.getLogger(__name__)


# ── Tool 1: Single retrieval + MMR ────────────────────────────────────────────

@tool
def search_docs(
    query: str,
    top_k: int = TOP_K,
    industry: str = "",
    doc_type: str = "",
) -> list[dict]:
    """
    Search the Notion document library using vector similarity + MMR reranking.
    Returns the most relevant and diverse chunks for a given query.

    Used by: retrieval_node (single_retrieval path)

    Args:
        query:    The search query (should already be refined before calling).
        top_k:    Number of chunks to return (default from rag_config.TOP_K).
        industry: Optional industry filter (e.g. 'HR', 'Finance'). Pass '' to skip.
        doc_type: Optional doc type filter (e.g. 'Policy', 'Contract'). Pass '' to skip.

    Returns:
        List of chunk dicts, each with:
            chunk_id, page_id, doc_title, section_heading,
            doc_type, industry, raw_text, score
    """
    try:
        industry_filter  = industry if industry and industry != "All" else None
        doc_type_filter  = doc_type if doc_type and doc_type != "All" else None

        chunks = retrieve_chunks(
            query    = query,
            top_k    = top_k,
            industry = industry_filter,
            doc_type = doc_type_filter,
        )

        logger.info(
            f"[search_docs] query='{query[:60]}' "
            f"filters=industry:{industry_filter} doc_type:{doc_type_filter} "
            f"→ {len(chunks)} chunks returned"
        )
        return chunks

    except Exception as e:
        logger.error(f"[search_docs] Retrieval failed for query='{query[:60]}': {e}")
        return []


# ── Tool 2: Multi-step iterative retrieval ────────────────────────────────────

@tool
def search_docs_multi_step(
    query: str,
    top_k: int = TOP_K,
) -> list[dict]:
    """
    Multi-step iterative retrieval for complex queries that require
    reasoning across multiple documents.

    Step 1: retrieve with original query
    Step 2: LLM generates a follow-up query to fill gaps
    Step 3: retrieve again, merge and deduplicate

    Used by: retrieval_node (multi_step path)

    Args:
        query: The refined search query.
        top_k: Number of chunks per retrieval step.

    Returns:
        Merged deduplicated list of chunks (up to top_k * 2),
        sorted by relevance score descending.
    """
    try:
        chunks = retrieve_multi_step(query=query, top_k=top_k)

        logger.info(
            f"[search_docs_multi_step] query='{query[:60]}' "
            f"→ {len(chunks)} chunks after merge"
        )
        return chunks

    except Exception as e:
        logger.error(f"[search_docs_multi_step] Retrieval failed for query='{query[:60]}': {e}")
        return []


# ── Tool 3: Compare retrieval ─────────────────────────────────────────────────

@tool
def search_docs_compare(query: str) -> dict:
    """
    Retrieval for compare queries — extracts two document names from the query
    and retrieves chunks from each separately.

    Used by: retrieval_node (compare path)

    Args:
        query: A comparison query, e.g. 'Compare the SOW vs MSA'.

    Returns:
        Dict with keys:
            chunks_a — list of chunks for the first document
            chunks_b — list of chunks for the second document
    """
    try:
        chunks_a, chunks_b = retrieve_for_compare(query=query)

        logger.info(
            f"[search_docs_compare] query='{query[:60]}' "
            f"→ doc_a: {len(chunks_a)} chunks | doc_b: {len(chunks_b)} chunks"
        )
        return {
            "chunks_a": chunks_a,
            "chunks_b": chunks_b,
        }

    except Exception as e:
        logger.error(f"[search_docs_compare] Retrieval failed for query='{query[:60]}': {e}")
        return {"chunks_a": [], "chunks_b": []}