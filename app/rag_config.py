"""
app/rag_config.py
Milvus Lite setup — runs embedded, no Docker needed.
Data stored in ./milvus.db (gitignored).
Switch to full Milvus in prod by changing MILVUS_URI to "http://localhost:19530"
"""

from pymilvus import MilvusClient, DataType
import os

# ── Config ─────────────────────────────────────────────────────────────────
MILVUS_URI        = os.getenv("MILVUS_URI", "./milvus.db")
COLLECTION_NAME   = "docforge_chunks"
EMBEDDING_DIM     = 3072      # text-embedding-3-large output size

# How many chunks to return per query
TOP_K             = 5

# ── Singleton client ────────────────────────────────────────────────────────
_client: MilvusClient | None = None

def get_client() -> MilvusClient:
    global _client
    if _client is None:
        _client = MilvusClient(MILVUS_URI)
    return _client


# ── Collection setup ────────────────────────────────────────────────────────
def create_collection_if_not_exists():
    """
    Creates the docforge_chunks collection if it doesn't already exist.
    Safe to call on every startup.
    """
    client = get_client()

    if client.has_collection(COLLECTION_NAME):
        print(f"[rag_config] Collection '{COLLECTION_NAME}' already exists — skipping.")
        return

    # Define schema
    schema = MilvusClient.create_schema(
        auto_id=False,
        enable_dynamic_field=False,
    )

    # Fields
    schema.add_field(
        field_name="chunk_id",
        datatype=DataType.VARCHAR,
        max_length=256,
        is_primary=True,
    )
    schema.add_field(
        field_name="embedding",
        datatype=DataType.FLOAT_VECTOR,
        dim=EMBEDDING_DIM,
    )
    schema.add_field(
        field_name="page_id",
        datatype=DataType.VARCHAR,
        max_length=128,
    )
    schema.add_field(
        field_name="doc_title",
        datatype=DataType.VARCHAR,
        max_length=512,
    )
    schema.add_field(
        field_name="section_heading",
        datatype=DataType.VARCHAR,
        max_length=512,
    )
    schema.add_field(
        field_name="doc_type",        # from Notion "tags" field
        datatype=DataType.VARCHAR,
        max_length=256,
    )
    schema.add_field(
        field_name="industry",        # from Notion "industry" field
        datatype=DataType.VARCHAR,
        max_length=256,
    )
    schema.add_field(
        field_name="version",
        datatype=DataType.VARCHAR,
        max_length=32,
    )
    schema.add_field(
        field_name="chunk_index",     # position within the doc (0, 1, 2...)
        datatype=DataType.INT64,
    )
    schema.add_field(
        field_name="raw_text",
        datatype=DataType.VARCHAR,
        max_length=4096,
    )

    # Index on the vector field — HNSW is fast and accurate for this scale
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    # Create
    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )
    print(f"[rag_config] Collection '{COLLECTION_NAME}' created ✓")


def drop_collection():
    """Drop and recreate — useful during dev to reset everything."""
    client = get_client()
    if client.has_collection(COLLECTION_NAME):
        client.drop_collection(COLLECTION_NAME)
        print(f"[rag_config] Collection '{COLLECTION_NAME}' dropped.")


def collection_stats() -> dict:
    """Return basic stats — used by the status pills in the UI."""
    client = get_client()
    if not client.has_collection(COLLECTION_NAME):
        return {"exists": False, "count": 0}
    stats = client.get_collection_stats(COLLECTION_NAME)
    return {
        "exists": True,
        "count": int(stats.get("row_count", 0)),
    }


# ── Run once on import ──────────────────────────────────────────────────────
# Called from main.py startup so the collection is ready before any request.
if __name__ == "__main__":
    create_collection_if_not_exists()
    print("Stats:", collection_stats())