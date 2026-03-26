"""
app/tools/run_evaluation.py

LangChain @tool — runs RAGAS evaluation on a completed RAG response.

Wraps evaluate_rag() from eval_service.py — no logic duplicated.

Used by: answer_node (after answer is generated, when run_eval=True)

Metrics returned:
    faithfulness       — is the answer grounded in the retrieved chunks?
    answer_relevancy   — is the answer relevant to the question?
    context_precision  — are the retrieved chunks precise for the question?
    context_recall     — do the chunks cover what's needed to answer?
"""

import logging
from dotenv import load_dotenv
from langchain_core.tools import tool

from app.services.eval_service import evaluate_rag as _evaluate_rag, _empty_scores

load_dotenv()

logger = logging.getLogger(__name__)


@tool
def run_evaluation(
    query: str,
    answer: str,
    chunks: list[dict],
) -> dict:
    """
    Run RAGAS evaluation on a completed RAG response and return quality scores.

    Only call this when the user has the Retrieval Inspector open (run_eval=True).
    Skipped entirely for no_retrieval, out_of_scope, and ticket paths.

    Args:
        query:   The refined user query that was answered.
        answer:  The generated answer string.
        chunks:  The retrieved chunks used to generate the answer.

    Returns:
        Dict with 4 float scores (0.0 – 1.0), or None if metric could not run:
            faithfulness       — 🟢 ≥0.8  🟡 ≥0.6  🔴 <0.6
            answer_relevancy   — 🟢 ≥0.8  🟡 ≥0.6  🔴 <0.6
            context_precision  — 🟢 ≥0.8  🟡 ≥0.6  🔴 <0.6
            context_recall     — 🟢 ≥0.8  🟡 ≥0.6  🔴 <0.6
    """
    if not chunks:
        logger.warning("[run_evaluation] No chunks provided — returning empty scores")
        return _empty_scores()

    if not answer or not answer.strip():
        logger.warning("[run_evaluation] Empty answer provided — returning empty scores")
        return _empty_scores()

    try:
        scores = _evaluate_rag(
            query=query,
            answer=answer,
            chunks=chunks,
        )

        logger.info(
            f"[run_evaluation] query='{query[:60]}' → "
            f"faithfulness={scores.get('faithfulness')} "
            f"relevancy={scores.get('answer_relevancy')} "
            f"precision={scores.get('context_precision')} "
            f"recall={scores.get('context_recall')}"
        )
        return scores

    except Exception as e:
        logger.error(f"[run_evaluation] RAGAS failed for query='{query[:60]}': {e}")
        return _empty_scores()