"""
app/tools/refine_query.py

LangChain @tool — rewrites vague or ambiguous queries into clear,
specific search queries before hitting Milvus.

Wraps the existing refine_query() from rag_service.py — no logic duplicated.

Used by: retrieval_node (single_retrieval and multi_step paths)
"""

import logging
from dotenv import load_dotenv
from langchain_core.tools import tool

from app.services.rag_service import refine_query as _refine_query

load_dotenv()

logger = logging.getLogger(__name__)


@tool
def refine_query(query: str) -> str:
    """
    Rewrite a vague or ambiguous query into a clear, specific search query
    optimised for document retrieval against the Notion library.

    If the query is already clear and specific, it is returned unchanged.

    Used by: retrieval_node before calling search_docs or search_docs_multi_step.

    Args:
        query: The raw user query.

    Returns:
        A refined query string ready for vector search.

    Examples:
        "what about security?"
            → "What are the security controls and policies for data protection?"

        "tell me about hr stuff"
            → "What are the HR policies regarding employee conduct and remote work?"

        "What is the leave policy for employees?" (already clear)
            → "What is the leave policy for employees?" (unchanged)
    """
    try:
        refined = _refine_query(query)
        logger.info(f"[refine_query] '{query[:60]}' → '{refined[:60]}'")
        return refined

    except Exception as e:
        logger.error(f"[refine_query] Failed for query='{query[:60]}': {e} — returning original")
        return query