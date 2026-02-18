from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
import uuid
from fastapi.responses import StreamingResponse
from io import BytesIO
from fpdf import FPDF

from app.db import get_db

# -------------------------
# Pydantic model for request
# -------------------------
class SessionCreateRequest(BaseModel):
    template_id: str

# -------------------------
# Router setup
# -------------------------
router = APIRouter(prefix="/sessions", tags=["Sessions"])

# -------------------------
# Create a session endpoint
# -------------------------
@router.post("/")
def create_session(payload: SessionCreateRequest):
    db = get_db()

    # Get template ID from request
    template_id = payload.template_id

    # 1️⃣ Fetch template by Mongo _id
    template = db.document_templates.find_one({"_id": template_id})

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # 2️⃣ Count sections
    sections = template["template_json"]["sections"]
    total_sections = len(sections)

    # 3️⃣ Create session record
    session_id = f"sess_{uuid.uuid4().hex[:8]}"

    session_doc = {
        "_id": session_id,
        "template_id": template_id,
        "dept_id": template["dept_id"],
        "status": "in_progress",
        "current_section_index": 0,
        "total_sections": total_sections,
        "created_at": datetime.utcnow()
    }

    db.doc_sessions.insert_one(session_doc)

    # 4️⃣ Return response
    return {
        "session_id": session_id,
        "total_sections": total_sections,
        "message": "Session created successfully"
    }
@router.get("/{session_id}/current_section")
def get_current_section(session_id: str):
    db = get_db()

    # 1️⃣ Fetch session
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2️⃣ Fetch associated template
    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # 3️⃣ Get current section index
    current_index = session.get("current_section_index", 0)
    sections = template["template_json"]["sections"]

    # 4️⃣ If all sections are completed
    if current_index >= len(sections):
        return {"message": "All sections completed"}

    # 5️⃣ Return the current section metadata
    current_section = sections[current_index]

    return current_section

class SectionQuestionRequest(BaseModel):
    section_id: str
    questions: list[str]        # AI-generated questions
    answers: list[str]          # User answers (in same order as questions)

@router.post("/{session_id}/questions")
def add_section_questions(session_id: str, payload: SectionQuestionRequest):
    db = get_db()

    # 1️⃣ Fetch session
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2️⃣ Prepare question document
    question_doc = {
        "_id": f"q_{uuid.uuid4().hex[:8]}",
        "session_id": session_id,
        "dept_id": session["dept_id"],
        "template_id": session["template_id"],
        "section_id": payload.section_id,
        "questions": payload.questions,
        "answers": payload.answers,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    # 3️⃣ Insert into session_questions collection
    db.session_questions.insert_one(question_doc)

    return {
        "message": "Questions and answers saved successfully",
        "question_doc_id": question_doc["_id"]
    }

class GenerateSectionRequest(BaseModel):
    section_id: str

@router.post("/{session_id}/generate_section")
def generate_section(session_id: str, payload: GenerateSectionRequest):
    db = get_db()

    # 1️⃣ Fetch session
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2️⃣ Fetch template
    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # 3️⃣ Fetch section metadata
    sections = template["template_json"]["sections"]
    section = next((s for s in sections if s["id"] == payload.section_id), None)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found in template")

    # 4️⃣ Fetch user answers
    qa_doc = db.session_questions.find_one({
        "session_id": session_id,
        "section_id": payload.section_id
    })
    answers = qa_doc.get("answers", []) if qa_doc else []

    # 5️⃣ Generate content (placeholder)
    # Here you would call your AI generator using `section` and `answers`
    generated_content = f"Generated content for section '{payload.section_id}' using answers: {answers}"

    # 6️⃣ Save to doc_sections
    section_doc = {
        "_id": f"sec_{uuid.uuid4().hex[:8]}",
        "session_id": session_id,
        "section_id": payload.section_id,
        "section_title": section["title"],
        "version": 1,
        "content": generated_content,
        "status": "generated",
        "created_at": datetime.utcnow()
    }
    db.doc_sections.insert_one(section_doc)

    return {
        "message": f"Section '{payload.section_id}' generated successfully",
        "section_doc_id": section_doc["_id"],
        "content_preview": generated_content[:200]  # first 200 chars
    }

from pydantic import BaseModel

class ApproveSectionRequest(BaseModel):
    section_id: str

@router.post("/{session_id}/approve_section")
def approve_section(session_id: str, payload: ApproveSectionRequest):
    db = get_db()

    # 1️⃣ Fetch session
    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2️⃣ Check section exists and is generated
    section_doc = db.doc_sections.find_one({
        "session_id": session_id,
        "section_id": payload.section_id,
        "status": "generated"
    })
    if not section_doc:
        raise HTTPException(status_code=404, detail="Section not generated yet")

    # 3️⃣ Mark section as approved
    db.doc_sections.update_one(
        {"_id": section_doc["_id"]},
        {"$set": {"status": "approved"}}
    )

    # 4️⃣ Increment current_section_index in session
    new_index = session["current_section_index"] + 1
    db.doc_sessions.update_one(
        {"_id": session_id},
        {"$set": {"current_section_index": new_index}}
    )

    return {
        "message": f"Section '{payload.section_id}' approved",
        "next_section_index": new_index
    }

@router.post("/{session_id}/compile")
def compile_document(session_id: str):
    db = get_db()
    print("DEBUG: session_id received from URL:", session_id)



    # 1️⃣ Fetch session
    session = db.doc_sessions.find_one({"_id": session_id})
    print("DEBUG: session fetched:", session)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2️⃣ Fetch template sections
    template = db.document_templates.find_one({"_id": session["template_id"]})
    print("DEBUG: template fetched:", template)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    sections = template["template_json"]["sections"]

    # 3️⃣ Fetch all approved sections for this session
    compiled_sections = []
    print("DEBUG: sections in template:", [sec["id"] for sec in sections])
    for sec in sections:
        sec_doc = db.doc_sections.find_one({
            "session_id": session_id,
            "section_id": sec["id"],
            "status": "approved"
        })
        if not sec_doc:
            raise HTTPException(status_code=400, detail=f"Section '{sec['id']}' not approved yet")
        compiled_sections.append(sec_doc["content"])

    # 4️⃣ Merge content
    final_content = "\n\n".join(compiled_sections)

    # 5️⃣ Save to generated_documents
    final_doc = {
        "_id": f"doc_{uuid.uuid4().hex[:8]}",
        "session_id": session_id,
        "compiled_content": final_content,
        "created_at": datetime.utcnow()
    }
    db.generated_documents.insert_one(final_doc)
    
    return {
        "message": "Document compiled successfully",
        "document_id": final_doc["_id"]
    }

from pydantic import BaseModel

class PublishRequest(BaseModel):
    notion_database_id: str  # Target Notion database
    title_field: str = "title"  # Which field in Notion to set title

@router.get("/{session_id}/download_pdf")
def download_pdf(session_id: str):
    db = get_db()

    # 1️⃣ Fetch compiled document
    compiled_doc = db.generated_documents.find_one({"session_id": session_id})
    if not compiled_doc:
        raise HTTPException(status_code=404, detail="Compiled document not found")

    content = compiled_doc.get("compiled_content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Compiled document is empty")

    # 2️⃣ Create PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Use UTF-8 capable font
    pdf.add_font('DejaVu', '', 'DejaVuSans.ttf', uni=True)
    pdf.set_font("DejaVu", size=12)
    
    for line in content.split("\n"):
        pdf.multi_cell(0, 8, line)

    # 3️⃣ Save to BytesIO
    pdf_output = BytesIO()
    pdf.output(pdf_output)
    pdf_output.seek(0)

    # 4️⃣ Return PDF response
    return StreamingResponse(
        pdf_output,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=document_{session_id}.pdf"}
    )