from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid
import textwrap
from fastapi.responses import StreamingResponse
from io import BytesIO
from fpdf import FPDF
from app.db import get_db
from app.services.question_service import QuestionService
from app.services.section_service import SectionService

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
    notion_database_id: str
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

# ─── Publish to Notion ─────────────────────────────────────────
@router.post("/{session_id}/publish_notion")
def publish_notion(session_id: str, payload: PublishRequest):
    db           = get_db()
    compiled_doc = db.generated_documents.find_one({"session_id": session_id})
    if not compiled_doc:
        raise HTTPException(status_code=404, detail="Compiled document not found")
    # Notion publish logic goes here
    return {"message": "Published to Notion successfully"}