import json

from app.services.llm_provider import LLMProvider


class SectionService:
    def __init__(self):
        self.llm = LLMProvider()

    async def generate_section(
        self,
        section_json: dict,
        qa_pairs: list[dict],          # [{"question": "...", "answer": "..."}, ...]
        generation_rules: dict,
        terminology_rules: dict,
    ) -> str:
        """
        Writes a document section using only the provided Q&A and metadata.
        Returns the raw section content string (markdown).
        """
        prompt = f"""You are an expert document writer. Your sole task is to write the document section described below, using ONLY the information provided. Do not invent or assume any facts not present in the Q&A or metadata.

SECTION METADATA:
{json.dumps(section_json, indent=2)}

USER Q&A (your only source of facts):
{json.dumps(qa_pairs, indent=2)}

GENERATION RULES:
{json.dumps(generation_rules, indent=2)}

TERMINOLOGY RULES:
{json.dumps(terminology_rules, indent=2)}

Instructions:
- Respect the min_words / max_words limits from the section metadata
- Match the tone and style specified in generation_rules
- Use required terminology from terminology_rules where relevant
- Do NOT use any forbidden terms
- Output ONLY the section content in markdown format
- Do NOT include the section title, labels, or any commentary — just the body text
"""
        content = await self.llm.generate(prompt)
        return content.strip()