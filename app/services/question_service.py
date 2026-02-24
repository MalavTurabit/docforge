import json
import re
from app.services.llm_provider import LLMProvider


def extract_questions_from_llm(raw_text: str):
    try:
        match = re.search(r'\{.*\}', raw_text, re.S)
        if not match:
            print("No JSON found in LLM response")
            return []
        json_str = match.group()
        data = json.loads(json_str)
        return data.get("questions", [])
    except Exception as e:
        print("JSON parsing error:", e)
        return []


class QuestionService:
    def __init__(self):
        self.llm = LLMProvider()

    async def generate_questions(self, section_json: dict, company_context: dict = None) -> list:

        # Build context block from what we already know
        known_info = ""
        if company_context:
            known_info = f"""
ALREADY KNOWN — DO NOT ask about any of these:
- Company name: {company_context.get('company_name', '')}
- Product name: {company_context.get('product_name', '')}
- Product description: {company_context.get('product_description', '')}
- Industry: {company_context.get('industry_vertical', '')}
- Company stage: {company_context.get('company_stage', '')}
- Target customer: {company_context.get('target_customer', '')}
- Key problem solved: {company_context.get('key_problem_solved', '')}
"""

        prompt = f"""You are helping draft one section of a business document. Your job is to ask the user ONLY what you need to write this section well.

SECTION TO DRAFT:
{json.dumps(section_json, indent=2)}
{known_info}
RULES:
1. Read the section title and prompt_hint carefully to understand what this section is ABOUT
2. Ask ONLY about content that belongs in THIS section of THIS document
   - "Candidate Details" in an offer letter → ask about the candidate's name, role, start date, location — NOT about technology, systems, or products
   - "Compensation" in an offer letter → ask about salary, bonuses, equity, pay frequency
   - "Scope of Work" in a contract → ask about deliverables, timelines, exclusions
3. NEVER ask about the company product, technology stack, or business model — that is already known above
4. NEVER ask generic questions like "are there any compliance requirements" or "what format should be used"
5. If the section likely needs a TABLE (e.g. compensation breakdown, fee schedule, pricing), ask for the specific numbers/rows needed for that table
6. Ask the MINIMUM questions needed — aim for 2-3, max 5 only if the section is genuinely complex
7. Each question must be direct and specific — answerable in 1-3 sentences

Return ONLY this JSON:
{{
  "questions": [
    {{"question_id": "q1", "question_text": "..."}},
    {{"question_id": "q2", "question_text": "..."}}
  ]
}}"""

        response = await self.llm.generate(prompt)
        print("LLM RAW RESPONSE:", response)
        questions = extract_questions_from_llm(response)
        print("EXTRACTED QUESTIONS:", questions)
        return questions