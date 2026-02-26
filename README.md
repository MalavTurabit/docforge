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
| AI / LLM | Azure OpenAI (GPT-4.1mini) via OpenAI SDK |
| Database | MongoDB |
| PDF Generation | fpdf2 |
| Notion Integration | Notion API |
| Package Manager | uv / pip |

---

## Project Structure

```
docforge/
├── app/
│   ├── main.py                  # FastAPI app entry point
│   ├── db.py                    # MongoDB connection helper
│   ├── routes/
│   │   ├── sessions.py          # All session/document API endpoints
│   │   ├── departments.py       # GET /departments/ — list all departments from MongoDB
│   │   └── templates.py         # GET /templates/?dept_id= — list templates by department
│   └── services/
│       ├── llm_provider.py      # Azure OpenAI LLM wrapper
│       ├── question_service.py  # AI question generation
│       └── section_service.py   # AI section writing + enhancement
├── docforge_app.py              # Streamlit frontend (entire UI)
├── pyproject.toml               # Dependencies
└── README.md
```

---

## Setup & Installation

### Prerequisites

- Python 3.12+
- MongoDB running locally (default: `mongodb://localhost:27017`)
- Azure OpenAI API access (endpoint + key + deployment name)
- `uv` package manager (recommended) or `pip`

### 1. Clone and install dependencies

```bash
git clone <your-repo-url>
cd docforge

# Using uv (recommended)
uv sync

# Or using pip with venv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Set environment variables

Create a `.env` file in the project root:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_DEPLOYMENT=gpt-4.1mini          # your deployment name
AZURE_OPENAI_API_VERSION=2024-02-01
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=docforge
```

### 3. Seed document templates

Make sure your MongoDB `docforge` database has templates seeded in the `document_templates` collection. Each template follows this structure:

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
    "generation_rules": {
      "tone": "professional",
      "format": "formal"
    },
    "terminology_rules": {}
  }
}
```

---

## Running the App

You need **two terminals** — one for the API, one for the UI.

### Terminal 1 — Start the FastAPI backend

```bash
# Using uv
uv run uvicorn app.main:app --reload --port 8000

# Or with activated venv
uvicorn app.main:app --reload --port 8000
```

API will be available at: `http://localhost:8000`
Interactive API docs: `http://localhost:8000/docs`

### Terminal 2 — Start the Streamlit frontend

```bash
# Using uv
uv run streamlit run docforge_app.py --server.port 8501

# Or with activated venv
streamlit run docforge_app.py --server.port 8501
```

App will be available at: `http://localhost:8501`

---

## How It Works — User Flow

```
Select Department → Select Template → Company Info → Generate Sections → Compile → Download
```

### Step 1 — Select Department
Choose from HR, Finance, Product Management, Engineering, QA, Legal & Compliance, Sales & Marketing, Business Ops, IT & Security, Support.

### Step 2 — Select Template
Templates are filtered by department. Each template defines the document structure (sections, generation rules, terminology).

### Step 3 — Company Info
Fill in 7 fields:
- Company name
- Product name + description
- Industry vertical
- Company stage (seed / series A / growth / etc.)
- Target customer
- Key problem solved

This context is passed to the AI for every section so content is accurate and company-specific.

### Step 4 — Generate Sections (one by one)

For each section:
1. AI generates **2–5 contextual questions** (not generic — specific to the document type and section)
2. User answers the questions
3. AI writes the section using answers + company context + template rules
4. User can **Edit** or **Approve** the section
5. Approved sections appear in the **live preview panel** on the right

### Step 5 — Compile & Download

Once all sections are approved:
- Click **Compile Document** to merge all sections
- **Download PDF** — professionally formatted with title, header on each page, markdown tables, bullet points
- **Publish to Notion** — push the document to a Notion database

### Step 6 — Enhance Sections (post-generation)

After compilation, use the **✨ Enhance a Section** panel to:
- Select any section from a dropdown
- Choose a quick preset:
  - ✦ Make it longer
  - ⚡ More formal
  - ✂ Make it concise
  - 📋 Add bullet points
  - 📊 Add a table
  - 💡 Add examples
  - 🔍 More specific
  - 🌐 Industry language
- Or write a **custom instruction** (e.g. *"Add a risk mitigation table and use executive tone"*)
- Review **side-by-side** original vs enhanced
- **Accept & Save** (updates the section, requires re-compile) or **Discard**

---

## Features

### Document Generation
- Section-by-section guided workflow
- AI questions are document-type aware (no irrelevant product/company questions asked)
- Questions capped at 2–3 per simple section, max 5 for complex ones
- Full company context injected into every generation call
- Live document preview updates as sections are approved

### Document Preview
- Sticky right-panel preview showing all approved sections in real time
- Document title shown at top of preview
- Markdown rendering: bold, tables, bullet lists
- Approved (green) vs generated (amber) status chips per section

### PDF Generation
- Professional PDF with document title as large heading on page 1
- Running header on every page: `DocForge | Document Title`
- Handles markdown: headings (H1/H2/H3), bullet lists, numbered lists, tables, horizontal rules
- Unicode-safe: rupee sign, curly quotes, em dashes, bullets all handled cleanly
- `safe_multicell()` prevents FPDF "not enough horizontal space" crash on long words
- Filename uses the document title (e.g. `Employment Offer Letter.pdf`)

### AI Enhancement
- Any approved section can be re-enhanced post-generation
- Enhancement agent receives: section metadata, current content, company context, generation rules, user instruction
- Side-by-side original vs enhanced diff before committing
- Accepting an enhancement clears the compiled document (forces re-compile to include new content)

### Notion Integration
- Publish compiled document to any Notion database
- Document title passed as the Notion page title

### Sidebar
- Dark navy sidebar with DocForge branding
- Progress tracker (Department → Template → Company Info → Generate) with live done/active states
- Generated Docs history — click any to view
- In Progress docs list
- API connection status pill

---

## API Reference

### Departments — `/departments/`

Returns all departments from the `Departments` MongoDB collection.

```http
GET /departments/
```
```json
[
  { "dept_id": "dept_hr",      "dept_name": "Human Resources" },
  { "dept_id": "dept_finance", "dept_name": "Finance" }
]
```

---

### Templates — `/templates/`

Returns all document templates filtered by department.

```http
GET /templates/?dept_id=dept_hr
```
```json
[
  { "id": "tpl_offer_letter", "label": "Employment Offer Letter" },
  { "id": "tpl_appraisal",    "label": "Performance Appraisal" }
]
```

---

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
| `GET` | `/sessions/{session_id}/download_pdf` | Download the compiled doc as PDF |
| `POST` | `/sessions/{session_id}/publish_notion` | Publish compiled doc to Notion |

### Request/Response Examples

#### Create Session
```http
POST /sessions/
Content-Type: application/json

{ "template_id": "tpl_offer_letter" }
```
```json
{ "session_id": "sess_a1b2c3d4", "total_sections": 6 }
```

#### Generate Questions
```http
POST /sessions/sess_a1b2c3d4/generate_questions
Content-Type: application/json

{
  "section_id": "candidate_details",
  "company_context": {
    "company_name": "Treespay",
    "product_name": "TreesPay",
    "industry_vertical": "Fintech"
  }
}
```
```json
{
  "questions": [
    { "question_id": "q1", "question_text": "What is the candidate's full name?" },
    { "question_id": "q2", "question_text": "What role are they being offered?" }
  ]
}
```

#### Enhance Section
```http
POST /sessions/sess_a1b2c3d4/enhance_section
Content-Type: application/json

{
  "section_id": "candidate_details",
  "enhance_prompt": "Make this section more formal and add a responsibilities table",
  "company_context": { "company_name": "Treespay" }
}
```
```json
{
  "section_id": "candidate_details",
  "section_title": "Candidate Details",
  "original": "...original content...",
  "enhanced": "...AI enhanced content..."
}
```

#### Compile Document
```http
POST /sessions/sess_a1b2c3d4/compile
Content-Type: application/json

{ "doc_title": "Employment Offer Letter" }
```
```json
{
  "message": "Document compiled",
  "document_id": "doc_e5f6g7h8",
  "doc_title": "Employment Offer Letter"
}
```

---

## Key Files

### `app/routes/sessions.py`
All document session logic. Contains:
- All 11 API endpoints
- `DocForgePDF` class — fpdf2 subclass with custom header
- `clean()` — unicode sanitizer (handles •, ₹, —, curly quotes, etc.)
- `safe_multicell()` — crash-proof text renderer for FPDF
- `render_markdown_to_pdf()` — full markdown-to-PDF converter

### `app/services/question_service.py`
- `generate_questions(section_json, company_context)` — generates 2–5 contextual questions
- Prompt explicitly lists all known company info and instructs the AI NOT to ask about those
- Uses section title to determine appropriate question type

### `app/services/section_service.py`
- `generate_section(section_json, qa_pairs, generation_rules, terminology_rules)` — writes section content
- `enhance_section(section_json, current_content, enhance_prompt, company_context, generation_rules)` — rewrites section per user instruction

### `docforge_app.py`
Full Streamlit frontend (~950 lines). Key functions:
- `render_sidebar()` — dark navy sidebar with progress + history
- `page_home()` — department + template selection
- `page_context()` — company info form
- `page_generating()` — section-by-section generation flow
- `_questions_form()` — renders AI questions as a form
- `_approve_panel()` — approve/edit generated section
- `_done_left()` — compile, download, publish panel
- `_enhance_panel()` — full AI enhancement UI with presets + custom prompt + diff
- `_preview_panel()` — live document preview (single HTML string for correct rendering)
- `render_markdown()` — converts markdown to HTML for preview
- `page_view_doc()` — view previously generated document

---

## Architecture Decisions

### Why single HTML string for preview?
Streamlit wraps each `st.markdown()` call in its own `<div>`. If you split a container's open and close tags across two `st.markdown()` calls, the closing tag renders as a separate visible element. The entire preview is built as one Python string and rendered in a single `st.markdown()` call.

### Why CSS `order` for sidebar button positioning?
Streamlit renders widgets (buttons) before HTML in the same block — you cannot reorder them with Python code. CSS `flex order` property is used to visually place the DocForge brand title (order:1) above the New Document button (order:2), even though the button is technically rendered first in the DOM.

### Why `clean()` runs on the entire document before PDF rendering?
FPDF with Helvetica (latin-1 encoding) crashes on any character outside the latin-1 range. Running `clean()` on the full content string upfront (before line-by-line processing) is a safety net — even if a single character slips through the replacement map, the `encode("latin-1", errors="ignore")` fallback will drop it silently rather than crashing.

### Why `safe_multicell()` wraps text before `multi_cell()`?
FPDF raises `FPDFException: Not enough horizontal space to render a single character` when a word is longer than the available column width (e.g. long URLs, camelCase identifiers). `textwrap.wrap(break_long_words=True)` pre-wraps the text so no word exceeds the column width before it reaches FPDF.

### Why async endpoints for question/section generation?
Azure OpenAI calls are I/O-bound and can take 5–30 seconds. FastAPI's `async def` endpoints run on the event loop without blocking the thread pool, allowing other requests to be served concurrently. Earlier sync endpoints were crashing with `asyncio.get_event_loop().run_until_complete()` inside FastAPI's thread pool — converting to `async def` + `await` fixed this.

---

## Known Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| AsyncIO crash on generate | `run_until_complete()` called inside FastAPI thread pool | Changed endpoints to `async def`, used `await` directly |
| Dict mutation on template | `generation_rules = template_json.get(...)` returned reference, mutations persisted | Used `dict(...)` copy before modifying |
| PDF crash — `Not enough horizontal space` | Long unbroken words exceeded FPDF column width | Added `safe_multicell()` with `textwrap.wrap(break_long_words=True)` |
| PDF crash — `UnicodeEncodeError: '\u2022'` | Bullet `•` passed to Helvetica font which is latin-1 only | Added `clean()` to sanitize entire content before rendering; replaced `•` with `-` |
| PDF `output()` wrote nothing | `fpdf2` `output()` returns bytes — old code passed a `BytesIO` as argument | `pdf_bytes = pdf.output()` then `BytesIO(pdf_bytes)` |
| Preview content renders outside container | Multiple `st.markdown()` calls split open/close HTML divs | Built entire preview as one HTML string in a single `st.markdown()` call |
| Sidebar button order wrong | Streamlit renders widgets before HTML regardless of call order | Used CSS `flex order` property to visually reorder elements |
| `open_sess_xxx` text in sidebar | Hidden buttons used session ID as label text | Used zero-width space `\u200b` as label + `display: none` CSS |
| Extra container above enhance panel | Orphaned `st.markdown('</div>')` rendered as visible Streamlit element | Merged all enhance header HTML into single `st.markdown()` call |
| Template None check crash | `approve_section` accessed `template["sections"]` without None guard | Added `if not template: raise HTTPException(404)` |
| Q&A None AttributeError | `qa_doc.get(...)` called when `qa_doc` was None | Added `if qa_doc` guard before all attribute access |

---

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint | `https://myresource.openai.azure.com/` |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | `abc123...` |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name in Azure | `gpt-4.1mini` |
| `AZURE_OPENAI_API_VERSION` | API version | `2024-02-01` |
| `MONGODB_URI` | MongoDB connection string | `mongodb://localhost:27017` |
| `MONGODB_DB` | Database name | `docforge` |

---

## MongoDB Collections

| Collection | Purpose |
|---|---|
| `depertments` | List of all defined Departments |
| `document_templates` | Template definitions (sections, generation rules, terminology) |
| `doc_sessions` | Active document sessions (current section index, status) |
| `doc_sections` | Section content per session (content, status: generated/approved) |
| `session_questions` | AI-generated questions and user answers per session |
| `generated_documents` | Compiled final documents with title and full content |

---

## Contributing / Development Notes

- The frontend (`docforge_app.py`) runs entirely stateless per page refresh — all state lives in `st.session_state`
- API timeout is set to **90 seconds** to handle slow LLM responses
- The preview panel is **sticky** (`position: sticky; top: 1rem`) so it stays visible while scrolling through the left panel
- PDF filenames use the document title with non-alphanumeric characters replaced by `_`
- Enhancement accepting a section clears `compiled_content` in session state to force re-compilation with the new content
- The `upsert_preview()` helper updates an existing section in the preview list in-place to avoid duplicates

---

*Built with FastAPI · Streamlit · MongoDB · Azure OpenAI · fpdf2*