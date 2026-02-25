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

        company_context = generation_rules.pop("company_context", {})

        context_block = ""
        if company_context:
            context_block = f"""
COMPANY CONTEXT:
- Company: {company_context.get('company_name', '')}
- Product: {company_context.get('product_name', '')} — {company_context.get('product_description', '')}
- Industry: {company_context.get('industry_vertical', '')}
- Stage: {company_context.get('company_stage', '')}
- Target customer: {company_context.get('target_customer', '')}
- Key problem solved: {company_context.get('key_problem_solved', '')}
"""

        prompt = f"""You are an expert document writer. Write the section below using ONLY the information provided.

SECTION:
{json.dumps(section_json, indent=2)}
{context_block}
USER Q&A:
{json.dumps(qa_pairs, indent=2)}

GENERATION RULES:
{json.dumps(generation_rules, indent=2)}

TERMINOLOGY RULES:
{json.dumps(terminology_rules, indent=2)}

OUTPUT FORMAT RULES — STRICTLY FOLLOW:
1. Output in clean Markdown
2. Use **bold** for field labels and important terms
3. If the section contains structured data (compensation, fees, schedule, breakdown):
   - Use a proper Markdown table with headers and alignment
   - Example:
     | Component       | Amount      | Frequency |
     |-----------------|-------------|-----------|
     | Base Salary     | ₹X,XX,XXX   | Monthly   |
     | Annual Bonus    | ₹X,XX,XXX   | Yearly    |
4. Use bullet lists where items are enumerable
5. Do NOT use HTML tags
6. Do NOT add a heading — the section title is already shown above
7. Write ONLY the section content, nothing else

Write this section now:"""

        return await self.llm.generate(prompt)

    async def enhance_section(
        self,
        section_json: dict,
        current_content: str,
        enhance_prompt: str,
        company_context: dict,
        generation_rules: dict,
    ) -> str:
        context_block = ""
        if company_context:
            context_block = f"""
COMPANY CONTEXT:
- Company: {company_context.get('company_name', '')}
- Product: {company_context.get('product_name', '')} — {company_context.get('product_description', '')}
- Industry: {company_context.get('industry_vertical', '')}
- Stage: {company_context.get('company_stage', '')}
- Target customer: {company_context.get('target_customer', '')}
"""

        prompt = f"""You are an expert document writer enhancing an existing section based on a user's instruction.

SECTION METADATA:
{json.dumps(section_json, indent=2)}
{context_block}
CURRENT CONTENT:
{current_content}

GENERATION RULES:
{json.dumps(generation_rules, indent=2)}

USER ENHANCEMENT INSTRUCTION:
{enhance_prompt}

YOUR TASK:
- Rewrite and enhance the section following the user's instruction EXACTLY
- Maintain consistency with the company context and section purpose
- Keep all factual information already present unless instructed otherwise
- Return ONLY the improved section content — no titles, no commentary, no "Here is..."

OUTPUT FORMAT RULES — STRICTLY FOLLOW:
1. Output in clean Markdown
2. Use **bold** for field labels and important terms
3. If the section contains structured data, use a proper Markdown table
4. Use bullet lists where items are enumerable
5. Do NOT use HTML tags
6. Do NOT add a heading — section title is already shown above
7. Write ONLY the enhanced section content

Enhanced section:"""

        return await self.llm.generate(prompt)