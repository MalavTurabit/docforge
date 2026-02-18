from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage
from app.config import settings


class LLMProvider:
    def __init__(self):
        self.llm = AzureChatOpenAI(
            azure_endpoint=settings.AZURE_LLM_ENDPOINT,
            azure_deployment=settings.AZURE_LLM_DEPLOYMENT_41_MINI,
            api_key=settings.AZURE_OPENAI_LLM_KEY,
            api_version=settings.AZURE_LLM_API_VERSION,
            temperature=0.2,
        )

    async def generate(self, prompt: str) -> str:
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
