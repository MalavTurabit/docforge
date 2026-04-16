# 🔍 DocForge × CiteRAG Lab

**An integrated AI document platform** — DocForge generates professional business documents through a guided workflow, while CiteRAG Lab lets you query and retrieve answers from your Notion document library using Adaptive RAG. Both are powered by Azure OpenAI, built with FastAPI + Streamlit.

---

## Platform Overview

| App | Port | Purpose |
|---|---|---|
| **DocForge** | `8501` | AI-powered document generation |
| **CiteRAG Lab** | `8502` | Adaptive RAG Q&A over Notion library |
| **Shared API** | `8000` | FastAPI backend for both apps |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit (two apps, two ports) |
| Backend API | FastAPI |
| LLM | Azure OpenAI GPT-4.1-mini |
| Embeddings | Azure OpenAI text-embedding-3-large (3072-dim) |
| Vector DB | Milvus Lite (local, `./milvus.db`) |
| Document DB | MongoDB |
| Memory / Cache | Redis (session memory + retrieval cache) |
| RAG Orchestration | LangGraph (5-node StateGraph) |
| Ticket Management | Notion API |
| Evaluation | RAGAS 0.4.3 |
| Observability | LangSmith |
| PDF Generation | fpdf2 (DocForge) · ReportLab (CiteRAG eval reports) |
| Package Manager | uv |

---

## Project Structure

```
docforge/
├── app/
│   ├── main.py                        # FastAPI entry + global exception handlers
│   ├── config.py                      # Pydantic settings — loads all env vars
│   ├── db.py                          # MongoDB connection
│   ├── redis_client.py                # Redis singleton + CACHE_TTL
│   │
│   ├── routes/
│   │   ├── chat.py                    # POST /chat — CiteRAG LangGraph pipeline
│   │   ├── tickets.py                 # GET/POST/PATCH /tickets — Notion ticket CRUD
│   │   ├── evaluation.py              # POST /evaluation/report — PDF report generation
│   │   ├── sessions.py                # DocForge session endpoints + PDF + Notion publish
│   │   ├── departments.py             # GET /departments/ — Redis cached
│   │   ├── templates.py               # GET /templates/?dept_id= — Redis cached
│   │   ├── notion_library.py          # GET /notion/library — fetch all Notion docs
│   │   ├── rag.py                     # Legacy RAG endpoints
│   │   ├── sync.py                    # Notion sync endpoints
│   │   └── cache_routes.py            # DELETE /cache/bust, GET /cache/status
│   │
│   ├── graph/                         # LangGraph pipeline (CiteRAG)
│   │   ├── graph.py                   # StateGraph definition + run_graph()
│   │   ├── nodes.py                   # 5 nodes: intent, retrieval, evidence, answer, ticket
│   │   └── state.py                   # CiteRAGState TypedDict (21+ fields)
│   │
│   ├── tools/                         # LangChain @tool wrappers (CiteRAG)
│   │   ├── search_docs.py             # Wraps retrieve_chunks() — MMR retrieval
│   │   ├── search_docs_multi_step.py  # Two-pass retrieval for multi_step path
│   │   ├── refine_query.py            # Wraps refine_query()
│   │   ├── compare_docs.py            # Wraps generate_compare_answer()
│   │   ├── create_ticket.py           # Notion ticket creation + semantic dedup
│   │   └── run_evaluation.py          # Wraps evaluate_rag() — RAGAS scoring
│   │
│   ├── services/
│   │   ├── rag_service.py             # Core RAG brain — all retrieval + LLM logic
│   │   ├── memory_service.py          # HybridMemory — Redis session memory
│   │   ├── rag_cache.py               # Redis retrieval cache (TTL-based)
│   │   ├── eval_service.py            # RAGAS evaluation runner
│   │   ├── embeddings.py              # Azure OpenAI embedding wrapper
│   │   ├── llm_provider.py            # AzureChatOpenAI async wrapper (DocForge)
│   │   ├── question_service.py        # AI question generation (DocForge)
│   │   └── section_service.py         # AI section writing + enhancement (DocForge)
│   │
│   ├── rag_config.py                  # Milvus collection config + TOP_K
│   ├── docforge_app.py                # DocForge Streamlit frontend (~1100 lines)
│   └── citerag_app.py                 # CiteRAG Lab Streamlit frontend (~1350 lines)
│
├── pyproject.toml
├── .env                               # Secrets — never commit
├── .gitignore
└── README.md
```

---

## Setup

### 1. Clone and install
```bash
git clone https://github.com/MalavTurabit/docforge.git
cd docforge
uv sync
```

### 2. Start Redis
```bash
sudo apt install redis-server
sudo systemctl start redis
```

### 3. Create `.env`
```env
# Azure OpenAI — LLM
AZURE_OPENAI_LLM_KEY=your-key
AZURE_LLM_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_LLM_API_VERSION=2025-01-01-preview
AZURE_LLM_DEPLOYMENT_41_MINI=gpt-4.1-mini

# Azure OpenAI — Embeddings
AZURE_OPENAI_EMB_KEY=your-key
AZURE_OPENAI_EMB_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_EMB_API_VERSION=2024-12-01-preview
AZURE_OPENAI_EMB_DEPLOYMENT=text-embedding-3-large

# MongoDB
MONGO_URI=mongodb://localhost:27017
DB_NAME=docforge

# Redis
REDIS_URL=redis://localhost:6379/0

# Milvus
MILVUS_URI=./milvus.db

# Notion
NOTION_API_KEY=secret_xxx
NOTION_DATABASE_ID=31461ecb2bd28053910fe4d3ad65235b
NOTION_TICKET_DB_ID=32d61ecb2bd28093a8f4d9273f854f87

# LangSmith (optional — for tracing)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__your-key
LANGCHAIN_PROJECT=CiteRAG-Lab
```

---

## Running

All commands from inside `docforge/`:

```bash
# Terminal 1 — Shared FastAPI backend
uv run uvicorn app.main:app --reload

# Terminal 2 — DocForge UI
uv run streamlit run app/docforge_app.py --server.port 8501

# Terminal 3 — CiteRAG Lab UI
uv run streamlit run app/citerag_app.py --server.port 8502
```

- API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`
- DocForge: `http://localhost:8501`
- CiteRAG Lab: `http://localhost:8502`

### Utility commands

```bash
# Clear retrieval cache (run after changing MMR settings or syncing new docs)
uv run python -c "
from app.redis_client import get_redis
r = get_redis()
keys = r.keys('retrieve:*')
if keys: r.delete(*keys)
print(f'Cleared {len(keys)} cache entries')
"

# Draw LangGraph pipeline diagram
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from app.graph.graph import citerag_graph
with open('citerag_graph.png', 'wb') as f:
    f.write(citerag_graph.get_graph().draw_mermaid_png())
print('Saved: citerag_graph.png')
"

# Test retrieval for a query
uv run python -c "
from app.services.rag_service import retrieve_chunks
chunks = retrieve_chunks('your query here')
for c in chunks:
    print(f'{c[\"doc_title\"]} → {c[\"section_heading\"]} : {c[\"score\"]}')
"
```

---

## DocForge — Document Generation

### User Flow
```
Select Department → Select Template → Company Info → Generate Sections → Compile → Download / Publish
```

1. **Department** — choose from 10 departments
2. **Template** — filtered by department
3. **Company Info** — 6 fields injected into every AI call
4. **Generate** — section by section: AI asks questions → user answers → AI writes → user approves
5. **Compile** → Download PDF or Publish to Notion
6. **Enhance** — re-enhance any section with presets or custom prompt
7. **Library** — view all Notion-published docs, resume in-progress docs from sidebar

### Features
- Section-by-section guided workflow with context-aware AI questions
- Live document preview updates as sections are approved
- PDF: title page, running header, full markdown rendering, Unicode-safe
- Notion publish: direct API, markdown tables, rate limiting, version tracking (`v1`, `v2`...)
- AI Enhancement: 8 quick presets + custom prompt, side-by-side diff before accepting
- Redis caching for departments and templates (1 hour TTL)

---

## CiteRAG Lab — Adaptive RAG Q&A

### How It Works

Every query passes through a 5-node LangGraph pipeline:

```
User Query
    ↓
intent_node        → classifies into 7 paths
    ↓
retrieval_node     → MMR search / multi-query / compare
    ↓
evidence_check_node → LLM-as-judge (grounding check)
    ↓ can_answer=True          ↓ can_answer=False
answer_node                ticket_node
    ↓                          ↓
Final cited answer         Notion support ticket
```

### The 7 Intent Paths

| Path | Example | Action |
|---|---|---|
| `no_retrieval` | "hello", "what can you do?" | Direct LLM response, no search |
| `out_of_scope` | "write Python code" | Canned rejection |
| `create_doc` | "generate a contract" | Redirects to DocForge (:8501) |
| `create_ticket` | "raise a ticket about X" | Creates Notion ticket directly |
| `single_retrieval` | "what is the leave policy?" | MMR vector search → answer |
| `multi_step` | "compliance across all departments" | Two-pass iterative retrieval |
| `compare` | "compare Handbook vs Remote Policy" | A/B retrieval → comparison table |

### Retrieval Strategy

**Simple queries** — standard MMR retrieval:
- Embeds query (3072-dim) → fetches 30 candidates from Milvus → MMR rerank (λ=0.75) → top 5 chunks

**Complex queries** (contains "and"/"also", >8 words, multiple `?`) — multi-query retrieval:
- LLM generates 2-3 keyword-dense sub-queries targeting different aspects
- Pure cosine similarity per sub-query (no MMR — diversity comes from sub-queries)
- Merge results → frequency boost (+15% per extra sub-query hit) → top 7 chunks

### Ticket System
- Unanswerable queries → confirmation prompt → user confirms → Notion ticket created
- `TKT-XXXXXXXX` human-readable ticket ID
- Semantic deduplication: exact match first, then LLM semantic match to prevent duplicates
- Multiple pending questions → numbered selection menu
- Priority updatable from chat (High/Medium/Low) — status locked to Notion only
- Escape selection loop with: "no", "cancel", "never mind"

### Memory
- HybridMemory: Redis (60min TTL) + UI chat history merged per session
- New Chat = new UUID = fresh Redis session
- Messages >10: old messages compressed into summary

### Evaluation Lab
- Add 5–20 question + ground truth pairs (form or CSV paste with `|` separator)
- Runs full pipeline per pair with RAGAS scoring
- Metrics: Faithfulness, Answer Relevancy, Context Precision, Context Recall
- Progress bar per question, aggregate scores, per-question breakdown
- Downloadable PDF report via ReportLab

### Other Features
- Multilingual: responds in the same language the user writes in
- Word-by-word streaming for latest assistant message
- Refined query shown below user message (`🔍 Searched as:`)
- Copy button (toggles `st.code()` block with native copy)
- LangSmith tracing: every query traced end-to-end with token usage and latency

---

## API Reference

### CiteRAG Routes

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat` | Full LangGraph pipeline — main CiteRAG endpoint |
| `GET` | `/tickets` | Fetch all Notion tickets (optional `?status=` filter) |
| `POST` | `/tickets/create` | Manually create a ticket |
| `PATCH` | `/tickets/{id}` | Update ticket priority (High/Medium/Low only) |
| `POST` | `/evaluation/report` | Generate PDF evaluation report |

### DocForge Routes

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/departments/` | List all departments (Redis cached) |
| `GET` | `/templates/?dept_id=` | List templates by dept (Redis cached) |
| `POST` | `/sessions/` | Create session |
| `GET` | `/sessions/{id}/current_section` | Get current section |
| `POST` | `/sessions/{id}/generate_questions` | Generate AI questions |
| `POST` | `/sessions/{id}/submit_answers` | Save answers |
| `POST` | `/sessions/{id}/generate_section` | Write section with AI |
| `POST` | `/sessions/{id}/approve_section` | Approve/edit section |
| `GET` | `/sessions/{id}/sections` | Get all sections |
| `POST` | `/sessions/{id}/enhance_section` | AI-enhance a section |
| `POST` | `/sessions/{id}/compile` | Compile final document |
| `GET` | `/sessions/{id}/download_pdf` | Download as PDF |
| `POST` | `/sessions/{id}/publish_notion` | Publish to Notion |
| `GET` | `/notion/library` | Fetch all Notion-published docs |
| `GET` | `/cache/status` | Redis cache status |
| `DELETE` | `/cache/bust` | Clear all cache |

---

## MongoDB Collections

| Collection | Purpose |
|---|---|
| `Departments` | Department list |
| `document_templates` | Template definitions |
| `doc_sessions` | Active DocForge sessions |
| `doc_sections` | Section content per session |
| `session_questions` | Questions and answers |
| `generated_documents` | Compiled documents |
| `notion_publishes` | Publish history + version tracking |

---

## Notion Databases

| Database | ID | Purpose |
|---|---|---|
| Document Library | `31461ecb2bd28053910fe4d3ad65235b` | Published DocForge documents + CiteRAG source library |
| CiteRAG Tickets | `32d61ecb2bd28093a8f4d9273f854f87` | Support tickets raised by CiteRAG Lab |

---

## Architecture Decisions

**Why LangGraph for CiteRAG?**
Explicit state management and conditional routing. A simple chain always runs every step — LangGraph lets us skip retrieval for greetings, route to tickets when answers fail, and add nodes without rewriting the pipeline.

**Why no MMR in multi-query retrieval?**
MMR penalises chunks from the same document. For complex questions needing two chunks from the same document (e.g. candidate details + job title from an offer letter), MMR eliminates one. Diversity comes from different sub-queries instead.

**Why chat_history=None in evidence check?**
Previous wrong answers contaminate the preview answer used for judging. Generating without history ensures the grounding check is pure — based only on retrieved chunks.

**Why UI-level ticket interception?**
If "create ticket" reached the graph, the classifier would route it as `create_ticket` path and create a ticket about "create a ticket". The UI intercepts it, checks the pending queue, and sends the original unanswered question to the graph instead.

**Why direct Notion API (no Make.com)?**
Make.com had a 1000 op/month limit and added latency. Direct API is free, faster, returns the exact page URL, and handles all block types natively.

**Why Redis for departments/templates only (DocForge)?**
These never change during normal use. Session data (questions, sections, content) is user-specific and always fresh — caching it would cause stale data bugs.

**Why async endpoints for AI calls?**
Azure OpenAI takes 5–30s. `async def` + `await` lets FastAPI serve other requests concurrently. Sync + `run_until_complete()` crashed inside FastAPI's thread pool.

---

## Known Bugs Fixed

| Bug | Fix |
|---|---|
| `import streamlit` in `chat.py` | Removed — caused ScriptRunContext warning in FastAPI |
| Pydantic `extra_forbidden` for LangSmith env vars | Added `extra="ignore"` to Settings `SettingsConfigDict` |
| Refined query contaminated by `[1][2]` citations | Only user messages (not assistant) passed to refine context |
| evidence_check contaminated by wrong previous answers | `chat_history=None` in preview answer generation |
| "create ticket" creating ticket for wrong question | UI intercepts before API — uses pending queue |
| "done" triggering ticket status update | Ambiguous word blocklist in `_detect_ticket_update()` |
| Opening Statement chunk missing (Rohit Mehra query) | Multi-query + no-MMR + frequency boost |
| Ticket showing Notion UUID not TKT-XXXXXXXX | Added `ticket_title` field through state → route → UI |
| AsyncIO crash on AI generate (DocForge) | `async def` + `await` |
| PDF `UnicodeEncodeError` (DocForge) | `clean()` sanitizes content before rendering |
| PDF `Not enough horizontal space` (DocForge) | `safe_multicell()` with `textwrap.wrap` |

---

*FastAPI · Streamlit · LangGraph · Milvus · Azure OpenAI · MongoDB · Redis · RAGAS · LangSmith · Notion API · ReportLab · fpdf2*