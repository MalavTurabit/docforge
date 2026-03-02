from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid
import textwrap
import time
import re
import requests as http_requests
from fastapi.responses import StreamingResponse
from io import BytesIO
from fpdf import FPDF
from app.db import get_db
from app.services.question_service import QuestionService
from app.services.section_service import SectionService
from app.config import settings
# ─── Notion API config ────────────────────────────────────────
NOTION_API_KEY     = settings.notion_api_key
NOTION_DATABASE_ID = settings.notion_database_id
NOTION_VERSION      = "2022-06-28"
NOTION_BASE_URL     = "https://api.notion.com/v1"

# ─── Notion API limits ────────────────────────────────────────
MAX_BLOCKS_PER_REQUEST : int   = 95    # Notion hard limit per append call
RICH_TEXT_MAX_CHARS    : int   = 1950  # Notion hard limit per rich-text object
REQUEST_INTERVAL_SEC   : float = 0.4   # ~2.5 req/s — well under the 3 req/s cap
MAX_RETRIES            : int   = 5     # max back-off retries on 429
BACKOFF_BASE_SEC       : float = 1.5   # exponential back-off base

DEPT_MAP = {
    "dept_hr": "Human Resources", "dept_finance": "Finance",
    "dept_product_management": "Product Management", "dept_engineering": "Engineering",
    "dept_qa": "QA", "dept_support": "Support",
    "dept_marketing__sales": "Marketing And Sales ", 
    "dept_business__operations": "Business Ops", "dept_legal__compliance": "Legal & Compliance",
    "dept_it__security": "IT & Security", "dept_sales__marketing": "Sales & Marketing",
}

router = APIRouter(prefix="/sessions", tags=["Sessions"])

# ─── Pydantic Models ───────────────────────────────────────────
class SessionCreateRequest(BaseModel):
    template_id: str

class GenerateQuestionsRequest(BaseModel):
    section_id: str
    company_context: Optional[dict] = None

class SubmitAnswersRequest(BaseModel):
    section_id: str
    answers: list  # list of {question_id, answer}

class GenerateSectionRequest(BaseModel):
    section_id: str
    company_context: Optional[dict] = None

class ApproveSectionRequest(BaseModel):
    section_id: str
    edited_content: Optional[str] = None

class CompileRequest(BaseModel):
    doc_title: Optional[str] = "Document"

class EnhanceSectionRequest(BaseModel):
    section_id: str
    enhance_prompt: str
    company_context: Optional[dict] = {}

class PublishRequest(BaseModel):
    doc_title: Optional[str] = "Document"

# ─── Create Session ────────────────────────────────────────────
@router.post("/")
def create_session(payload: SessionCreateRequest):
    db = get_db()
    template = db.document_templates.find_one({"_id": payload.template_id})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    sections       = template["template_json"]["sections"]
    total_sections = len(sections)
    session_id     = f"sess_{uuid.uuid4().hex[:8]}"

    db.doc_sessions.insert_one({
        "_id":                   session_id,
        "template_id":           payload.template_id,
        "dept_id":               template["dept_id"],
        "status":                "in_progress",
        "current_section_index": 0,
        "total_sections":        total_sections,
        "created_at":            datetime.utcnow(),
    })
    return {"session_id": session_id, "total_sections": total_sections}

# ─── Current Section ───────────────────────────────────────────
@router.get("/{session_id}/current_section")
def get_current_section(session_id: str):
    db       = get_db()
    session  = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    idx      = session.get("current_section_index", 0)
    sections = template["template_json"]["sections"]

    if idx >= len(sections):
        return {"all_sections_done": True, "current_index": idx, "total_sections": len(sections)}

    return {
        "all_sections_done": False,
        "section":           sections[idx],
        "current_index":     idx,
        "total_sections":    len(sections),
    }

# ─── Generate Questions ────────────────────────────────────────
@router.post("/{session_id}/generate_questions")
async def generate_questions(session_id: str, payload: GenerateQuestionsRequest):
    db = get_db()
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Get section metadata
    sections = template["template_json"]["sections"]
    section  = next((s for s in sections if s["id"] == payload.section_id), None)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found in template")

    # Check if questions already generated for this section
    existing = db.session_questions.find_one({
        "session_id": session_id,
        "section_id": payload.section_id,
    })
    if existing:
        return {"questions": existing["questions"]}

    # Generate questions via AI — pass company_context so LLM doesn't ask about it
    svc = QuestionService()
    questions = await svc.generate_questions(section, payload.company_context or {})

    # Store generated questions
    db.session_questions.insert_one({
        "_id":        f"q_{uuid.uuid4().hex[:8]}",
        "session_id": session_id,
        "section_id": payload.section_id,
        "questions":  questions,
        "answers":    [],
        "created_at": datetime.utcnow(),
    })

    return {"questions": questions}

# ─── Submit Answers ────────────────────────────────────────────
@router.post("/{session_id}/submit_answers")
def submit_answers(session_id: str, payload: SubmitAnswersRequest):
    db = get_db()
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.session_questions.update_one(
        {"session_id": session_id, "section_id": payload.section_id},
        {"$set": {"answers": payload.answers, "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    return {"message": "Answers saved"}

# ─── Generate Section ──────────────────────────────────────────
@router.post("/{session_id}/generate_section")
async def generate_section(session_id: str, payload: GenerateSectionRequest):
    db = get_db()
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    sections = template["template_json"]["sections"]
    section  = next((s for s in sections if s["id"] == payload.section_id), None)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")

    # Fetch Q&A — qa_doc may be None if questions were skipped
    qa_doc    = db.session_questions.find_one({"session_id": session_id, "section_id": payload.section_id})
    questions = qa_doc["questions"] if qa_doc else []
    answers   = qa_doc["answers"]   if qa_doc else []

    # Build qa_pairs safely — handle both dict answers and plain strings
    qa_pairs = []
    for q, a in zip(questions, answers):
        q_text = q.get("question_text", "") if isinstance(q, dict) else str(q)
        a_text = a.get("answer", "")        if isinstance(a, dict) else str(a)
        qa_pairs.append({"question": q_text, "answer": a_text})

    template_json     = template["template_json"]
    # Use .copy() to avoid mutating the template dict fetched from MongoDB
    generation_rules  = dict(template_json.get("generation_rules", {}))
    terminology_rules = dict(template_json.get("terminology_rules", {}))

    # Inject company context into generation rules so section writer has full context
    if payload.company_context:
        generation_rules["company_context"] = payload.company_context

    svc     = SectionService()
    content = await svc.generate_section(section, qa_pairs, generation_rules, terminology_rules)

    # Save/update section
    existing_sec = db.doc_sections.find_one({"session_id": session_id, "section_id": payload.section_id})
    if existing_sec:
        db.doc_sections.update_one(
            {"_id": existing_sec["_id"]},
            {"$set": {"content": content, "status": "generated", "updated_at": datetime.utcnow()}}
        )
    else:
        db.doc_sections.insert_one({
            "_id":           f"sec_{uuid.uuid4().hex[:8]}",
            "session_id":    session_id,
            "section_id":    payload.section_id,
            "section_title": section["title"],
            "version":       1,
            "content":       content,
            "status":        "generated",
            "created_at":    datetime.utcnow(),
        })

    return {"content": content}

# ─── Approve Section ───────────────────────────────────────────
@router.post("/{session_id}/approve_section")
def approve_section(session_id: str, payload: ApproveSectionRequest):
    db = get_db()
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    total = len(template["template_json"]["sections"])

    sec_doc = db.doc_sections.find_one({"session_id": session_id, "section_id": payload.section_id})
    if not sec_doc:
        raise HTTPException(status_code=404, detail="Section not found")

    # Use edited content if provided
    final_content = payload.edited_content if payload.edited_content else sec_doc["content"]

    db.doc_sections.update_one(
        {"_id": sec_doc["_id"]},
        {"$set": {"content": final_content, "status": "approved", "updated_at": datetime.utcnow()}}
    )

    new_index = session["current_section_index"] + 1
    db.doc_sessions.update_one(
        {"_id": session_id},
        {"$set": {"current_section_index": new_index}}
    )

    return {
        "message":          f"Section '{payload.section_id}' approved",
        "all_sections_done": new_index >= total,
        "next_index":        new_index,
    }

# ─── Get Sections ──────────────────────────────────────────────
@router.get("/{session_id}/sections")
def get_sections(session_id: str):
    db   = get_db()
    docs = list(db.doc_sections.find({"session_id": session_id}))
    return {
        "sections": [
            {
                "section_id":    d["section_id"],
                "section_title": d["section_title"],
                "content":       d["content"],
                "status":        d["status"],
            }
            for d in docs
        ]
    }

# ─── Enhance Section ───────────────────────────────────────────
@router.post("/{session_id}/enhance_section")
async def enhance_section(session_id: str, payload: EnhanceSectionRequest):
    db = get_db()

    # Get session & template
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template_json = template["template_json"]
    sections      = template_json.get("sections", [])

    # Find the section metadata from template
    section_meta = next((s for s in sections if s["id"] == payload.section_id), None)
    if not section_meta:
        raise HTTPException(status_code=404, detail=f"Section '{payload.section_id}' not found in template")

    # Get the current approved content
    sec_doc = db.doc_sections.find_one({"session_id": session_id, "section_id": payload.section_id})
    if not sec_doc:
        raise HTTPException(status_code=404, detail="Section content not found")

    current_content = sec_doc.get("content", "")
    generation_rules = dict(template_json.get("generation_rules", {}))

    svc = SectionService()
    enhanced = await svc.enhance_section(
        section_json     = section_meta,
        current_content  = current_content,
        enhance_prompt   = payload.enhance_prompt,
        company_context  = payload.company_context or {},
        generation_rules = generation_rules,
    )

    return {
        "section_id":     payload.section_id,
        "section_title":  section_meta.get("title", payload.section_id),
        "original":       current_content,
        "enhanced":       enhanced,
    }

# ─── Compile ───────────────────────────────────────────────────
@router.post("/{session_id}/compile")
def compile_document(session_id: str, payload: CompileRequest = None):
    db = get_db()
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    sections = template["template_json"]["sections"]
    compiled = []
    for sec in sections:
        sec_doc = db.doc_sections.find_one({
            "session_id": session_id,
            "section_id": sec["id"],
            "status":     "approved",
        })
        if not sec_doc:
            raise HTTPException(status_code=400, detail=f"Section '{sec['id']}' not approved yet")
        compiled.append(sec_doc)

    final_content = "\n\n---\n\n".join(
        f"## {s['section_title']}\n\n{s['content']}" for s in compiled
    )

    doc_title = (payload.doc_title if payload and payload.doc_title else
                 template.get("label") or template.get("doc_name") or "Document")

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    existing = db.generated_documents.find_one({"session_id": session_id})
    if existing:
        db.generated_documents.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "compiled_content": final_content,
                "doc_title":        doc_title,
                "updated_at":       datetime.utcnow(),
            }}
        )
        doc_id = existing["_id"]
    else:
        db.generated_documents.insert_one({
            "_id":              doc_id,
            "session_id":       session_id,
            "doc_title":        doc_title,
            "compiled_content": final_content,
            "created_at":       datetime.utcnow(),
        })

    return {"message": "Document compiled", "document_id": doc_id, "doc_title": doc_title}

# ─── PDF Helpers ───────────────────────────────────────────────
class DocForgePDF(FPDF):
    doc_title: str = "Document"

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(160, 160, 160)
        self.cell(0, 8, f"DocForge  |  {self.doc_title}", align="R")
        self.ln(8)
        self.set_text_color(0, 0, 0)

def clean(text: str) -> str:
    """Replace known unicode chars and strip anything outside latin-1 range."""
    replacements = {
        "•": "-",   # bullet •
        "–": "-",   # en dash
        "—": "-",   # em dash
        "‘": "'",   # left single quote
        "’": "'",   # right single quote
        "“": '"',   # left double quote
        "”": '"',   # right double quote
        "₹": "Rs.", # rupee sign ₹
        "…": "...", # ellipsis
        " ": " ",   # non-breaking space
        "**": "",        # strip markdown bold markers
        "__": "",        # strip markdown underline markers
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    # Final safety net: drop anything still outside latin-1
    return text.encode("latin-1", errors="ignore").decode("latin-1")

def safe_multicell(pdf, text, line_height=7, width=95):
    """Prevents FPDFException: Not enough horizontal space to render a single character"""
    pdf.set_x(pdf.l_margin)
    wrapped = "\n".join(
        textwrap.wrap(
            clean(text),
            width=width,
            break_long_words=True,
            replace_whitespace=False,
        )
    )
    pdf.multi_cell(0, line_height, wrapped)

def render_markdown_to_pdf(content: str, doc_title: str = "Document") -> bytes:
    pdf = DocForgePDF()
    pdf.doc_title = clean(doc_title)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Title block on first page ──────────────────────────────
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(15, 32, 68)   # dark navy
    safe_multicell(pdf, doc_title, 12, 90)
    pdf.ln(3)
    pdf.set_draw_color(79, 110, 247)  # accent blue
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 60, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(8)

    # Clean entire content FIRST — strip all unicode the font can't handle
    content = clean(content)
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 12)
            safe_multicell(pdf, stripped[4:], 7)
            pdf.ln(1)
        elif stripped.startswith("## "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 14)
            safe_multicell(pdf, stripped[3:], 8)
            pdf.ln(2)
        elif stripped.startswith("# "):
            pdf.ln(6)
            pdf.set_font("Helvetica", "B", 18)
            safe_multicell(pdf, stripped[2:], 10)
            pdf.ln(4)
        elif stripped == "---":
            pdf.ln(2)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)
        elif stripped.startswith("|"):
            pdf.set_font("Helvetica", "", 9)
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(c.replace("-", "").strip() == "" for c in cells):
                continue  # skip separator row |---|---|
            col_w = 180 / max(len(cells), 1)
            for cell in cells:
                pdf.cell(col_w, 7, clean(cell[:50]), border=1)
            pdf.ln()
            pdf.set_x(pdf.l_margin)
        elif stripped.startswith(("- ", "* ")):
            pdf.set_font("Helvetica", "", 11)
            pdf.set_x(pdf.l_margin + 2)
            safe_multicell(pdf, "- " + clean(stripped[2:]), 7, 88)
        elif len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in ".)" :
            pdf.set_font("Helvetica", "", 11)
            safe_multicell(pdf, stripped)
        elif stripped:
            pdf.set_font("Helvetica", "", 11)
            safe_multicell(pdf, stripped, 7)
        else:
            pdf.ln(4)
    return pdf.output()

# ─── Download PDF ───────────────────────────────────────────────
@router.get("/{session_id}/download_pdf")
def download_pdf(session_id: str):
    db           = get_db()
    compiled_doc = db.generated_documents.find_one({"session_id": session_id})
    if not compiled_doc:
        raise HTTPException(status_code=404, detail="Compiled document not found")

    content = compiled_doc.get("compiled_content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Document is empty")

    doc_title = compiled_doc.get("doc_title", "Document")
    safe_filename = "".join(c if c.isalnum() or c in "._- " else "_" for c in doc_title).strip()

    pdf_bytes = render_markdown_to_pdf(content, doc_title)
    buf = BytesIO(pdf_bytes)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}.pdf"'}
    )

# ═══════════════════════════════════════════════════════════════
# NOTION HELPERS
# ═══════════════════════════════════════════════════════════════

def _notion_headers() -> dict:
    return {
        "Authorization":  f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type":   "application/json",
    }

def _notion_request(method: str, url: str, payload: dict) -> dict:
    """Make a Notion API call with exponential backoff on 429."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = http_requests.request(
                method, url,
                headers=_notion_headers(),
                json=payload,
                timeout=30,
            )
            if resp.status_code == 429:
                wait = BACKOFF_BASE_SEC * (2 ** attempt)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except http_requests.exceptions.Timeout:
            if attempt == MAX_RETRIES - 1:
                raise HTTPException(status_code=504, detail="Notion API timed out")
            time.sleep(BACKOFF_BASE_SEC * (2 ** attempt))
        except http_requests.exceptions.HTTPError as e:
            detail = ""
            try:    detail = e.response.json().get("message", str(e))
            except: detail = str(e)
            raise HTTPException(status_code=502, detail=f"Notion API error: {detail}")
    raise HTTPException(status_code=502, detail="Notion API failed after max retries")


def _chunk_text(text: str) -> list:
    """Split text into chunks of max RICH_TEXT_MAX_CHARS on word boundaries."""
    if len(text) <= RICH_TEXT_MAX_CHARS:
        return [text]
    chunks = []
    while text:
        if len(text) <= RICH_TEXT_MAX_CHARS:
            chunks.append(text)
            break
        split_at = text.rfind(" ", 0, RICH_TEXT_MAX_CHARS)
        if split_at == -1:
            split_at = RICH_TEXT_MAX_CHARS
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks


def _make_rich_text(text: str) -> list:
    """Convert a plain string into a Notion rich_text array, handling bold."""
    if not text.strip():
        return [{"type": "text", "text": {"content": ""}}]

    rich = []
    # Parse **bold** segments
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            inner = part[2:-2]
            for chunk in _chunk_text(inner):
                rich.append({
                    "type": "text",
                    "text": {"content": chunk},
                    "annotations": {"bold": True},
                })
        else:
            for chunk in _chunk_text(part):
                if chunk:
                    rich.append({"type": "text", "text": {"content": chunk}})
    return rich if rich else [{"type": "text", "text": {"content": ""}}]


def _make_paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _make_rich_text(text)}}

def _make_heading2(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": _make_rich_text(text)}}

def _make_heading3(text: str) -> dict:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": _make_rich_text(text)}}

def _make_bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _make_rich_text(text)}}

def _make_numbered(text: str) -> dict:
    return {"object": "block", "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": _make_rich_text(text)}}

def _make_divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _parse_table(table_lines: list) -> dict:
    """Convert markdown table lines into a Notion table block."""
    rows = []
    for line in table_lines:
        # Skip separator rows like |---|---|
        stripped = line.strip().strip("|")
        if re.match(r"^[\s\-:|]+$", stripped):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)

    if not rows:
        return None

    table_width = max(len(r) for r in rows)

    # Pad all rows to same width
    padded_rows = [r + [""] * (table_width - len(r)) for r in rows]

    children = []
    for i, row in enumerate(padded_rows):
        cells = []
        for cell in row:
            cells.append(_make_rich_text(cell) if cell.strip() else
                         [{"type": "text", "text": {"content": ""}}])
        children.append({
            "object": "block",
            "type":   "table_row",
            "table_row": {"cells": cells},
        })

    return {
        "object": "block",
        "type":   "table",
        "table": {
            "table_width":       table_width,
            "has_column_header": True,
            "has_row_header":    False,
            "children":          children,
        },
    }


def _content_to_blocks(compiled_content: str) -> list:
    """
    Convert DocForge compiled markdown content into a flat list of Notion blocks.
    Handles: headings, paragraphs, bullets, numbered lists, tables, dividers.
    """
    blocks = []
    sections = compiled_content.split("\n\n---\n\n")

    for sec_idx, section in enumerate(sections):
        lines = section.strip().split("\n")
        if not lines:
            continue

        # Add divider between sections (not before first)
        if sec_idx > 0:
            blocks.append(_make_divider())

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # ── Skip empty lines ──────────────────────────────
            if not stripped:
                i += 1
                continue

            # ── Horizontal rule ───────────────────────────────
            if stripped in ("---", "***", "___"):
                blocks.append(_make_divider())
                i += 1
                continue

            # ── Table detection ───────────────────────────────
            if stripped.startswith("|"):
                table_lines = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i])
                    i += 1
                tbl = _parse_table(table_lines)
                if tbl:
                    blocks.append(tbl)
                continue

            # ── Headings ──────────────────────────────────────
            if stripped.startswith("### "):
                blocks.append(_make_heading3(stripped[4:].strip()))
                i += 1
                continue
            if stripped.startswith("## "):
                blocks.append(_make_heading2(stripped[3:].strip()))
                i += 1
                continue
            if stripped.startswith("# "):
                blocks.append(_make_heading2(stripped[2:].strip()))
                i += 1
                continue

            # ── Bullet list ───────────────────────────────────
            if stripped.startswith("- ") or stripped.startswith("* "):
                blocks.append(_make_bullet(stripped[2:].strip()))
                i += 1
                continue

            # ── Numbered list ─────────────────────────────────
            num_match = re.match(r"^\d+[.)]\s+(.*)", stripped)
            if num_match:
                blocks.append(_make_numbered(num_match.group(1).strip()))
                i += 1
                continue

            # ── Normal paragraph ──────────────────────────────
            blocks.append(_make_paragraph(stripped))
            i += 1

    return blocks


def _append_blocks(page_id: str, blocks: list) -> None:
    """Append blocks to a Notion page in batches of MAX_BLOCKS_PER_REQUEST."""
    url = f"{NOTION_BASE_URL}/blocks/{page_id}/children"
    for batch_start in range(0, len(blocks), MAX_BLOCKS_PER_REQUEST):
        batch = blocks[batch_start : batch_start + MAX_BLOCKS_PER_REQUEST]
        _notion_request("PATCH", url, {"children": batch})
        if batch_start + MAX_BLOCKS_PER_REQUEST < len(blocks):
            time.sleep(REQUEST_INTERVAL_SEC)


# ─── Publish to Notion ─────────────────────────────────────────
@router.post("/{session_id}/publish_notion")
def publish_notion(session_id: str, payload: PublishRequest):
    db = get_db()

    # ── Get compiled document ──────────────────────────────────
    compiled_doc = db.generated_documents.find_one({"session_id": session_id})
    if not compiled_doc:
        raise HTTPException(status_code=404, detail="Compiled document not found")

    content = compiled_doc.get("compiled_content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Document content is empty")

    # ── Get session + template info ────────────────────────────
    session  = db.doc_sessions.find_one({"_id": session_id})
    dept_id  = session.get("dept_id", "") if session else ""
    template = db.document_templates.find_one(
        {"_id": session.get("template_id", "")}
    ) if session else None

    doc_title = (payload.doc_title or compiled_doc.get("doc_title", "Document")).strip()
    tags      = (template.get("label") or template.get("doc_name", "")) if template else doc_title
    industry  = DEPT_MAP.get(dept_id, dept_id.replace("_", " ").title() if dept_id else "General")

    # ── Version tracking ───────────────────────────────────────
    existing = db.notion_publishes.count_documents({"session_id": session_id})
    version  = f"v{existing + 1}"

    # ── Convert content to Notion blocks ──────────────────────
    all_blocks = _content_to_blocks(content)

    # First batch goes in the page creation call (max 95)
    first_batch    = all_blocks[:MAX_BLOCKS_PER_REQUEST]
    remaining      = all_blocks[MAX_BLOCKS_PER_REQUEST:]

    # ── Create Notion page with properties + first batch ──────
    page_payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name":     {"title":  [{"text": {"content": doc_title}}]},
            "industry": {"rich_text": [{"text": {"content": industry}}]},
            "version":  {"rich_text": [{"text": {"content": version}}]},
            "tags":     {"rich_text": [{"text": {"content": tags}}]},
        },
        "children": first_batch,
    }

    time.sleep(REQUEST_INTERVAL_SEC)
    page = _notion_request("POST", f"{NOTION_BASE_URL}/pages", page_payload)
    page_id  = page["id"]
    page_url = page.get("url", f"https://www.notion.so/{page_id.replace('-', '')}")

    # ── Append remaining blocks in batches ────────────────────
    if remaining:
        time.sleep(REQUEST_INTERVAL_SEC)
        _append_blocks(page_id, remaining)

    # ── Store publish record ───────────────────────────────────
    db.notion_publishes.insert_one({
        "session_id":   session_id,
        "doc_title":    doc_title,
        "version":      version,
        "notion_page_id": page_id,
        "notion_url":   page_url,
        "published_at": datetime.utcnow(),
    })

    return {
        "message":    "Published to Notion successfully",
        "doc_title":  doc_title,
        "version":    version,
        "industry":   industry,
        "tags":       tags,
        "notion_url": page_url,
    }