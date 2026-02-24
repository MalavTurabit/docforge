from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid
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

# ─── Compile ───────────────────────────────────────────────────
@router.post("/{session_id}/compile")
def compile_document(session_id: str):
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

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    existing = db.generated_documents.find_one({"session_id": session_id})
    if existing:
        db.generated_documents.update_one(
            {"_id": existing["_id"]},
            {"$set": {"compiled_content": final_content, "updated_at": datetime.utcnow()}}
        )
        doc_id = existing["_id"]
    else:
        db.generated_documents.insert_one({
            "_id":              doc_id,
            "session_id":       session_id,
            "compiled_content": final_content,
            "created_at":       datetime.utcnow(),
        })

    return {"message": "Document compiled", "document_id": doc_id}

# ─── Download PDF ──────────────────────────────────────────────
@router.get("/{session_id}/download_pdf")
def download_pdf(session_id: str):
    db          = get_db()
    compiled_doc = db.generated_documents.find_one({"session_id": session_id})
    if not compiled_doc:
        raise HTTPException(status_code=404, detail="Compiled document not found")

    content = compiled_doc.get("compiled_content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Document is empty")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.ln(4)
            pdf.multi_cell(0, 8, stripped[3:])
            pdf.ln(2)
        elif stripped == "---":
            pdf.set_draw_color(200, 200, 200)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(3)
        elif stripped.startswith("|"):
            # Markdown table row — render as simple text
            pdf.set_font("Helvetica", "", 9)
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            col_w = 180 // max(len(cells), 1)
            for cell in cells:
                if cell.replace("-","").strip() == "":
                    continue
                pdf.cell(col_w, 7, cell[:30], border=1)
            if not all(c.replace("-","").strip() == "" for c in cells):
                pdf.ln()
        elif stripped:
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 7, stripped)

    # fpdf2's output() returns bytes directly — don't pass BytesIO
    pdf_bytes = pdf.output()
    buf = BytesIO(pdf_bytes)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=document_{session_id}.pdf"}
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