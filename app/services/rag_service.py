"""
app/services/rag_service.py
Adaptive RAG with LLM-as-Judge (Self-RAG style).

Query router classifies every query into one of 4 paths:
  1. no_retrieval     — simple factual/greeting, LLM answers directly
  2. single_retrieval — targeted lookup, optional metadata filter
  3. multi_step       — complex reasoning across multiple docs
  4. compare          — side-by-side comparison of two documents
"""

import os
import json
import logging
import time
from openai import AzureOpenAI
from app.services.embeddings import embed_texts
from app.rag_config import get_client, COLLECTION_NAME, TOP_K
from app.services.rag_cache import get_retrieval_cache, set_retrieval_cache
from app.services.eval_service import evaluate_rag

logger = logging.getLogger("docforge.rag")

# ── Azure OpenAI Chat client ─────────────────────────────────────────────────
_chat_client: AzureOpenAI | None = None

def get_chat_client() -> AzureOpenAI:
    global _chat_client
    if _chat_client is None:
        _chat_client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
            azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT"),
            api_version=os.getenv("AZURE_LLM_API_VERSION", "2024-02-01"),
        )
    return _chat_client

CHAT_DEPLOYMENT = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI", "gpt-4o-mini")

# ── System persona — injected into EVERY LLM call ───────────────────────────
# Single source of truth for what CiteRAG is and what it will/won't do.
CITERAG_SYSTEM = (
    "You are CiteRAG, a document Q&A assistant  "
    "internal company documents stored in the Notion library.\n\n"
    "Your ONLY purpose is to answer questions about company policies, HR, security, "
    "finance, compliance, legal, contracts, and operational documents.\n\n"
    "STRICT RULES — never violate these:\n"
    "1. NEVER answer coding questions, math, general knowledge, science, history, "
    "or any topic not in the company documents.\n"
    "2. NEVER answer questions about specific people by name unless they appear "
    "in a retrieved document excerpt provided to you.\n"
    "3. NEVER fabricate, assume, or infer facts not explicitly in the document excerpts.\n"
    "4. NEVER answer about future dates, projections, or plans unless explicitly "
    "stated in the documents.\n"
    "5. If the SPECIFIC information asked for is NOT in the retrieved documents, "
    "respond with ONLY: 'I could not find this information in the available documents.' "
    "Do NOT mention what you did find. Do NOT speculate. Do NOT add anything else.\n"
    "6. Always cite sources using [1], [2] etc. for every factual claim.\n"
    "7. NEVER combine partial or unrelated information from documents to imply an answer. "
    "Only answer if the EXACT information requested is explicitly present in the excerpts.\n\n"
    "If asked anything outside company documents, respond: "
    "'I can only answer questions about company documents. "
    "Please ask about HR policies, security controls, compliance, contracts, or other company topics.'"
)


def _chat(messages: list, temperature: float = 0.2, max_tokens: int = 800) -> str:
    """Simple wrapper for Azure OpenAI chat completion."""
    resp = get_chat_client().chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ── STEP 1: Query Router ─────────────────────────────────────────────────────

def classify_query(query: str) -> dict:
    """
    Classify the query into one of 4 retrieval paths.
    Returns {"path": str, "reasoning": str, "doc_hint": str | None}

    Paths:
      no_retrieval     — greeting, simple definition, meta question
      single_retrieval — specific policy/doc lookup
      multi_step       — comparison, analysis across multiple docs
      compare          — explicit "compare X vs Y" request
    """
    prompt = f"""You are a query classifier for a document Q&A system that contains company policies and documents.
Classify the following query into exactly one of these paths:

- no_retrieval: ONLY for pure greetings like "hello", "hi", "how are you",
  or questions about what THIS system can do like "what can you do?".
  NEVER use this for any question about a person, topic, document, or company matter.

- out_of_scope: For questions that cannot be answered from company documents:
  * Coding / programming questions (e.g. "write python code", "fibonacci series")
  * General world knowledge (e.g. "who is the president", "what is machine learning")
  * Math / trivia / jokes
  * Questions about specific people by name (e.g. "who is Malav?", "who is John?")
    UNLESS the question is clearly about their role in a company document
    (e.g. "what is the CEO's policy on remote work" is fine as single_retrieval)
  Use this to politely decline.

- single_retrieval: Any question about company policies, HR, security, finance,
  compliance, legal, engineering, contracts, or any business topic.
  Includes vague queries like "hr stuff", "security?", "tell me about contracts".

- multi_step: Complex questions requiring reasoning across multiple documents.
  (e.g. "What compliance requirements appear across all departments?")

- compare: Explicit request to compare two specific documents or topics.
  (e.g. "Compare the SOW vs MSA")

Query: "{query}"

Respond with JSON only:
{{"path": "no_retrieval|single_retrieval|multi_step|compare", "reasoning": "one line explanation", "doc_hint": "specific document name if mentioned or null"}}"""

    raw = _chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=150)
    try:
        clean  = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        logger.info(f"[classify] query='{query[:60]}' → path={result.get('path')} reason={result.get('reasoning','')[:60]}")
        return result
    except Exception:
        logger.warning(f"[classify] Failed to parse response for query='{query[:60]}' — falling back to single_retrieval")
        return {"path": "single_retrieval", "reasoning": "fallback", "doc_hint": None}


# ── STEP 1b: Query Refinement ────────────────────────────────────────────────

def refine_query(query: str) -> str:
    """
    Rewrites vague or ambiguous queries into clear, specific search queries
    before hitting Milvus. Only called for single_retrieval and multi_step paths.

    Examples:
      "what about security?"
        → "What are the security controls and policies for data protection?"

      "tell me about hr stuff"
        → "What are the HR policies regarding employee conduct and remote work?"

      "compliance things"
        → "What compliance requirements and regulatory frameworks apply across departments?"

    If the query is already clear and specific, returns it unchanged.
    """
    prompt = f"""You are a search query optimizer for a document Q&A system.
Rewrite the following query to be clear, specific, and optimized for document retrieval.

Rules:
- If the query is already clear and specific, return it EXACTLY as-is
- If vague, expand it into a precise question
- Keep it as a single sentence question
- Do NOT add information not implied by the original query
- Do NOT change the intent of the query

Original query: "{query}"

Respond with ONLY the rewritten query — no explanation, no quotes."""

    refined = _chat(
        [{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=100,
    ).strip().strip('"').strip("'")

    # Safety — if something went wrong, return original
    if not refined or len(refined) < 5:
        logger.warning(f"[refine] Got empty result for query='{query[:60]}' — using original")
        return query

    if refined != query:
        logger.info(f"[refine] '{query[:60]}' → '{refined[:60]}'")
    else:
        logger.info(f"[refine] Query unchanged: '{query[:60]}'")

    return refined

# MMR config
MMR_FETCH_K   = 20    # fetch more candidates from Milvus before MMR reranking
MMR_LAMBDA    = 0.6   # 0 = max diversity, 1 = max relevance (0.6 = balanced)


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Simple cosine similarity between two vectors."""
    import math
    dot   = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def mmr_rerank(
    query_vector: list[float],
    chunks:       list[dict],
    top_k:        int,
    lambda_val:   float = MMR_LAMBDA,
) -> list[dict]:
    """
    Maximal Marginal Relevance reranking.
    Uses pre-fetched vectors stored in chunk["_vec"] — no re-embedding needed.

    Formula: MMR = argmax[ λ * sim(chunk, query) - (1-λ) * max(sim(chunk, selected)) ]
    lambda_val = 0.7 means 70% relevance, 30% diversity
    """
    if not chunks or top_k >= len(chunks):
        # Clean _vec before returning
        for c in chunks:
            c.pop("_vec", None)
        return chunks[:top_k]

    selected  = []
    remaining = list(range(len(chunks)))

    while len(selected) < top_k and remaining:
        mmr_scores = []
        for idx in remaining:
            vec       = chunks[idx].get("_vec")
            if not vec:
                mmr_scores.append((idx, chunks[idx]["score"]))
                continue

            rel_score = _cosine_similarity(query_vector, vec)
            div_score = max(
                (_cosine_similarity(vec, chunks[s]["_vec"])
                 for s in selected if chunks[s].get("_vec")),
                default=0.0
            )
            mmr = lambda_val * rel_score - (1 - lambda_val) * div_score
            mmr_scores.append((idx, mmr))

        best_idx = max(mmr_scores, key=lambda x: x[1])[0]
        selected.append(best_idx)
        remaining.remove(best_idx)

    result = []
    for idx in selected:
        c = chunks[idx].copy()
        c.pop("_vec", None)
        c["score"] = round(c["score"], 4)
        result.append(c)

    return result


def retrieve_chunks(
    query: str,
    top_k: int = TOP_K,
    industry: str | None = None,
    doc_type: str | None = None,
) -> list[dict]:
    """
    Embed query → fetch MMR_FETCH_K candidates from Milvus
    → MMR rerank → return top_k diverse + relevant chunks.
    """
    # Check retrieval cache first — avoids re-embedding + re-searching
    cached = get_retrieval_cache(query, industry, doc_type)
    if cached is not None:
        logger.info(f"[retrieve] Cache HIT — query='{query[:60]}'")
        return cached

    logger.info(f"[retrieve] Cache MISS — embedding + searching query='{query[:60]}' filters=industry:{industry} doc_type:{doc_type}")
    t0           = time.time()
    query_vector = embed_texts([query])[0]
    client       = get_client()

    filters = []
    if industry and industry != "All":
        filters.append(f'industry == "{industry}"')
    if doc_type and doc_type != "All":
        filters.append(f'doc_type == "{doc_type}"')
    filter_expr = " && ".join(filters) if filters else ""

    # Fetch more candidates than needed so MMR has room to diversify
    fetch_k = max(MMR_FETCH_K, top_k * 3)

    search_params = {
        "collection_name": COLLECTION_NAME,
        "data":            [query_vector],
        "limit":           fetch_k,
        "output_fields":   ["chunk_id", "page_id", "doc_title", "section_heading",
                            "doc_type", "industry", "version", "chunk_index", "raw_text"],
        "search_params":   {"metric_type": "COSINE"},
        "anns_field":      "embedding",
    }
    if filter_expr:
        search_params["filter"] = filter_expr

    results    = client.search(**search_params)
    candidates = []
    for hit in results[0]:
        e = hit.get("entity", {})
        candidates.append({
            "chunk_id":        e.get("chunk_id"),
            "page_id":         e.get("page_id"),
            "doc_title":       e.get("doc_title"),
            "section_heading": e.get("section_heading"),
            "doc_type":        e.get("doc_type"),
            "industry":        e.get("industry"),
            "raw_text":        e.get("raw_text"),
            "score":           round(float(hit.get("distance", 0)), 4),
            # Pass the Milvus distance as a proxy vector signal for MMR
            # We store the query_vector similarity as _vec approximation
            "_vec":            None,  # will be set below
        })

    # Fetch actual stored vectors for MMR inter-chunk diversity computation
    # This avoids re-embedding — we get vectors directly from Milvus
    if candidates:
        chunk_ids = [c["chunk_id"] for c in candidates if c["chunk_id"]]
        try:
            vec_results = client.query(
                collection_name=COLLECTION_NAME,
                filter=f'chunk_id in {json.dumps(chunk_ids)}',
                output_fields=["chunk_id", "embedding"],
                limit=len(chunk_ids),
            )
            vec_map = {r["chunk_id"]: r["embedding"] for r in vec_results}
            for c in candidates:
                c["_vec"] = vec_map.get(c["chunk_id"])

        except Exception as e:
            logger.warning(f"[retrieve] Could not fetch vectors for MMR: {e}")

    # Apply MMR reranking using fetched vectors — no re-embedding needed
    logger.info(f"[retrieve] Milvus returned {len(candidates)} candidates in {time.time()-t0:.2f}s — running MMR")
    reranked = mmr_rerank(query_vector, candidates, top_k)
    logger.info(f"[retrieve] MMR selected {len(reranked)} chunks: {[c['doc_title'][:25] + ' → ' + c['section_heading'][:15] for c in reranked]}")

    # Cache the final reranked results
    set_retrieval_cache(query, industry, doc_type, reranked)
    return reranked


def retrieve_multi_step(query: str, top_k: int = TOP_K) -> list[dict]:
    """
    Multi-step retrieval — iteratively refines the query to get
    broader coverage across multiple documents.
    Step 1: retrieve with original query
    Step 2: generate a follow-up query from gaps, retrieve again
    Step 3: merge and deduplicate results
    """
    # Step 1 — initial retrieval
    chunks_1 = retrieve_chunks(query, top_k=top_k)

    # Step 2 — generate a follow-up query to fill gaps
    context_so_far = "\n".join(
        f"- {c['doc_title']} → {c['section_heading']}" for c in chunks_1
    )
    followup_prompt = f"""Given this question: "{query}"
And these already-retrieved document sections:
{context_so_far}

Generate ONE follow-up search query to find additional relevant information 
that was NOT covered by the above sections. 
Respond with just the query string, nothing else."""

    followup_query = _chat(
        [{"role": "user", "content": followup_prompt}],
        temperature=0.3, max_tokens=80
    )

    # Step 3 — retrieve with follow-up query
    chunks_2 = retrieve_chunks(followup_query, top_k=top_k)

    # Merge and deduplicate by chunk_id
    seen = set()
    merged = []
    for c in chunks_1 + chunks_2:
        if c["chunk_id"] not in seen:
            seen.add(c["chunk_id"])
            merged.append(c)

    # Return top chunks sorted by score
    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged[:top_k * 2]


def retrieve_for_compare(query: str) -> tuple[list[dict], list[dict]]:
    """
    For compare queries — extract the two doc names and retrieve
    chunks from each separately.
    Returns (chunks_doc1, chunks_doc2)
    """
    # Extract the two documents being compared
    extract_prompt = f"""From this comparison query, extract the two document/topic names being compared.
Query: "{query}"
Respond with JSON only: {{"doc1": "first document name", "doc2": "second document name"}}"""

    raw = _chat([{"role": "user", "content": extract_prompt}], temperature=0, max_tokens=80)
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        docs = json.loads(clean)
        doc1, doc2 = docs.get("doc1", ""), docs.get("doc2", "")
    except Exception:
        # Fall back to regular retrieval if parsing fails
        chunks = retrieve_chunks(query, top_k=10)
        mid = len(chunks) // 2
        return chunks[:mid], chunks[mid:]

    chunks_1 = retrieve_chunks(doc1, top_k=5)
    chunks_2 = retrieve_chunks(doc2, top_k=5)
    return chunks_1, chunks_2


# ── STEP 3: Answer generation ────────────────────────────────────────────────

def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        citation = (f"{c['doc_title']} → {c['section_heading']}"
                    if c.get("section_heading") else c["doc_title"])
        parts.append(f"[{i}] {citation}\n{c['raw_text']}")
    return "\n\n---\n\n".join(parts)


def generate_answer(
    query: str,
    chunks: list[dict],
    chat_history: list[dict] | None = None,
) -> str:
    """Generate grounded answer from retrieved chunks with inline citations.
    Accepts optional chat_history for multi-turn memory.
    chat_history = [{"role": "user"|"assistant", "content": "..."}]
    """
    if not chunks:
        return "I could not find any relevant documents to answer your question."

    context = _build_context(chunks)
    system = CITERAG_SYSTEM

    # Build messages — system + history + current question
    messages = [{"role": "system", "content": system}]

    # Add last N turns of chat history for context (last 6 messages = 3 turns)
    if chat_history:
        for msg in chat_history[-6:]:
            role    = msg.get("role", "user")
            content = msg.get("content", "")
            # Only include user and assistant messages, skip empty
            if role in ("user", "assistant") and content.strip():
                messages.append({"role": role, "content": content})

    # Add current question with document context
    user_msg = f"""Document excerpts:
{context}

Question: {query}

Answer (with inline citations):"""

    messages.append({"role": "user", "content": user_msg})

    return _chat(messages)


def generate_compare_answer(query: str, chunks_1: list[dict], chunks_2: list[dict]) -> str:
    """Generate a side-by-side comparison answer."""
    ctx_1 = _build_context(chunks_1)
    ctx_2 = _build_context(chunks_2)

    system = CITERAG_SYSTEM + """
When comparing documents, use structured format with similarities and differences.
Cite sources as [A1], [A2] for first document and [B1], [B2] for second document."""

    user = f"""Query: {query}

=== DOCUMENT SET A ===
{ctx_1}

=== DOCUMENT SET B ===
{ctx_2}

Provide a clear comparison with:
1. Key similarities
2. Key differences
3. Summary recommendation"""

    return _chat([
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ], max_tokens=1200)


# ── STEP 4: LLM-as-Judge (Self-RAG style) ───────────────────────────────────

def judge_answer(query: str, answer: str, chunks: list[dict]) -> dict:
    """
    Self-RAG style grounding check.
    Verifies the answer is supported by retrieved chunks.
    Returns {"grounded": bool, "reason": str}
    """
    context = _build_context(chunks)
    prompt = f"""You are a strict fact-checker for a document Q&A system.
Check if EVERY factual claim in the answer is directly supported by the provided document excerpts.

Rules:
- If the answer states a specific number, date, name, or figure — it MUST appear in the excerpts
- If the answer implies a time period (e.g. "for 2027") that is NOT in the excerpts — it is NOT grounded
- Do NOT accept reasonable inference or extrapolation as grounded
- Only mark as grounded=true if every single claim has direct evidence in the excerpts

Document excerpts:
{context}

Question: {query}
Answer: {answer}

Respond with JSON only:
{{"grounded": true/false, "reason": "brief explanation of what is or is not supported"}}"""

    raw = _chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=150)
    try:
        clean   = raw.replace("```json", "").replace("```", "").strip()
        verdict = json.loads(clean)
        logger.info(f"[judge] grounded={verdict.get('grounded')} reason={verdict.get('reason','')[:80]}")
        return verdict
    except Exception:
        logger.warning("[judge] Failed to parse verdict — defaulting to grounded=True")
        return {"grounded": True, "reason": "Could not parse judge response"}


# ── MAIN: Full Adaptive RAG pipeline ─────────────────────────────────────────

def rag_query(
    query:        str,
    industry:     str | None = None,
    doc_type:     str | None = None,
    top_k:        int = TOP_K,
    chat_history: list[dict] | None = None,
    run_eval:     bool = False,
) -> dict:
    """
    Full adaptive RAG pipeline:
    1. Classify query → choose path
    2. Retrieve based on path
    3. Generate answer
    4. Judge answer (Self-RAG style)
    Returns {answer, chunks, grounded, sources, path}
    """

    t_start = time.time()
    logger.info(f"[rag_query] START query='{query[:80]}' industry={industry} doc_type={doc_type}")

    # ── 1. Classify ──────────────────────────────────────────
    classification = classify_query(query)
    path = classification.get("path", "single_retrieval")
    refined_query  = query  # default — overwritten for single/multi_step paths

    # ── 2. Route to correct retrieval path ───────────────────

    # PATH 1 — No retrieval needed (greetings / meta questions)
    if path == "no_retrieval":
        messages = [{"role": "system", "content": CITERAG_SYSTEM}]
        if chat_history:
            for msg in chat_history[-6:]:
                if msg.get("role") in ("user", "assistant") and msg.get("content", "").strip():
                    messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})
        answer = _chat(messages)
        logger.info(f"[rag_query] DONE path=no_retrieval time={time.time()-t_start:.2f}s")
        return {
            "answer":   answer,
            "chunks":   [],
            "grounded": True,
            "sources":  [],
            "path":     "no_retrieval",
        }

    # PATH 0 — Out of scope (coding, general knowledge, off-topic)
    if path == "out_of_scope":
        answer = (
            "I'm CiteRAG — a document Q&A assistant for company policies and documents. "
            "I can only answer questions about your Notion document library. "
            "Try asking about HR policies, security controls, compliance requirements, or contracts."
        )
        logger.info(f"[rag_query] DONE path=out_of_scope time={time.time()-t_start:.2f}s")
        return {
            "answer":   answer,
            "chunks":   [],
            "grounded": True,
            "sources":  [],
            "path":     "out_of_scope",
        }

    # PATH 4 — Compare two documents
    if path == "compare":
        chunks_1, chunks_2 = retrieve_for_compare(query)
        all_chunks = chunks_1 + chunks_2

        if not all_chunks:
            return {
                "answer":   "Could not find the documents you want to compare.",
                "chunks":   [],
                "grounded": True,
                "sources":  [],
                "path":     "compare",
            }

        answer  = generate_compare_answer(query, chunks_1, chunks_2)
        verdict = judge_answer(query, answer, all_chunks)

        if not verdict.get("grounded", True):
            answer = (f"⚠️ **Grounding check failed** — {verdict.get('reason', '')}\n\n---\n\n{answer}")

        sources = list(dict.fromkeys(
            f"{c['doc_title']} → {c['section_heading']}" if c.get("section_heading") else c["doc_title"]
            for c in all_chunks
        ))

        # Run full RAGAS for compare — all 4 metrics using synthetic reference
        ragas_scores = None
        if run_eval and all_chunks:
            try:
                ragas_scores = evaluate_rag(
                    query  = query,
                    answer = answer,
                    chunks = all_chunks,
                )
                logger.info(f"[rag_query] RAGAS scores (compare): {ragas_scores}")
            except Exception as e:
                logger.warning(f"[rag_query] RAGAS failed for compare: {e}")

        logger.info(f"[rag_query] DONE path=compare chunks={len(all_chunks)} time={time.time()-t_start:.2f}s")
        return {
            "answer":        answer,
            "chunks":        all_chunks,
            "grounded":      verdict.get("grounded", True),
            "sources":       sources,
            "path":          "compare",
            "ragas_scores":  ragas_scores,
        }

    # PATH 3 — Multi-step iterative retrieval
    if path == "multi_step":
        refined_query = refine_query(query)
        chunks = retrieve_multi_step(refined_query, top_k=top_k)
    else:
        # PATH 2 — Single retrieval (default)
        refined_query = refine_query(query)
        chunks = retrieve_chunks(refined_query, top_k=top_k, industry=industry, doc_type=doc_type)

    if not chunks:
        return {
            "answer":   "No relevant documents found. Try a different question or remove any filters.",
            "chunks":   [],
            "grounded": True,
            "sources":  [],
            "path":     path,
        }

    # ── 3. Generate ───────────────────────────────────────────
    answer = generate_answer(query, chunks, chat_history=chat_history)

    # ── 4. Judge (Self-RAG style) ─────────────────────────────
    verdict = judge_answer(query, answer, chunks)

    if not verdict.get("grounded", True):
        answer = (
            f"⚠️ **This answer could not be verified against your documents.**\n\n"
            f"Reason: {verdict.get('reason', '')}\n\n"
            f"The retrieved documents may not contain the specific information requested. "
            f"Please verify directly in your source documents.\n\n---\n\n{answer}"
        )

    sources = list(dict.fromkeys(
        f"{c['doc_title']} → {c['section_heading']}" if c.get("section_heading") else c["doc_title"]
        for c in chunks
    ))

    # ── 5. RAGAS evaluation (optional — only when run_eval=True) ──
    ragas_scores = None
    if run_eval:
        # Use refined_query for evaluation — more accurate than vague original
        eval_query = refined_query if 'refined_query' in dir() else query
        ragas_scores = evaluate_rag(query=eval_query, answer=answer, chunks=chunks)
        logger.info(f"[rag_query] RAGAS scores: {ragas_scores}")

    logger.info(
        f"[rag_query] DONE path={path} chunks={len(chunks)} "
        f"grounded={verdict.get('grounded')} time={time.time()-t_start:.2f}s"
    )

    return {
        "answer":        answer,
        "chunks":        chunks,
        "grounded":      verdict.get("grounded", True),
        "sources":       sources,
        "path":          path,
        "ragas_scores":  ragas_scores,
    }