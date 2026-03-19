"""
app/services/embeddings.py
Standalone embedding function — imported by both ingest_service and rag_service.
Kept separate to avoid circular imports.
"""
import os
from openai import AzureOpenAI

_emb_client: AzureOpenAI | None = None

def get_emb_client() -> AzureOpenAI:
    global _emb_client
    if _emb_client is None:
        _emb_client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_EMB_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_EMB_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_EMB_API_VERSION", "2024-02-01"),
        )
    return _emb_client

EMB_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT", "text-embedding-3-large")

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts via Azure OpenAI. Returns list of vectors."""
    resp = get_emb_client().embeddings.create(
        model=EMB_DEPLOYMENT,
        input=texts,
    )
    return [item.embedding for item in resp.data]