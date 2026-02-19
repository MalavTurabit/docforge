import uuid
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from fpdf import FPDF
from pydantic import BaseModel

from app.db import get_db
from app.services.orchestrator_service import OrchestratorService

router = APIRouter(prefix="/sessions", tags=["Sessions"])


# ──────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ──────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    template_id: str


class GenerateQuestionsRequest(BaseModel):
    section_id: str  # the section we want questions for


class AnswerItem(BaseModel):
    question_id: str
    answer: str


class SubmitAnswersRequest(BaseModel):
    section_id: str
    answers: list[AnswerItem]


class GenerateSectionRequest(BaseModel):
    section_id: str


class ApproveSectionRequest(BaseModel):
    section_id: str
    edited_content: str | None = None  # optional manual edit before approval


# ──────────────────────────────────────────────
# 1. CREATE SESSION
# ──────────────────────────────────────────────

@router.post("/")
def create_session(payload: SessionCreateRequest):
    db = get_db()

    template = db.document_templates.find_one({"_id": payload.template_id})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    sections = template["template_json"]["sections"]
    total_sections = len(sections)

    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    session_doc = {
        "_id": session_id,
        "template_id": payload.template_id,
        "dept_id": template["dept_id"],
        "status": "in_progress",
        "current_section_index": 0,
        "total_sections": total_sections,
        "created_at": datetime.utcnow(),
    }
    db.doc_sessions.insert_one(session_doc)

    return {
        "session_id": session_id,
        "total_sections": total_sections,
        "message": "Session created successfully",
    }


# ──────────────────────────────────────────────
# 2. GET CURRENT SECTION METADATA
# ──────────────────────────────────────────────

@router.get("/{session_id}/current_section")
def get_current_section(session_id: str):
    db = get_db()

    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    current_index = session.get("current_section_index", 0)
    sections = template["template_json"]["sections"]

    if current_index >= len(sections):
        return {
            "all_sections_done": True,
            "message": "All sections completed. Ready to compile.",
        }

    return {
        "all_sections_done": False,
        "current_index": current_index,
        "total_sections": len(sections),
        "section": sections[current_index],
    }


# ──────────────────────────────────────────────
# 3. GENERATE QUESTIONS FOR CURRENT SECTION
#    (LLM call via orchestrator)
# ──────────────────────────────────────────────

@router.post("/{session_id}/generate_questions")
async def generate_questions(session_id: str, payload: GenerateQuestionsRequest):
    db = get_db()

    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    template = db.document_templates.find_one({"_id": session["template_id"]})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    sections = template["template_json"]["sections"]
    section_json = next(
        (s for s in sections if s["id"] == payload.section_id), None
    )
    if not section_json:
        raise HTTPException(status_code=404, detail="Section not found in template")

    orchestrator = OrchestratorService()
    result = await orchestrator.generate_questions_for_section(session_id, section_json)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["detail"])

    return result


# ──────────────────────────────────────────────
# 4. SUBMIT ANSWERS FOR A SECTION
# ──────────────────────────────────────────────

@router.post("/{session_id}/submit_answers")
def submit_answers(session_id: str, payload: SubmitAnswersRequest):
    db = get_db()

    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    orchestrator = OrchestratorService()
    result = orchestrator.save_answers(
        session_id,
        payload.section_id,
        [a.dict() for a in payload.answers],
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["detail"])

    return result


# ──────────────────────────────────────────────
# 5. GENERATE SECTION CONTENT (LLM writes section)
# ──────────────────────────────────────────────

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
    section_json = next(
        (s for s in sections if s["id"] == payload.section_id), None
    )
    if not section_json:
        raise HTTPException(status_code=404, detail="Section not found in template")

    orchestrator = OrchestratorService()
    result = await orchestrator.generate_section_content(
        session_id, section_json, template["template_json"]
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["detail"])

    if result.get("status") == "waiting_for_answers":
        raise HTTPException(
            status_code=400,
            detail=f"Unanswered required questions: {result.get('unanswered_question_ids')}",
        )

    return result


# ──────────────────────────────────────────────
# 6. APPROVE SECTION (with optional manual edit)
# ──────────────────────────────────────────────

@router.post("/{session_id}/approve_section")
def approve_section(session_id: str, payload: ApproveSectionRequest):
    db = get_db()

    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    orchestrator = OrchestratorService()
    result = orchestrator.approve_section(
        session_id, payload.section_id, payload.edited_content
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["detail"])

    return result


# ──────────────────────────────────────────────
# 7. GET ALL GENERATED SECTIONS (for final review)
# ──────────────────────────────────────────────

@router.get("/{session_id}/sections")
def get_all_sections(session_id: str):
    db = get_db()

    session = db.doc_sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sections = list(
        db.doc_sections.find(
            {"session_id": session_id},
            {"_id": 1, "section_id": 1, "section_title": 1, "content": 1, "status": 1},
        )
    )

    return {"session_id": session_id, "sections": sections}


# ──────────────────────────────────────────────
# 8. COMPILE FINAL DOCUMENT
# ──────────────────────────────────────────────

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

    compiled_sections = []
    for sec in sections:
        sec_doc = db.doc_sections.find_one(
            {
                "session_id": session_id,
                "section_id": sec["id"],
                "status": "approved",
            }
        )
        if not sec_doc:
            raise HTTPException(
                status_code=400,
                detail=f"Section '{sec['id']}' is not approved yet.",
            )
        compiled_sections.append(
            f"## {sec_doc['section_title']}\n\n{sec_doc['content']}"
        )

    final_content = "\n\n---\n\n".join(compiled_sections)

    # Upsert compiled doc (allow recompilation)
    existing_doc = db.generated_documents.find_one({"session_id": session_id})
    if existing_doc:
        db.generated_documents.update_one(
            {"_id": existing_doc["_id"]},
            {"$set": {"compiled_content": final_content, "updated_at": datetime.utcnow()}},
        )
        document_id = existing_doc["_id"]
    else:
        document_id = f"doc_{uuid.uuid4().hex[:8]}"
        db.generated_documents.insert_one(
            {
                "_id": document_id,
                "session_id": session_id,
                "compiled_content": final_content,
                "created_at": datetime.utcnow(),
            }
        )

    db.doc_sessions.update_one(
        {"_id": session_id}, {"$set": {"status": "compiled"}}
    )

    return {
        "message": "Document compiled successfully",
        "document_id": document_id,
    }


# ──────────────────────────────────────────────
# 9. DOWNLOAD PDF
# ──────────────────────────────────────────────

@router.get("/{session_id}/download_pdf")
def download_pdf(session_id: str):
    db = get_db()

    compiled_doc = db.generated_documents.find_one({"session_id": session_id})
    if not compiled_doc:
        raise HTTPException(status_code=404, detail="Compiled document not found. Run /compile first.")

    content = compiled_doc.get("compiled_content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Compiled document is empty")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("DejaVu", "", "DejaVuSans.ttf", uni=True)
    pdf.set_font("DejaVu", size=12)

    for line in content.split("\n"):
        pdf.multi_cell(0, 8, line)

    pdf_output = BytesIO()
    pdf.output(pdf_output)
    pdf_output.seek(0)

    return StreamingResponse(
        pdf_output,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=document_{session_id}.pdf"
        },
    )


# ──────────────────────────────────────────────
# 10. PUBLISH TO NOTION
# ──────────────────────────────────────────────

class PublishToNotionRequest(BaseModel):
    notion_database_id: str
    doc_title: str = "Generated Document"


@router.post("/{session_id}/publish_notion")
async def publish_to_notion(session_id: str, payload: PublishToNotionRequest):
    db = get_db()

    compiled_doc = db.generated_documents.find_one({"session_id": session_id})
    if not compiled_doc:
        raise HTTPException(status_code=404, detail="Compiled document not found. Run /compile first.")

    content = compiled_doc.get("compiled_content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Compiled document is empty")

    # Notiob mcp need to implemnt latter on  

    db.generated_documents.update_one(
        {"_id": compiled_doc["_id"]},
        {
            "$set": {
                "notion_database_id": payload.notion_database_id,
                "notion_publish_requested": True,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    return {
        "message": "Notion publish request recorded. Use the Streamlit frontend to push via Notion MCP.",
        "session_id": session_id,
        "notion_database_id": payload.notion_database_id,
        "content_length": len(content),
    }