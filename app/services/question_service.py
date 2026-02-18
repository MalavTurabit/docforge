import json
import re
from app.services.llm_provider import LLMProvider


def extract_questions_from_llm(raw_text: str):
    try:
        # Extract JSON block from markdown response
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

    async def generate_questions(self, section_json: dict) -> list:
        prompt = f"""
You are an expert document architect. Your job is to generate targeted questions that, when answered, will give an LLM everything it needs to write a specific document section accurately and completely.

SECTION METADATA:
{json.dumps(section_json, indent=2)}

Generate 5–7 questions that:
- Are specific to this section's purpose and prompt_hint
- Surface the exact content, data, or decisions an LLM would need to draft this section
- Prioritize gaps — focus on information NOT already present in the metadata
- Are answerable by a human domain expert or stakeholder
- Avoid generic or structural questions

Return ONLY valid JSON:
{{
  "questions": []
}}
"""

        response = await self.llm.generate(prompt)
        print("LLM RAW RESPONSE:", response)

        # ✅ Use extractor instead of direct json.loads
        questions = extract_questions_from_llm(response)

        print("EXTRACTED QUESTIONS:", questions)

        return questions
