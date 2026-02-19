import uuid
from datetime import datetime

from app.db import get_db
from app.services.question_service import QuestionService
from app.services.section_service import SectionService


class OrchestratorService:
    """
    Drives the section-by-section document generation loop.

    State machine per section:
        no questions doc  →  generate questions  →  return  (frontend shows Q form)
        questions exist, answers incomplete  →  waiting_for_answers
        answers complete, no section doc  →  generate section content  →  return
        section generated  →  waiting_for_approval (user edits / approves)
    """

    def __init__(self):
        self.db = get_db()
        self.question_service = QuestionService()
        self.section_service = SectionService()

    # ------------------------------------------------------------------
    # STEP 1 – Generate questions for a section (called on section start)
    # ------------------------------------------------------------------
    async def generate_questions_for_section(
        self, session_id: str, section_json: dict
    ) -> dict:
        session = self.db.doc_sessions.find_one({"_id": session_id})
        if not session:
            return {"status": "error", "detail": "Session not found"}

        section_id = section_json["id"]

        # Idempotent: if questions already exist just return them
        existing = self.db.session_questions.find_one(
            {"session_id": session_id, "section_id": section_id}
        )
        if existing:
            return {
                "status": "questions_ready",
                "questions": existing["questions"],
                "question_doc_id": existing["_id"],
            }

        # Call LLM to generate questions
        raw_questions: list[str] = await self.question_service.generate_questions(
            section_json
        )

        # Build structured question list matching session_questions schema
        structured_questions = [
            {
                "question_id": f"q{i + 1}",
                "question_text": q,
                "answer": "",
                "type": "text",
                "is_required": True,
            }
            for i, q in enumerate(raw_questions)
        ]

        doc = {
            "_id": f"sq_{uuid.uuid4().hex[:8]}",
            "session_id": session_id,
            "dept_id": session["dept_id"],
            "template_id": session["template_id"],
            "section_id": section_id,
            "section_title": section_json.get("title", section_id),
            "generation_round": 1,
            "questions": structured_questions,
            "status": "questions_generated",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        self.db.session_questions.insert_one(doc)

        return {
            "status": "questions_ready",
            "questions": structured_questions,
            "question_doc_id": doc["_id"],
        }

    # ------------------------------------------------------------------
    # STEP 2 – Save user answers (upsert into the questions doc)
    # ------------------------------------------------------------------
    def save_answers(
        self, session_id: str, section_id: str, answers: list[dict]
    ) -> dict:
        """
        `answers` is a list of dicts: [{"question_id": "q1", "answer": "..."}, ...]
        """
        existing = self.db.session_questions.find_one(
            {"session_id": session_id, "section_id": section_id}
        )
        if not existing:
            return {"status": "error", "detail": "Questions doc not found – generate questions first"}

        # Merge answers into the structured questions list
        answer_map = {a["question_id"]: a["answer"] for a in answers}
        updated_questions = []
        for q in existing["questions"]:
            q_copy = dict(q)
            if q_copy["question_id"] in answer_map:
                q_copy["answer"] = answer_map[q_copy["question_id"]]
            updated_questions.append(q_copy)

        self.db.session_questions.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "questions": updated_questions,
                    "status": "answers_submitted",
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return {"status": "answers_saved", "question_doc_id": existing["_id"]}

    # ------------------------------------------------------------------
    # STEP 3 – Generate section content using the saved Q&A
    # ------------------------------------------------------------------
    async def generate_section_content(
        self, session_id: str, section_json: dict, template_json: dict
    ) -> dict:
        section_id = section_json["id"]

        # Fetch Q&A doc
        qa_doc = self.db.session_questions.find_one(
            {"session_id": session_id, "section_id": section_id}
        )
        if not qa_doc:
            return {"status": "error", "detail": "No questions found for this section"}

        # Check all required questions are answered
        unanswered = [
            q["question_id"]
            for q in qa_doc["questions"]
            if q.get("is_required") and not q.get("answer", "").strip()
        ]
        if unanswered:
            return {
                "status": "waiting_for_answers",
                "unanswered_question_ids": unanswered,
            }

        # Build qa_pairs for the section service
        qa_pairs = [
            {"question": q["question_text"], "answer": q["answer"]}
            for q in qa_doc["questions"]
        ]

        # Call LLM to write the section
        content: str = await self.section_service.generate_section(
            section_json,
            qa_pairs,
            template_json.get("generation_rules", {}),
            template_json.get("terminology_rules", {}),
        )

        # Upsert into doc_sections (allow regeneration)
        existing_sec = self.db.doc_sections.find_one(
            {"session_id": session_id, "section_id": section_id}
        )
        if existing_sec:
            self.db.doc_sections.update_one(
                {"_id": existing_sec["_id"]},
                {
                    "$set": {
                        "content": content,
                        "status": "generated",
                        "version": existing_sec.get("version", 1) + 1,
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            section_doc_id = existing_sec["_id"]
        else:
            section_doc_id = f"sec_{uuid.uuid4().hex[:8]}"
            self.db.doc_sections.insert_one(
                {
                    "_id": section_doc_id,
                    "session_id": session_id,
                    "section_id": section_id,
                    "section_title": section_json.get("title", section_id),
                    "version": 1,
                    "content": content,
                    "status": "generated",
                    "created_at": datetime.utcnow(),
                }
            )

        return {
            "status": "section_generated",
            "section_doc_id": section_doc_id,
            "content": content,
        }

    # ------------------------------------------------------------------
    # STEP 4 – Approve section (with optional manual edit)
    # ------------------------------------------------------------------
    def approve_section(
        self, session_id: str, section_id: str, edited_content: str | None = None
    ) -> dict:
        section_doc = self.db.doc_sections.find_one(
            {"session_id": session_id, "section_id": section_id}
        )
        if not section_doc:
            return {"status": "error", "detail": "Section not found"}

        update_fields: dict = {"status": "approved", "updated_at": datetime.utcnow()}
        if edited_content is not None:
            update_fields["content"] = edited_content.strip()

        self.db.doc_sections.update_one(
            {"_id": section_doc["_id"]}, {"$set": update_fields}
        )

        # Advance session index
        session = self.db.doc_sessions.find_one({"_id": session_id})
        new_index = session["current_section_index"] + 1
        all_done = new_index >= session["total_sections"]

        self.db.doc_sessions.update_one(
            {"_id": session_id},
            {
                "$set": {
                    "current_section_index": new_index,
                    "status": "completed" if all_done else "in_progress",
                }
            },
        )

        return {
            "status": "approved",
            "next_section_index": new_index,
            "all_sections_done": all_done,
        }