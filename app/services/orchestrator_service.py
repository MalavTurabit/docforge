from app.db import db
from app.db import get_db
from app.services.question_service import QuestionService
from app.services.section_service import SectionService


class OrchestratorService:

    def __init__(self):
        self.db = get_db()
        self.question_service = QuestionService()
        self.section_service = SectionService()

    async def handle_section_generation(self, session_id, section_json, template_json):

        # 1 Check existing questions
        questions_doc = self.db.session_questions.find_one({
            "session_id": session_id,
            "section_id": section_json["id"]
        })

        # 2 If not present → generate
        if not questions_doc:
            questions = await self.question_service.generate_questions(section_json)

            self.db.session_questions.insert_one({
                "session_id": session_id,
                "section_id": section_json["id"],
                "questions": questions,
                "answers": [],
                "status": "pending"
            })

            return {
                "status": "questions_generated",
                "questions": questions
            }

        # 3 Wait for answers
        if len(questions_doc["answers"]) < len(questions_doc["questions"]):
            return {"status": "waiting_for_answers"}

        # 4 Generate section
        qa_pairs = list(zip(
            questions_doc["questions"],
            questions_doc["answers"]
        ))

        content = await self.section_service.generate_section(
            section_json,
            qa_pairs,
            template_json["generation_rules"],
            template_json["terminology_rules"]
        )

        # 5 Save section
        self.db.doc_sections.insert_one({
            "session_id": session_id,
            "section_id": section_json["id"],
            "section_title": section_json["title"],
            "version": 1,
            "content": content,
            "status": "generated"
        })

        return {
            "status": "section_generated",
            "content": content
        }

async def run_pipeline(session_id: str, section_json: dict, template_json: dict):
    orchestrator = OrchestratorService()
    return await orchestrator.handle_section_generation(
        session_id,
        section_json,
        template_json
    )