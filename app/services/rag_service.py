"""
app/services/rag_service.py
Adaptive RAG with LLM-as-Judge (Self-RAG style).

Query router classifies every query into one of 5 paths:
  1. no_retrieval     — greetings, meta questions about the system
  2. out_of_scope     — coding, math, general world knowledge (NOT company topics)
  3. single_retrieval — targeted lookup, optional metadata filter
  4. multi_step       — complex reasoning across multiple docs
  5. compare          — side-by-side comparison of two documents

Special path:
  6. create_ticket    — user explicitly wants to raise a support ticket
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

# ── System persona ────────────────────────────────────────────────────────────
CITERAG_SYSTEM = (
    "You are CiteRAG, a document Q&A assistant for "
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
    "6. Always cite sources using [1], [2] etc. inline for every factual claim.\n"
    "7. NEVER combine partial or unrelated information from documents to imply an answer. "
    "Only answer if the EXACT information requested is explicitly present in the excerpts.\n"
    "8. NEVER add a 'References:', 'Sources:', or bibliography section at the end of your "
    "answer. The UI handles source display automatically. Only use inline citations like [1].\n\n"
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


# ── STEP 1: Query Router ──────────────────────────────────────────────────────

def classify_query(query: str, chat_history: list[dict] | None = None) -> dict:
    """
    Classify the query into one of 6 paths.
    Uses recent chat history to understand follow-up questions in context.
    Returns {"path": str, "reasoning": str, "doc_hint": str | None}
    """
    # Build recent context block for the classifier
    context_block = ""
    if chat_history:
        recent = [
            m for m in chat_history[-6:]
            if m.get("role") in ("user", "assistant") and m.get("content", "").strip()
        ]
        if recent:
            lines = []
            for m in recent:
                role = "User" if m["role"] == "user" else "CiteRAG"
                lines.append(f"{role}: {m['content'][:200]}")
            context_block = (
                "Recent conversation (use this to understand vague follow-ups):\n"
                + "\n".join(lines)
                + "\n\n"
            )

    prompt = f"""{context_block}You are a query classifier for a document Q&A system containing company policies and internal business documents.
Classify the LATEST USER QUERY into exactly one of these paths.
Use the conversation context above to understand vague or follow-up questions.

- no_retrieval: ONLY for:
  * Pure greetings ("hello", "hi", "how are you")
  * Questions about what THIS system can do ("what can you do?", "help")
  * Questions about the CURRENT CONVERSATION itself answerable from memory only:
    - "what was my first message", "summarise our chat", "what did we just discuss"
    - "why did we create that ticket" (ticket created in this chat session)
  CRITICAL: If the question contains "in doc", "in the document", "show me",
  "find", "search", or refers to Notion library content — use single_retrieval.

- out_of_scope: ONLY for questions with ZERO chance of being in company documents
  AND are not follow-ups to a previous company topic:
  * Coding, math, science, general world knowledge, jokes, creative writing
  IMPORTANT: If the user is continuing a conversation about a company topic —
  even with vague language like "what about that", "like in a library",
  "the one we discussed" — use single_retrieval, NOT out_of_scope.

- create_ticket: User explicitly wants to create or raise a support ticket.

- single_retrieval: ANY question about the company or its documents, plus
  any vague follow-up that relates to a previous company topic.
  When in doubt between out_of_scope and single_retrieval → use single_retrieval.

- multi_step: Complex questions requiring reasoning across multiple documents.

- compare: Explicit request to compare two specific documents or topics.

Latest user query: "{query}"

Respond with JSON only:
{{"path": "no_retrieval|out_of_scope|create_ticket|single_retrieval|multi_step|compare", "reasoning": "one line explanation", "doc_hint": "specific document name if mentioned or null"}}"""

    raw = _chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=150)
    try:
        clean  = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        logger.info(f"[classify] query='{query[:60]}' → path={result.get('path')} reason={result.get('reasoning','')[:60]}")
        return result
    except Exception:
        logger.warning(f"[classify] Failed to parse — falling back to single_retrieval")
        return {"path": "single_retrieval", "reasoning": "fallback", "doc_hint": None}


# ── STEP 1b: Query Refinement ─────────────────────────────────────────────────

def refine_query(query: str) -> str:
    """
    Rewrites vague or ambiguous queries into clear, specific search queries
    before hitting Milvus.
    """
    prompt = f"""You are a search query optimizer for a document Q&A system.
Rewrite the following query to be clear, specific, and optimized for document retrieval.

Rules:
- If the query is already clear and specific, return it EXACTLY as-is
- If vague, expand it into a precise question
- Keep it as a single sentence question
- Do NOT add information not implied by the original query
- Do NOT change the intent of the query
- NEVER include citation references like [1], [2], [3] in the output
- NEVER add phrases like "according to documents" or "as mentioned in"
- Output ONLY the clean search query — nothing else

Original query: "{query}"

Respond with ONLY the rewritten query — no explanation, no quotes, no citations."""

    refined = _chat(
        [{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=100,
    ).strip().strip('"').strip("'")

    if not refined or len(refined) < 5:
        logger.warning(f"[refine] Got empty result — using original")
        return query

    if refined != query:
        logger.info(f"[refine] '{query[:60]}' → '{refined[:60]}'")
    else:
        logger.info(f"[refine] Query unchanged: '{query[:60]}'")

    return refined


# ── STEP 1c: Extract ticket topic from explicit ticket request ─────────────────

def extract_ticket_topic(query: str) -> str:
    """
    When user explicitly asks to create a ticket, extract what the ticket
    should actually be about.

    Examples:
      "create a ticket about the leave policy"
        → "What is the leave policy?"
      "raise a support ticket for my question about expense reimbursement"
        → "What is the expense reimbursement policy?"
      "i want to log a ticket"
        → original query (no topic found)
    """
    prompt = f"""The user wants to create a support ticket.
Extract the actual question or topic the ticket should be about.
If a clear topic is mentioned, rephrase it as a clean question.
If no specific topic is mentioned, return the original message as-is.

User message: "{query}"

Respond with ONLY the extracted question — no explanation, no quotes."""

    try:
        result = _chat(
            [{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=100,
        ).strip().strip('"').strip("'")
        if result and len(result) > 5:
            logger.info(f"[extract_ticket_topic] '{query[:60]}' → '{result[:60]}'")
            return result
    except Exception as e:
        logger.warning(f"[extract_ticket_topic] Failed: {e}")

    return query


# ── MMR config ────────────────────────────────────────────────────────────────

MMR_FETCH_K = 30    # increased from 20 — more candidates before MMR
MMR_LAMBDA  = 0.75  # increased from 0.6 — more relevance, less diversity penalty
                    # prevents penalising two chunks from the same relevant doc


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
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
    """Maximal Marginal Relevance reranking."""
    if not chunks or top_k >= len(chunks):
        for c in chunks:
            c.pop("_vec", None)
        return chunks[:top_k]

    selected  = []
    remaining = list(range(len(chunks)))

    while len(selected) < top_k and remaining:
        mmr_scores = []
        for idx in remaining:
            vec = chunks[idx].get("_vec")
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


def generate_sub_queries(query: str) -> list[str]:
    """
    For complex queries, generate 2-3 focused sub-queries that together
    cover all aspects of the original question.
    """
    prompt = f"""You are a search query decomposer for a document retrieval system.

Break the following question into 2-3 keyword-dense search queries for vector search.
Each sub-query must target a DIFFERENT aspect. Make them short, specific, keyword-rich.

Original question: "{query}"

Rules:
- Each sub-query should be 4-8 keywords, NO full sentences
- If asking about a person AND their role/position: one query for the person details, one for the job title/position
- Use domain keywords: "job title", "position", "role", "offer letter", "employment contract", "candidate"
- Do NOT use full sentences or question format
- Do NOT repeat the same keywords across sub-queries
- Respond with ONLY the queries, one per line, no numbering

Examples:
Original: "who is John Smith and what role was offered?"
Output:
John Smith candidate personal details address
job title position offered employment offer letter John Smith

Original: "who signed the offer letter and what is the candidate address?"
Output:
signature block HR signatory name title offer letter
candidate address personal details offer letter

Original: "what is the leave policy and how to apply?"
Output:
leave policy annual sick casual entitlement days
leave application process HRMS portal submission"""

    try:
        raw = _chat(
            [{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=100,
        ).strip()
        queries = [q.strip() for q in raw.split("\n") if q.strip() and len(q.strip()) > 5]
        if not queries:
            return [query]
        # Always include original as fallback
        if query not in queries:
            queries.append(query)
        logger.info(f"[sub_queries] '{query[:50]}' → {queries}")
        return queries[:3]
    except Exception as e:
        logger.warning(f"[sub_queries] Failed: {e} — using original query")
        return [query]


def retrieve_chunks_no_mmr(
    query: str,
    top_k: int = TOP_K,
    industry: str | None = None,
    doc_type: str | None = None,
) -> list[dict]:
    """
    Pure cosine similarity retrieval — no MMR reranking.
    Used by multi-query retrieval where diversity comes from sub-queries,
    not from MMR within a single query.
    """
    cached = get_retrieval_cache(query + "__no_mmr", industry, doc_type)
    if cached is not None:
        return cached

    query_vector = embed_texts([query])[0]
    client       = get_client()

    filters = []
    if industry and industry != "All":
        filters.append(f'industry == "{industry}"')
    if doc_type and doc_type != "All":
        filters.append(f'doc_type == "{doc_type}"')
    filter_expr = " && ".join(filters) if filters else ""

    search_params = {
        "collection_name": COLLECTION_NAME,
        "data":            [query_vector],
        "limit":           top_k,
        "output_fields":   ["chunk_id", "page_id", "doc_title", "section_heading",
                            "doc_type", "industry", "version", "chunk_index", "raw_text"],
        "search_params":   {"metric_type": "COSINE"},
        "anns_field":      "embedding",
    }
    if filter_expr:
        search_params["filter"] = filter_expr

    results    = client.search(**search_params)
    chunks = []
    for hit in results[0]:
        e = hit.get("entity", {})
        chunks.append({
            "chunk_id":        e.get("chunk_id"),
            "page_id":         e.get("page_id"),
            "doc_title":       e.get("doc_title"),
            "section_heading": e.get("section_heading"),
            "doc_type":        e.get("doc_type"),
            "industry":        e.get("industry"),
            "raw_text":        e.get("raw_text"),
            "score":           round(float(hit.get("distance", 0)), 4),
        })

    set_retrieval_cache(query + "__no_mmr", industry, doc_type, chunks)
    return chunks


def retrieve_chunks_multi_query(
    query: str,
    top_k: int = TOP_K,
    industry: str | None = None,
    doc_type: str | None = None,
) -> list[dict]:
    """
    Multi-query retrieval using pure cosine similarity (no MMR).
    Generates sub-queries, retrieves for each, merges and deduplicates,
    returns top_k by score.
    MMR is skipped here because diversity comes from different sub-queries.
    """
    sub_queries = generate_sub_queries(query)

    seen  = {}   # chunk_id → chunk (keep highest score)
    freq  = {}   # chunk_id → how many sub-queries returned it

    for sq in sub_queries:
        chunks = retrieve_chunks_no_mmr(sq, top_k=top_k * 2, industry=industry, doc_type=doc_type)
        for c in chunks:
            cid = c.get("chunk_id")
            freq[cid] = freq.get(cid, 0) + 1
            if cid not in seen or c["score"] > seen[cid]["score"]:
                seen[cid] = c

    # Boost score for chunks appearing in multiple sub-queries
    for cid, chunk in seen.items():
        if freq.get(cid, 1) > 1:
            chunk["score"] = round(chunk["score"] * (1 + 0.15 * (freq[cid] - 1)), 4)

    merged = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    logger.info(f"[multi_query] {len(sub_queries)} sub-queries → {len(merged)} unique chunks → returning top {top_k}")
    return merged[:top_k]


def retrieve_chunks(
    query: str,
    top_k: int = TOP_K,
    industry: str | None = None,
    doc_type: str | None = None,
) -> list[dict]:
    """Embed query → fetch MMR_FETCH_K candidates → MMR rerank → return top_k."""
    cached = get_retrieval_cache(query, industry, doc_type)
    if cached is not None:
        logger.info(f"[retrieve] Cache HIT — query='{query[:60]}'")
        return cached

    logger.info(f"[retrieve] Cache MISS — query='{query[:60]}' filters=industry:{industry} doc_type:{doc_type}")
    t0           = time.time()
    query_vector = embed_texts([query])[0]
    client       = get_client()

    filters = []
    if industry and industry != "All":
        filters.append(f'industry == "{industry}"')
    if doc_type and doc_type != "All":
        filters.append(f'doc_type == "{doc_type}"')
    filter_expr = " && ".join(filters) if filters else ""

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
            "_vec":            None,
        })

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

    logger.info(f"[retrieve] {len(candidates)} candidates in {time.time()-t0:.2f}s — running MMR")
    reranked = mmr_rerank(query_vector, candidates, top_k)
    set_retrieval_cache(query, industry, doc_type, reranked)
    return reranked


def retrieve_multi_step(query: str, top_k: int = TOP_K) -> list[dict]:
    """Multi-step retrieval — two passes with follow-up query."""
    chunks_1 = retrieve_chunks(query, top_k=top_k)

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

    chunks_2 = retrieve_chunks(followup_query, top_k=top_k)

    seen   = set()
    merged = []
    for c in chunks_1 + chunks_2:
        if c["chunk_id"] not in seen:
            seen.add(c["chunk_id"])
            merged.append(c)

    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged[:top_k * 2]


def retrieve_for_compare(query: str) -> tuple[list[dict], list[dict]]:
    """Extract two doc names and retrieve chunks from each separately."""
    extract_prompt = f"""From this comparison query, extract the two document/topic names being compared.
Query: "{query}"
Respond with JSON only: {{"doc1": "first document name", "doc2": "second document name"}}"""

    raw = _chat([{"role": "user", "content": extract_prompt}], temperature=0, max_tokens=80)
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        docs  = json.loads(clean)
        doc1, doc2 = docs.get("doc1", ""), docs.get("doc2", "")
    except Exception:
        chunks = retrieve_chunks(query, top_k=10)
        mid    = len(chunks) // 2
        return chunks[:mid], chunks[mid:]

    chunks_1 = retrieve_chunks(doc1, top_k=5)
    chunks_2 = retrieve_chunks(doc2, top_k=5)
    return chunks_1, chunks_2


# ── STEP 3: Answer generation ─────────────────────────────────────────────────

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
    """Generate grounded answer from retrieved chunks with inline citations."""
    if not chunks:
        return "I could not find any relevant documents to answer your question."

    context  = _build_context(chunks)
    messages = [{"role": "system", "content": CITERAG_SYSTEM}]

    if chat_history:
        for msg in chat_history[-8:]:
            role    = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant", "system") and content.strip():
                messages.append({"role": role, "content": content})

    # Extract first_message from system context if present — inject prominently
    first_msg_note = ""
    if chat_history:
        sys_msg = next((m["content"] for m in chat_history if m.get("role") == "system"), "")
        if "very first message" in sys_msg:
            import re
            match = re.search(r'very first message.*?was: "(.+?)"', sys_msg)
            if match:
                first_msg_note = f"\n\nNote: The user's very first message in this conversation was: \"{match.group(1)}\""

    messages.append({"role": "user", "content": (
        f"Document excerpts:\n{context}\n\n"
        f"Question: {query}"
        f"{first_msg_note}\n\n"
        f"Answer (with inline citations):"
    )})

    return _chat(messages)


def generate_compare_answer(query: str, chunks_1: list[dict], chunks_2: list[dict]) -> str:
    """Generate a structured side-by-side comparison answer with a markdown table.
    Citations use [A1],[A2] for doc A and [B1],[B2] for doc B — matching the sources list.
    """
    # Build labelled contexts so citations match sources
    parts_1 = []
    for i, c in enumerate(chunks_1, 1):
        citation = (f"{c['doc_title']} → {c['section_heading']}"
                    if c.get("section_heading") else c["doc_title"])
        parts_1.append(f"[A{i}] {citation}\n{c['raw_text']}")
    ctx_1 = "\n\n---\n\n".join(parts_1)

    parts_2 = []
    for i, c in enumerate(chunks_2, 1):
        citation = (f"{c['doc_title']} → {c['section_heading']}"
                    if c.get("section_heading") else c["doc_title"])
        parts_2.append(f"[B{i}] {citation}\n{c['raw_text']}")
    ctx_2 = "\n\n---\n\n".join(parts_2)

    # Build reference list so UI can show matching sources
    ref_lines = []
    for i, c in enumerate(chunks_1, 1):
        label = (f"{c['doc_title']} → {c['section_heading']}"
                 if c.get("section_heading") else c["doc_title"])
        ref_lines.append(f"[A{i}] {label}")
    for i, c in enumerate(chunks_2, 1):
        label = (f"{c['doc_title']} → {c['section_heading']}"
                 if c.get("section_heading") else c["doc_title"])
        ref_lines.append(f"[B{i}] {label}")
    references = "\n".join(ref_lines)

    system = CITERAG_SYSTEM + """
When comparing documents follow this exact format:

1. Key Similarities — bullet points, cite as [A1], [B2] etc.
2. Key Differences — markdown table with columns: Aspect | Document A | Document B, cite inline
3. Summary Recommendation — short paragraph
4. References — list every citation used, one per line as: [A1] Doc → Section

Use ONLY [A1],[A2]... for Document A and [B1],[B2]... for Document B.
Every factual claim must have a citation."""

    user = f"""Query: {query}

=== DOCUMENT A ===
{ctx_1}

=== DOCUMENT B ===
{ctx_2}

Available references:
{references}

Provide:
1. Key Similarities (bullet points with citations)
2. Key Differences (markdown table: Aspect | Document A | Document B)
3. Summary Recommendation
4. References"""

    return _chat([
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ], max_tokens=1500)


# ── STEP 4: LLM-as-Judge ──────────────────────────────────────────────────────

def judge_answer(query: str, answer: str, chunks: list[dict]) -> dict:
    """
    Self-RAG grounding check. Returns {"grounded": bool, "reason": str}
    """
    if "I could not find this information" in answer:
        return {"grounded": True, "reason": "Correct not-found response"}

    context = _build_context(chunks)

    prompt = f"""You are a fact-checker for a document Q&A system.
Check if the answer is grounded in the provided document excerpts.

RULES:
1. Mark grounded=TRUE if every specific claim (names, numbers, dates, roles, addresses)
   appears explicitly in at least one excerpt.
2. It is FINE and CORRECT to combine information from multiple excerpts to form
   a complete answer — this is expected behaviour, NOT a grounding violation.
3. Mark grounded=FALSE ONLY if the answer contains specific facts that do NOT
   appear in ANY of the excerpts (fabricated information).
4. If the answer says "I could not find" but the info IS in the excerpts = FALSE.
5. Minor wording differences are fine — look for semantic equivalence, not exact match.
6. If most claims are grounded but one small detail is uncertain, still mark TRUE
   and note the uncertainty in the reason.

Document excerpts:
{context}

Question: {query}
Answer: {answer}

Respond with JSON only:
{{"grounded": true/false, "reason": "brief explanation"}}"""

    raw = _chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=150)
    try:
        clean   = raw.replace("```json", "").replace("```", "").strip()
        verdict = json.loads(clean)
        logger.info(f"[judge] grounded={verdict.get('grounded')} reason={verdict.get('reason','')[:80]}")
        return verdict
    except Exception:
        logger.warning("[judge] Failed to parse — defaulting to grounded=True")
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
    Full adaptive RAG pipeline (used by legacy /rag/chat endpoint).
    LangGraph /chat endpoint uses run_graph() instead.
    """
    t_start = time.time()
    logger.info(f"[rag_query] START query='{query[:80]}'")

    classification = classify_query(query)
    path           = classification.get("path", "single_retrieval")
    refined_query  = query

    # PATH: no_retrieval
    if path == "no_retrieval":
        messages = [{"role": "system", "content": (
            "You are CiteRAG, a helpful document Q&A assistant for Company Documents. "
            "Respond warmly to greetings and questions about what you can do. "
            "Keep responses short and friendly."
        )}]
        if chat_history:
            for msg in chat_history[-6:]:
                if msg.get("role") in ("user", "assistant") and msg.get("content", "").strip():
                    messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})
        answer = _chat(messages)
        return {"answer": answer, "chunks": [], "grounded": True, "sources": [], "path": "no_retrieval"}

    # PATH: out_of_scope
    if path == "out_of_scope":
        answer = (
            "I'm CiteRAG — a document Q&A assistant for Company Documents. "
            "I can only answer questions about your Notion document library. "
            "Try asking about HR policies, security controls, compliance requirements, or contracts."
        )
        return {"answer": answer, "chunks": [], "grounded": True, "sources": [], "path": "out_of_scope"}

    # PATH: create_ticket (user explicitly asked to create one)
    if path == "create_ticket":
        topic = extract_ticket_topic(query)
        answer = (
            f"I'll create a support ticket for: **\"{topic}\"**\n\n"
            "Please confirm — reply **yes** and I'll raise it right away."
        )
        return {
            "answer":        answer,
            "chunks":        [],
            "grounded":      True,
            "sources":       [],
            "path":          "create_ticket",
            "ticket_status": "pending_confirmation",
            "ragas_scores":  None,
        }

    # PATH: compare
    if path == "compare":
        chunks_1, chunks_2 = retrieve_for_compare(query)
        all_chunks = chunks_1 + chunks_2

        if not all_chunks:
            return {"answer": "Could not find the documents you want to compare.",
                    "chunks": [], "grounded": True, "sources": [], "path": "compare"}

        answer  = generate_compare_answer(query, chunks_1, chunks_2)
        verdict = judge_answer(query, answer, all_chunks)

        if not verdict.get("grounded", True):
            answer = f"⚠️ **Grounding check failed** — {verdict.get('reason', '')}\n\n---\n\n{answer}"

        sources = list(dict.fromkeys(
            f"{c['doc_title']} → {c['section_heading']}" if c.get("section_heading") else c["doc_title"]
            for c in all_chunks
        ))

        ragas_scores = None
        if run_eval and all_chunks:
            try:
                ragas_scores = evaluate_rag(query=query, answer=answer, chunks=all_chunks)
            except Exception as e:
                logger.warning(f"[rag_query] RAGAS failed for compare: {e}")

        return {
            "answer": answer, "chunks": all_chunks, "grounded": verdict.get("grounded", True),
            "sources": sources, "path": "compare", "ragas_scores": ragas_scores,
        }

    # PATH: multi_step
    if path == "multi_step":
        refined_query = refine_query(query)
        chunks        = retrieve_multi_step(refined_query, top_k=top_k)
    else:
        # PATH: single_retrieval (default)
        refined_query = refine_query(query)
        chunks        = retrieve_chunks(refined_query, top_k=top_k, industry=industry, doc_type=doc_type)

    if not chunks:
        return {"answer": "No relevant documents found. Try a different question or remove any filters.",
                "chunks": [], "grounded": True, "sources": [], "path": path}

    answer  = generate_answer(query, chunks, chat_history=chat_history)
    verdict = judge_answer(query, answer, chunks)

    if not verdict.get("grounded", True):
        answer = (
            f"⚠️ **This answer could not be verified against your documents.**\n\n"
            f"Reason: {verdict.get('reason', '')}\n\n"
            f"Please verify directly in your source documents.\n\n---\n\n{answer}"
        )

    sources = list(dict.fromkeys(
        f"{c['doc_title']} → {c['section_heading']}" if c.get("section_heading") else c["doc_title"]
        for c in chunks
    ))

    ragas_scores = None
    if run_eval:
        eval_query   = refined_query
        ragas_scores = evaluate_rag(query=eval_query, answer=answer, chunks=chunks)
        logger.info(f"[rag_query] RAGAS scores: {ragas_scores}")

    logger.info(f"[rag_query] DONE path={path} chunks={len(chunks)} grounded={verdict.get('grounded')} time={time.time()-t_start:.2f}s")

    return {
        "answer":       answer,
        "chunks":       chunks,
        "grounded":     verdict.get("grounded", True),
        "sources":      sources,
        "path":         path,
        "ragas_scores": ragas_scores,
    }