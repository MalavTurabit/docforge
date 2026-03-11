# 📋 DocForge

**AI-powered document generation system** — create professional, context-aware business documents through a guided, section-by-section workflow. Powered by Azure OpenAI, built with FastAPI + Streamlit + MongoDB.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [Running the App](#running-the-app)
- [How It Works — User Flow](#how-it-works--user-flow)
- [Features](#features)
- [API Reference](#api-reference)
- [Key Files](#key-files)
- [Architecture Decisions](#architecture-decisions)
- [Known Bugs Fixed](#known-bugs-fixed)
- [Environment Variables](#environment-variables)
- [MongoDB Collections](#mongodb-collections)
- [LangChain Usage](#langchain-usage)
- [Development Notes](#development-notes)

---

## Overview

DocForge lets users generate complete, professional documents (offer letters, privacy policies, financial reports, compliance docs, etc.) in minutes. The system:

1. Asks the user to select a **department** and **document template**
2. Collects **company context** (name, product, industry, stage)
3. For each section, generates **smart contextual questions** using AI
4. Takes user answers and **writes each section** with AI
5. Lets users **review, edit, approve** each section
6. Compiles everything into a **final document** with PDF download and Notion publish
7. Allows post-generation **AI enhancement** of any section with one-click presets or custom prompts

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit (Python) |
| Backend API | FastAPI (Python) |
| AI / LLM | Azure OpenAI (GPT-4) via LangChain (`langchain-openai`, `langchain-core`) |
| Database | MongoDB |
| PDF Generation | fpdf2 |
| Notion Integration | Notion API (direct, no third-party bridge) |
| Package Manager | uv |

---

## Project Structure

```
docforge/
├── app/
│   ├── main.py                  # FastAPI entry point + global exception handlers
│   ├── config.py                # Pydantic settings — loads all env vars
│   ├── db.py                    # MongoDB connection helper
│   ├── routes/
│   │   ├── sessions.py          # All session/document endpoints + Notion + PDF
│   │   ├── departments.py       # GET /departments/
│   │   └── templates.py         # GET /templates/?dept_id=
│   └── services/
│       ├── llm_provider.py      # AzureChatOpenAI wrapper (LangChain)
│       ├── question_service.py  # AI question generation
│       └── section_service.py   # AI section writing + enhancement
├── docforge_app.py              # Streamlit frontend (entire UI)
├── pyproject.toml               # Dependencies
├── .env                         # Secrets — never commit this
├── .gitignore                   # Includes .env
└── README.md
```

---

## Setup & Installation

### Prerequisites

- Python 3.12+
- MongoDB running locally (default: `mongodb://localhost:27017`)
- Azure OpenAI API access (endpoint + key + deployment name)
- Notion internal integration key
- `uv` package manager

### 1. Clone and install dependencies

```bash
git clone https://github.com/MalavTurabit/docforge.git
cd docforge
uv sync
```

### 2. Create `.env` file

```env
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01

# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=docforge

# Notion
NOTION_API_KEY=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_DATABASE_ID=31461ecb2bd28053910fe4d3ad65235b
```

> ⚠️ Never commit `.env` to git. It is listed in `.gitignore`.

### 3. Seed document templates

Make sure your MongoDB `docforge` database has templates in the `document_templates` collection:

```json
{
  "_id": "tpl_offer_letter",
  "dept_id": "dept_hr",
  "label": "Employment Offer Letter",
  "template_json": {
    "sections": [
      {
        "id": "candidate_details",
        "title": "Candidate Details",
        "description": "Personal and role information for the candidate"
      }
    ],
    "generation_rules": { "tone": "professional", "format": "formal" },
    "terminology_rules": {}
  }
}
```

---

## Running the App

Run both commands from inside the `docforge/` directory.

### Terminal 1 — FastAPI backend

```bash
cd docforge
uv run uvicorn app.main:app --reload
```

API: `http://localhost:8000`
Docs: `http://localhost:8000/docs`

### Terminal 2 — Streamlit frontend

```bash
cd docforge
uv run streamlit run app/docforge_app.py --server.port 8501
```

App: `http://localhost:8501`

---

## How It Works — User Flow

```
Select Department → Select Template → Company Info → Generate Sections → Compile → Download / Publish
```

### Step 1 — Select Department
Choose from HR, Finance, Product Management, Engineering, QA, Legal & Compliance, Sales & Marketing, Business Ops, IT & Security, Support.

### Step 2 — Select Template
Templates are filtered by department. Each defines the document structure (sections, generation rules, terminology).

### Step 3 — Company Info
Fill in 6 fields: company name, product name + description, industry vertical, company stage, target customer, key problem solved. This context is injected into every AI call.

### Step 4 — Generate Sections (one by one)
For each section:
1. AI generates 2–5 contextual questions specific to the section and document type
2. User answers the questions
3. AI writes the section using answers + company context + template rules
4. User can **Edit** or **Approve** — approved sections appear in the live preview panel

### Step 5 — Compile & Download
Once all sections are approved:
- **Compile Document** — merges all sections into the final document
- **Download PDF** — professionally formatted with title page, running header, markdown tables, bullet points
- **Publish to Notion** — one-click, no configuration needed

### Step 6 — Enhance Sections
After compilation, the **✨ Enhance a Section** panel lets you:
- Pick any section from a dropdown
- Choose a quick preset (Make longer, More formal, Add table, Add examples, etc.)
- Or type a custom instruction
- Review original vs enhanced side-by-side
- Accept (triggers re-compile) or Discard

### Step 7 — Library
All compiled documents are saved in the sidebar **Library**. Click any to open it and re-download PDF or re-publish to Notion.

---

## Features

### Document Generation
- Section-by-section guided workflow
- AI questions are document-type aware — never asks for info already provided in company context
- Questions capped at 2–3 for simple sections, max 5 for complex ones
- Full company context injected into every generation call
- Live document preview updates as sections are approved

### PDF Generation
- Professional PDF with document title as large heading on page 1
- Running header on every page: `DocForge | Document Title`
- Full markdown support: H1/H2/H3, bullet lists, numbered lists, tables, horizontal rules
- Unicode-safe: rupee `₹`, curly quotes, em dashes, bullets all handled
- `safe_multicell()` prevents FPDF crash on long unbroken words
- Filename uses the document title (e.g. `Employment_Offer_Letter.pdf`)

### Notion Integration
- **Direct Notion API** — no third-party bridge (Make.com removed)
- Each section becomes a **Heading 2 + paragraph blocks** in Notion
- Markdown tables → proper Notion `table` blocks with headers
- Bullet lines → `bulleted_list_item` blocks
- Numbered lists → `numbered_list_item` blocks
- Bold `**text**` → Notion bold annotations
- **Rate limiting**: 0.4s sleep between API calls (~2.5 req/s, under the 3 req/s cap)
- **Batching**: 95 blocks per request (Notion hard limit is 100)
- **Retry logic**: exponential backoff up to 5× on 429 Too Many Requests
- **2000 char limit**: text chunked at 1950 chars on word boundaries
- **Version tracking**: `v1`, `v2`... auto-incremented per session in MongoDB
- After publish — shows **"Open in Notion →"** direct link to the exact page created
- Database fields populated: Name, industry, version, tags

### AI Enhancement
- Any approved section can be re-enhanced post-generation
- 8 quick presets: Make longer, More formal, Make concise, Add bullets, Add table, Add examples, More specific, Industry language
- Free-form custom prompt also supported
- Side-by-side original vs enhanced diff before committing
- Accepting clears compiled content → forces re-compile

### Sidebar Library
- All compiled documents listed under **Library** section
- Real `st.button` widgets styled as doc tiles — no hidden button hacks
- Each tile shows doc title + department + date
- Click → opens document view with Download PDF + Publish to Notion

### Exception Handling
- `main.py` has three global handlers:
  - **422** `RequestValidationError` — shows exactly which field failed
  - **HTTP errors** — clean JSON with status + detail
  - **Unhandled exceptions** — returns error type + message + last 5 lines of traceback

---

## API Reference

### Departments — `GET /departments/`

```http
GET /departments/
```
```json
[
  { "dept_id": "dept_hr",      "dept_name": "Human Resources" },
  { "dept_id": "dept_finance", "dept_name": "Finance" }
]
```

### Templates — `GET /templates/?dept_id=`

```http
GET /templates/?dept_id=dept_hr
```
```json
[
  { "id": "tpl_offer_letter", "label": "Employment Offer Letter" }
]
```

### Sessions — `/sessions/`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/sessions/` | Create a new document session |
| `GET` | `/sessions/{session_id}/current_section` | Get the current section to fill |
| `POST` | `/sessions/{session_id}/generate_questions` | Generate AI questions for a section |
| `POST` | `/sessions/{session_id}/submit_answers` | Save user answers for a section |
| `POST` | `/sessions/{session_id}/generate_section` | Write section content with AI |
| `POST` | `/sessions/{session_id}/approve_section` | Approve (or save edited) section |
| `GET` | `/sessions/{session_id}/sections` | Get all section contents for a session |
| `POST` | `/sessions/{session_id}/enhance_section` | AI-enhance a section with a custom prompt |
| `POST` | `/sessions/{session_id}/compile` | Compile all approved sections into final doc |
| `GET` | `/sessions/{session_id}/download_pdf` | Download compiled doc as PDF |
| `POST` | `/sessions/{session_id}/publish_notion` | Publish compiled doc to Notion |

### Publish to Notion — Request/Response

```http
POST /sessions/sess_a1b2c3d4/publish_notion
Content-Type: application/json

{ "doc_title": "Employment Offer Letter" }
```
```json
{
  "message":    "Published to Notion successfully",
  "doc_title":  "Employment Offer Letter",
  "version":    "v1",
  "industry":   "Human Resources",
  "tags":       "Employment Offer Letter",
  "notion_url": "https://www.notion.so/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

---

## Key Files

### `app/main.py`
FastAPI entry point. Registers all routers. Three global exception handlers: `RequestValidationError`, `StarletteHTTPException`, `Exception`.

### `app/routes/sessions.py`
All document session logic. Contains:
- All 11 API endpoints
- **Notion helpers**: `_notion_request()`, `_chunk_text()`, `_make_rich_text()`, `_parse_table()`, `_content_to_blocks()`, `_append_blocks()`
- **PDF helpers**: `DocForgePDF`, `clean()`, `safe_multicell()`, `render_markdown_to_pdf()`
- Rate limiting, retry backoff, block batching for Notion API

### `app/routes/departments.py`
`GET /departments/` — reads from `Departments` MongoDB collection.

### `app/routes/templates.py`
`GET /templates/?dept_id=` — filters `document_templates` by department.

### `app/services/llm_provider.py`
Thin LangChain wrapper around `AzureChatOpenAI`. Uses `ainvoke()` for async calls. LangChain is used **only as an Azure OpenAI client** — no chains, no agents, no memory.

### `app/services/question_service.py`
`generate_questions()` — generates 2–5 contextual questions per section. Prompt explicitly lists known company info and instructs AI not to ask about it again.

### `app/services/section_service.py`
- `generate_section()` — writes section content from Q&A + company context
- `enhance_section()` — rewrites section per user instruction

### `app/docforge_app.py`
Full Streamlit frontend (~1000 lines). Key functions:
- `render_sidebar()` — dark navy sidebar, Library with real buttons, API status pill
- `page_home()` — department + template selection tiles
- `page_context()` — company info form
- `page_generating()` — section-by-section generation flow
- `_questions_form()` — renders AI questions as a Streamlit form
- `_approve_panel()` — approve/edit generated section
- `_done_left()` — compile, download, publish, enhance panel
- `_enhance_panel()` — 8 presets + custom prompt + side-by-side diff
- `_preview_panel()` — live sticky preview (single HTML string)
- `page_view_doc()` — view/download/publish any Library document

---

## Architecture Decisions

### Why single HTML string for preview?
Streamlit wraps each `st.markdown()` in its own `<div>`. Splitting open/close HTML tags across two calls causes the closing tag to render as a visible element. Everything is built as one string in a single `st.markdown()` call.

### Why real `st.button` for Library tiles instead of hidden buttons?
Hidden buttons (zero-width space label + `display:none` CSS) always leaked a visible white box in the sidebar. Replaced with real `st.button` widgets styled to look like doc tiles — zero leaking, fully clickable.

### Why not use LangChain chains?
DocForge's AI flow is single prompt → single response for every operation. Chains are useful for RAG, agents, or multi-step LLM pipelines — none of which we need. All sequencing and context injection is done manually in Python. LangChain is used only for the `AzureChatOpenAI` async client.

### Why direct Notion API instead of Make.com?
Make.com free plan has 1000 operations/month and adds latency. Direct Notion API is faster, free, handles all block types natively, and gives us the exact page URL back. The 3 req/s rate limit is handled with 0.4s sleeps + exponential backoff.

### Why `clean()` runs on entire document before PDF rendering?
FPDF with Helvetica (latin-1) crashes on any character outside latin-1 range. Running `clean()` upfront on the full content string is a safety net — `encode("latin-1", errors="ignore")` drops anything that slips through.

### Why `safe_multicell()` wraps text?
FPDF raises `FPDFException: Not enough horizontal space` when a word exceeds column width. `textwrap.wrap(break_long_words=True)` pre-wraps so no word hits FPDF raw.

### Why async endpoints for AI calls?
Azure OpenAI calls are I/O-bound and take 5–30 seconds. `async def` + `await` lets FastAPI serve other requests concurrently. Sync endpoints with `run_until_complete()` crashed inside FastAPI's thread pool.

---

## Known Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| AsyncIO crash on generate | `run_until_complete()` inside FastAPI thread pool | Changed to `async def` + `await` |
| Dict mutation on template | `generation_rules = template_json.get(...)` returned reference | Used `dict(...)` copy |
| PDF crash — not enough horizontal space | Long unbroken words exceeded FPDF column width | `safe_multicell()` with `textwrap.wrap(break_long_words=True)` |
| PDF crash — `UnicodeEncodeError: '\u2022'` | Bullet `•` outside latin-1 range | `clean()` on full content before rendering |
| PDF `output()` wrote nothing | `fpdf2` `output()` returns bytes, not writes to file | `pdf_bytes = pdf.output()` then `BytesIO(pdf_bytes)` |
| Preview renders outside container | Split open/close HTML divs across two `st.markdown()` calls | Single `st.markdown()` call with full HTML string |
| `open_sess_xxx` text in sidebar | Hidden buttons used session ID as visible label | Replaced with real styled `st.button` widgets |
| Blank container below API pill | Hidden `\u200b` button leaked white box despite CSS | Removed hidden buttons entirely |
| Extra container above enhance panel | Orphaned `st.markdown('</div>')` rendered as element | Merged into single `st.markdown()` call |
| Template None check crash | `template["sections"]` accessed without None guard | Added `if not template: raise HTTPException(404)` |
| Q&A None AttributeError | `qa_doc.get(...)` on None object | Added `if qa_doc` guard |
| `notion_database_id` validation error | `PublishRequest` had it as required field | Removed field — hardcoded in config |
| GitHub push blocked | Notion API key hardcoded in `sessions.py` | Moved to `.env` + `config.py` via pydantic-settings |

---

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint | `https://myresource.openai.azure.com/` |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | `abc123...` |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name in Azure | `gpt-4o` |
| `AZURE_OPENAI_API_VERSION` | API version | `2024-02-01` |
| `MONGODB_URI` | MongoDB connection string | `mongodb://localhost:27017` |
| `MONGODB_DB` | Database name | `docforge` |
| `NOTION_API_KEY` | Notion internal integration secret | `secret_xxx...` |
| `NOTION_DATABASE_ID` | Notion liberary database ID | `31461ecb2bd28053910fe4d3ad65235b` |

---

## MongoDB Collections

| Collection | Purpose |
|---|---|
| `Departments` | Department list (dept_id, name) |
| `document_templates` | Template definitions (sections, generation rules, terminology) |
| `doc_sessions` | Active document sessions (current section index, status) |
| `doc_sections` | Section content per session (content, status: generated/approved) |
| `session_questions` | AI-generated questions and user answers per session |
| `generated_documents` | Compiled final documents with title and full content |
| `notion_publishes` | Publish history — session_id, version, notion_page_id, notion_url |

---

## LangChain Usage

LangChain is used **only in `llm_provider.py`** as a thin client wrapper:

```python
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage

self.llm = AzureChatOpenAI(...)
response = await self.llm.ainvoke([HumanMessage(content=prompt)])
```

**Not used**: chains, agents, memory, RAG, tools, callbacks, or any other LangChain feature. All prompt construction, context injection, and sequencing is done manually in Python.

---

## Development Notes

- Run both `uvicorn` and `streamlit` from inside the `docforge/` directory
- API timeout is **90 seconds** to handle slow LLM responses
- The preview panel is sticky (`position: sticky; top: 1rem`)
- PDF filenames replace non-alphanumeric chars with `_`
- Accepting an enhancement clears `compiled_content` in session state — user must re-compile
- `upsert_preview()` updates sections in-place to avoid duplicates in the preview list
- Notion `notion_publishes` collection tracks publish count per session for version numbers
- Secrets must never be hardcoded — GitHub push protection will block the push

---

*Built with FastAPI · Streamlit · MongoDB · Azure OpenAI · LangChain · fpdf2 · Notion API*