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
from openai import AzureOpenAI
from app.services.embeddings import embed_texts
from app.rag_config import get_client, COLLECTION_NAME, TOP_K

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
    prompt = f"""You are a query classifier for a document Q&A system.
Classify the following query into exactly one of these paths:

- no_retrieval: Simple greetings, meta questions about the system, 
  or questions you can answer without any documents 
  (e.g. "hello", "what can you do?", "what is GDPR?")

- single_retrieval: Questions about a specific policy, document, 
  or topic that can be answered by retrieving relevant sections 
  (e.g. "What is the remote work policy?", "What are the security controls?")

- multi_step: Complex questions requiring reasoning across multiple 
  documents or multiple retrieval rounds 
  (e.g. "How do security policies across all departments compare?",
   "What are all the compliance requirements mentioned in every document?")

- compare: Explicit request to compare two specific documents or sections 
  (e.g. "Compare the SOW vs MSA", "What is different between the HR policy and remote work policy?")

Query: "{query}"

Respond with JSON only:
{{"path": "no_retrieval|single_retrieval|multi_step|compare", "reasoning": "one line explanation", "doc_hint": "specific document name if mentioned or null"}}"""

    raw = _chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=150)
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception:
        # Default to single retrieval if parsing fails
        return {"path": "single_retrieval", "reasoning": "fallback", "doc_hint": None}


# ── STEP 2: Retrieval functions ──────────────────────────────────────────────

def retrieve_chunks(
    query: str,
    top_k: int = TOP_K,
    industry: str | None = None,
    doc_type: str | None = None,
) -> list[dict]:
    """Embed query → search Milvus → return top_k chunks."""
    query_vector = embed_texts([query])[0]
    client = get_client()

    filters = []
    if industry and industry != "All":
        filters.append(f'industry == "{industry}"')
    if doc_type and doc_type != "All":
        filters.append(f'doc_type == "{doc_type}"')
    filter_expr = " && ".join(filters) if filters else ""

    search_params = {
        "collection_name": COLLECTION_NAME,
        "data": [query_vector],
        "limit": top_k,
        "output_fields": ["chunk_id", "page_id", "doc_title", "section_heading",
                          "doc_type", "industry", "version", "chunk_index", "raw_text"],
        "search_params": {"metric_type": "COSINE"},
    }
    if filter_expr:
        search_params["filter"] = filter_expr

    results = client.search(**search_params)
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
    return chunks


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


def generate_answer(query: str, chunks: list[dict]) -> str:
    """Generate grounded answer from retrieved chunks with inline citations."""
    if not chunks:
        return "I could not find any relevant documents to answer your question."

    context = _build_context(chunks)
    system = """You are CiteRAG, a document Q&A assistant.
Answer ONLY using the provided document excerpts.
Rules:
- Always cite sources inline using [1], [2] etc.
- If the answer is not in the context, say so explicitly — do NOT guess.
- Be concise and professional."""

    user = f"""Document excerpts:
{context}

Question: {query}

Answer (with inline citations):"""

    return _chat([
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ])


def generate_compare_answer(query: str, chunks_1: list[dict], chunks_2: list[dict]) -> str:
    """Generate a side-by-side comparison answer."""
    ctx_1 = _build_context(chunks_1)
    ctx_2 = _build_context(chunks_2)

    system = """You are CiteRAG, a document comparison assistant.
Compare the two sets of documents clearly and concisely.
Use a structured format with sections for similarities and differences.
Always cite sources inline using [A1], [A2] for first doc and [B1], [B2] for second doc."""

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
    prompt = f"""You are a strict fact-checker.
Check if this answer is fully supported by the provided document excerpts.
Do NOT penalize for reasonable inference — only flag unsupported claims.

Document excerpts:
{context}

Question: {query}
Answer: {answer}

Respond with JSON only:
{{"grounded": true/false, "reason": "brief explanation"}}"""

    raw = _chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=150)
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception:
        return {"grounded": True, "reason": "Could not parse judge response"}


# ── MAIN: Full Adaptive RAG pipeline ─────────────────────────────────────────

def rag_query(
    query:    str,
    industry: str | None = None,
    doc_type: str | None = None,
    top_k:    int = TOP_K,
) -> dict:
    """
    Full adaptive RAG pipeline:
    1. Classify query → choose path
    2. Retrieve based on path
    3. Generate answer
    4. Judge answer (Self-RAG style)
    Returns {answer, chunks, grounded, sources, path}
    """

    # ── 1. Classify ──────────────────────────────────────────
    classification = classify_query(query)
    path = classification.get("path", "single_retrieval")

    # ── 2. Route to correct retrieval path ───────────────────

    # PATH 1 — No retrieval needed
    if path == "no_retrieval":
        answer = _chat([
            {"role": "system", "content": "You are CiteRAG, a helpful document Q&A assistant. Answer briefly and helpfully."},
            {"role": "user",   "content": query},
        ])
        return {
            "answer":   answer,
            "chunks":   [],
            "grounded": True,
            "sources":  [],
            "path":     "no_retrieval",
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
        return {
            "answer":   answer,
            "chunks":   all_chunks,
            "grounded": verdict.get("grounded", True),
            "sources":  sources,
            "path":     "compare",
        }

    # PATH 3 — Multi-step iterative retrieval
    if path == "multi_step":
        chunks = retrieve_multi_step(query, top_k=top_k)
    else:
        # PATH 2 — Single retrieval (default)
        chunks = retrieve_chunks(query, top_k=top_k, industry=industry, doc_type=doc_type)

    if not chunks:
        return {
            "answer":   "No relevant documents found. Try a different question or remove any filters.",
            "chunks":   [],
            "grounded": True,
            "sources":  [],
            "path":     path,
        }

    # ── 3. Generate ───────────────────────────────────────────
    answer = generate_answer(query, chunks)

    # ── 4. Judge (Self-RAG style) ─────────────────────────────
    verdict = judge_answer(query, answer, chunks)

    if not verdict.get("grounded", True):
        answer = (
            f"⚠️ **Grounding check failed** — the answer may not be fully supported "
            f"by the retrieved documents.\n\nReason: {verdict.get('reason', '')}\n\n---\n\n{answer}"
        )

    sources = list(dict.fromkeys(
        f"{c['doc_title']} → {c['section_heading']}" if c.get("section_heading") else c["doc_title"]
        for c in chunks
    ))

    return {
        "answer":   answer,
        "chunks":   chunks,
        "grounded": verdict.get("grounded", True),
        "sources":  sources,
        "path":     path,
    }