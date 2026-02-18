import json
from app.services.llm_provider import LLMProvider


class SectionService:
    def __init__(self):
        self.llm = LLMProvider()

    async def generate_section(
        self,
        section_json: dict,
        qa_pairs: list,
        generation_rules: dict,
        terminology_rules: dict
    ) -> str:

        prompt = f"""
You are an expert document writer. Your sole task is to write the section below using ONLY the information provided — no assumptions, no invented details.

SECTION METADATA:
{json.dumps(section_json, indent=2)}

USER Q&A:
{json.dumps(qa_pairs, indent=2)}

GENERATION RULES:
{json.dumps(generation_rules, indent=2)}

TERMINOLOGY RULES:
{json.dumps(terminology_rules, indent=2)}

Write this section adhering strictly to:
- Word limits defined in generation_rules
- Tone, style, and formatting defined in generation_rules
- Required terminology from terminology_rules
- Content drawn exclusively from the Q&A and metadata above

Output ONLY the section content. No headings, labels, or commentary.
"""

        return await self.llm.generate(prompt)
