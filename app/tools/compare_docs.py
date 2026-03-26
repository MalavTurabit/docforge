"""
app/tools/compare_docs.py

LangChain @tool — generates a structured side-by-side comparison answer
from two sets of retrieved document chunks.

Wraps generate_compare_answer() from rag_service.py — no logic duplicated.

Used by: answer_node (compare path)
"""

import logging
from dotenv import load_dotenv
from langchain_core.tools import tool

from app.services.rag_service import generate_compare_answer as _generate_compare_answer

load_dotenv()

logger = logging.getLogger(__name__)


@tool
def compare_docs(
    query: str,
    chunks_a: list[dict],
    chunks_b: list[dict],
) -> str:
    """
    Generate a structured side-by-side comparison answer from two sets
    of retrieved document chunks.

    Used by: answer_node when intent_node detected path = 'compare'.
    chunks_a and chunks_b come from search_docs_compare tool output.

    Args:
        query:    The original comparison query from the user.
        chunks_a: Retrieved chunks for the first document.
        chunks_b: Retrieved chunks for the second document.

    Returns:
        A structured comparison answer string with:
            1. Key similarities
            2. Key differences
            3. Summary recommendation
        Citations use [A1], [A2] for doc A and [B1], [B2] for doc B.
    """
    if not chunks_a and not chunks_b:
        logger.warning("[compare_docs] Both chunk sets are empty — cannot compare")
        return "I could not find the documents you want to compare in the library."

    if not chunks_a:
        logger.warning("[compare_docs] chunks_a is empty")
        return "I could not find the first document you want to compare."

    if not chunks_b:
        logger.warning("[compare_docs] chunks_b is empty")
        return "I could not find the second document you want to compare."

    try:
        answer = _generate_compare_answer(
            query    = query,
            chunks_1 = chunks_a,
            chunks_2 = chunks_b,
        )

        logger.info(
            f"[compare_docs] query='{query[:60]}' "
            f"doc_a={len(chunks_a)} chunks | doc_b={len(chunks_b)} chunks "
            f"→ answer generated ({len(answer)} chars)"
        )
        return answer

    except Exception as e:
        logger.error(f"[compare_docs] Comparison failed for query='{query[:60]}': {e}")
        return "I encountered an error while generating the comparison. Please try again."