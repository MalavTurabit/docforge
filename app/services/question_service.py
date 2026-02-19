import json
import re

from app.services.llm_provider import LLMProvider


def extract_questions_from_llm(raw_text: str) -> list[str]:
    """
    Robustly pull the questions list out of the LLM response even if it
    wraps the JSON in markdown fences or adds commentary.
    """
    try:
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()

        # Find the first JSON object in the response
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            print("[QuestionService] No JSON object found in LLM response")
            return []

        data = json.loads(match.group())
        questions = data.get("questions", [])

        # Normalise: handle both list-of-strings and list-of-dicts
        result = []
        for q in questions:
            if isinstance(q, str):
                result.append(q.strip())
            elif isinstance(q, dict):
                text = q.get("question_text") or q.get("text") or q.get("question") or ""
                if text:
                    result.append(text.strip())

        return result

    except Exception as e:
        print(f"[QuestionService] JSON parse error: {e}")
        return []


class QuestionService:
    def __init__(self):
        self.llm = LLMProvider()

    async def generate_questions(self, section_json: dict) -> list[str]:
        """
        Generate 5-7 targeted questions for the given section.
        Returns a plain list of question strings.
        """
        prompt = f"""You are an expert document architect. Your job is to generate targeted questions that, when answered, will give an AI everything it needs to write a specific document section accurately and completely.

SECTION METADATA:
{json.dumps(section_json, indent=2)}

Generate 5 to 7 questions that:
- Are specific to this section's purpose and prompt_hint
- Surface the exact content, data, or decisions needed to draft this section
- Focus on information NOT already present in the metadata
- Are answerable by a human domain expert or stakeholder
- Avoid generic or structural questions

Return ONLY valid JSON with no extra commentary:
{{
  "questions": [
    "Question 1 text here",
    "Question 2 text here"
  ]
}}
"""
        response = await self.llm.generate(prompt)
        print("[QuestionService] LLM raw response:", response)

        questions = extract_questions_from_llm(response)
        print("[QuestionService] Extracted questions:", questions)

        return questions