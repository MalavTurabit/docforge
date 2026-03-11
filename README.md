# 📋 DocForge

**AI-powered document generation system** — create professional, context-aware business documents through a guided, section-by-section workflow. Powered by Azure OpenAI, built with FastAPI + Streamlit + MongoDB + Redis.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit |
| Backend API | FastAPI |
| AI / LLM | Azure OpenAI via LangChain (`langchain-openai`, `langchain-core`) |
| Database | MongoDB |
| Cache | Redis |
| PDF Generation | fpdf2 |
| Notion Integration | Notion API (direct) |
| Package Manager | uv |

---

## Project Structure

```
docforge/
├── app/
│   ├── main.py                    # FastAPI entry + global exception handlers
│   ├── config.py                  # Pydantic settings — loads all env vars
│   ├── db.py                      # MongoDB connection
│   ├── redis_client.py            # Redis singleton + CACHE_TTL
│   ├── routes/
│   │   ├── sessions.py            # All session endpoints + PDF + Notion publish
│   │   ├── departments.py         # GET /departments/ — Redis cached
│   │   ├── templates.py           # GET /templates/?dept_id= — Redis cached
│   │   ├── notion_library.py      # GET /notion/library — fetch all Notion docs
│   │   └── cache_routes.py        # DELETE /cache/bust, GET /cache/status
│   └── services/
│       ├── llm_provider.py        # AzureChatOpenAI async wrapper
│       ├── question_service.py    # AI question generation
│       └── section_service.py     # AI section writing + enhancement
├── app/docforge_app.py            # Streamlit frontend (~1100 lines)
├── pyproject.toml
├── .env                           # Secrets — never commit
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
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01

# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=docforge

# Redis
REDIS_URL=redis://localhost:6379/0

# Notion
NOTION_API_KEY=secret_xxx
NOTION_DATABASE_ID=31461ecb2bd28053910fe4d3ad65235b
```

### 4. Add to `config.py` Settings class
```python
notion_api_key:     str = ""
notion_database_id: str = ""
redis_url:          str = "redis://localhost:6379/0"
```

---

## Running

Both commands from inside `docforge/`:

```bash
# Terminal 1 — API
uv run uvicorn app.main:app --reload

# Terminal 2 — UI
uv run streamlit run app/docforge_app.py --server.port 8501
```

- API: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`
- App: `http://localhost:8501`

---

## User Flow

```
Select Department → Select Template → Company Info → Generate Sections → Compile → Download / Publish
```

1. **Department** — choose from 10 departments
2. **Template** — filtered by department
3. **Company Info** — 6 fields injected into every AI call
4. **Generate** — section by section: AI asks questions → user answers → AI writes → user approves
5. **Compile** → Download PDF or Publish to Notion
6. **Enhance** — re-enhance any section post-generation with presets or custom prompt
7. **Library** — view all Notion-published docs, resume in-progress docs from sidebar

---

## Features

### Document Generation
- Section-by-section guided workflow
- AI questions are document-type aware — never re-asks info already in company context
- Live document preview updates as sections are approved

### PDF
- Title page + running header on every page
- Full markdown: H1/H2/H3, bullets, numbered lists, tables, horizontal rules
- Unicode-safe (`₹`, `—`, curly quotes, bullets)
- Crash-proof: `safe_multicell()` handles long unbroken words

### Notion Publish
- Direct Notion API — no third-party bridge
- Sections → Heading 2 + paragraph blocks
- Markdown tables → Notion `table` blocks
- Bullets → `bulleted_list_item`, numbered → `numbered_list_item`, bold → annotations
- Rate limiting: 0.4s between calls, 95 blocks/request, 5× exponential backoff on 429
- Text chunked at 1950 chars (Notion 2000 char limit)
- Auto version tracking: `v1`, `v2`... per session
- Returns direct page URL → "Open in Notion →" link

### Notion Library Page
- `📚 Notion Library` button in sidebar
- Fetches all published docs directly from Notion database
- Shows title, version, department, tags, date, direct Notion link
- Sorted newest first, 50 docs per page

### Redis Caching
- Departments and templates cached for 1 hour
- Cache keys: `docforge:depts`, `docforge:templates:{dept_id}`
- Graceful fallback to MongoDB if Redis is down
- `GET /cache/status` — see what's cached
- `DELETE /cache/bust` — clear all cache (call after adding new templates)
- Logs show `cache hit` vs `cache miss` in uvicorn terminal

### AI Enhancement
- 8 quick presets: Make longer, More formal, Make concise, Add bullets, Add table, Add examples, More specific, Industry language
- Custom prompt also supported
- Side-by-side original vs enhanced diff before accepting
- Accepting clears compiled content → forces re-compile

### Sidebar
- In Progress docs — click to resume exactly where you left off
- Library — compiled docs, click to view/download/publish
- `+ New Document` and `📚 Notion Library` buttons always visible

### Exception Handling (`main.py`)
- 422 → shows exactly which field failed + hint
- HTTP errors → clean JSON with status + detail
- Unhandled → error type + message + last 5 lines of traceback

---

## API Reference

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
| `doc_sessions` | Active sessions |
| `doc_sections` | Section content per session |
| `session_questions` | Questions and answers |
| `generated_documents` | Compiled documents |
| `notion_publishes` | Publish history + version tracking |

---

## Environment Variables

| Variable | Description |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI key |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name |
| `AZURE_OPENAI_API_VERSION` | API version |
| `MONGODB_URI` | MongoDB connection string |
| `MONGODB_DB` | Database name |
| `REDIS_URL` | Redis URL |
| `NOTION_API_KEY` | Notion internal integration secret |
| `NOTION_DATABASE_ID` | Notion database ID |

---

## Architecture Decisions

**Why not LangChain chains?** All AI calls are single prompt → single response. LangChain is used only as an async Azure OpenAI client — no chains, agents, or memory needed.

**Why direct Notion API?** Make.com had 1000 op/month limit and added latency. Direct API is free, faster, returns exact page URL, and handles all block types natively.

**Why Redis for departments/templates only?** These never change during normal use. Session data (questions, sections, content) is user-specific and always fresh — caching it would cause stale data bugs.

**Why single HTML string for preview?** Streamlit wraps each `st.markdown()` in its own div — splitting HTML open/close tags across two calls causes the closing tag to render as a visible element.

**Why `safe_multicell()` in PDF?** FPDF crashes on words longer than column width. `textwrap.wrap(break_long_words=True)` pre-wraps before FPDF sees it.

**Why async endpoints for AI calls?** Azure OpenAI takes 5–30s. `async def` + `await` lets FastAPI serve other requests concurrently. Sync + `run_until_complete()` crashed inside FastAPI's thread pool.

---

## Known Bugs Fixed

| Bug | Fix |
|---|---|
| AsyncIO crash on generate | `async def` + `await` |
| PDF `UnicodeEncodeError` | `clean()` sanitizes full content before rendering |
| PDF `Not enough horizontal space` | `safe_multicell()` with `textwrap.wrap` |
| PDF `output()` wrote nothing | `pdf.output()` returns bytes — wrap in `BytesIO` |
| Preview renders outside container | Single `st.markdown()` call with full HTML string |
| Sidebar hidden buttons leaking | Replaced with real `st.button` widgets |
| In Progress docs not resuming | `need_fetch=True` + full state restore on click |
| `notion_database_id` validation error | Removed from `PublishRequest` — read from config |
| GitHub push blocked | Moved secrets to `.env` + removed from git history |
| Template None crash | `if not template: raise HTTPException(404)` |

---

*FastAPI · Streamlit · MongoDB · Redis · Azure OpenAI · LangChain · fpdf2 · Notion API*