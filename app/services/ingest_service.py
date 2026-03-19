"""
app/services/ingest_service.py
Notion → chunk by heading → embed via Azure OpenAI → upsert into Milvus Lite.
"""

import os
import re
import time
import hashlib
import requests as http_requests

from app.rag_config import get_client, COLLECTION_NAME, TOP_K

# ── Embedding ────────────────────────────────────────────────────────────────
from app.services.embeddings import embed_texts  # noqa: E402

# ── Notion API config ────────────────────────────────────────────────────────
NOTION_API_KEY   = os.getenv("NOTION_API_KEY")
NOTION_DB_ID     = "31461ecb2bd28053910fe4d3ad65235b"   # your library DB
NOTION_VERSION   = "2022-06-28"
NOTION_BASE      = "https://api.notion.com/v1"

# ── Chunking config ──────────────────────────────────────────────────────────
MAX_TOKENS_PER_CHUNK = 400    # ~400 tokens ≈ 300 words
MIN_CHUNK_CHARS      = 80     # skip tiny sections


# ── Notion helpers ───────────────────────────────────────────────────────────

def _notion_headers() -> dict:
    return {
        "Authorization":  f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type":   "application/json",
    }


def fetch_all_library_pages() -> list[dict]:
    """
    Fetch all pages from the Notion library database.
    Returns list of dicts with id, title, industry, doc_type, version.
    """
    pages = []
    url   = f"{NOTION_BASE}/databases/{NOTION_DB_ID}/query"
    body  = {"page_size": 100}

    while True:
        resp = http_requests.post(url, headers=_notion_headers(), json=body)
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            props = page.get("properties", {})

            # Extract title
            title_arr = props.get("Name", {}).get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_arr).strip()

            # Extract text properties
            def _text(key):
                arr = props.get(key, {}).get("rich_text", [])
                return "".join(t.get("plain_text", "") for t in arr).strip()

            pages.append({
                "page_id":  page["id"],
                "title":    title,
                "industry": _text("industry"),
                "doc_type": _text("tags"),
                "version":  _text("version"),
            })

        if not data.get("has_more"):
            break
        body["start_cursor"] = data["next_cursor"]

    return pages


def fetch_page_blocks(page_id: str) -> list[dict]:
    """Fetch all blocks for a Notion page (handles pagination)."""
    blocks = []
    url    = f"{NOTION_BASE}/blocks/{page_id}/children"
    params = {"page_size": 100}

    while True:
        resp = http_requests.get(url, headers=_notion_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        blocks.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        params["start_cursor"] = data["next_cursor"]

    return blocks


def _block_text(block: dict) -> str:
    """Extract plain text from any block type."""
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich = content.get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in rich).strip()


def _is_heading(block: dict) -> tuple[bool, str]:
    """Returns (is_heading, heading_text)."""
    btype = block.get("type", "")
    if btype in ("heading_1", "heading_2", "heading_3"):
        return True, _block_text(block)
    return False, ""


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunk_page_blocks(blocks: list[dict]) -> list[dict]:
    """
    Split blocks into chunks by heading.
    Each chunk = one heading section.
    If a section is too long (>MAX_TOKENS_PER_CHUNK words), split by paragraph.
    Returns list of {heading, text, chunk_index}
    """
    chunks   = []
    current_heading = "Introduction"
    current_lines   = []

    def _flush(heading, lines, base_idx):
        text = "\n".join(lines).strip()
        if len(text) < MIN_CHUNK_CHARS:
            return base_idx

        # Rough token estimate: 1 token ≈ 0.75 words ≈ 4 chars
        if len(text) > MAX_TOKENS_PER_CHUNK * 4:
            # Split by paragraph
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) >= MIN_CHUNK_CHARS]
            for p in paragraphs:
                chunks.append({
                    "heading":     heading,
                    "text":        p,
                    "chunk_index": base_idx,
                })
                base_idx += 1
        else:
            chunks.append({
                "heading":     heading,
                "text":        text,
                "chunk_index": base_idx,
            })
            base_idx += 1

        return base_idx

    idx = 0
    for block in blocks:
        is_hdg, hdg_text = _is_heading(block)
        if is_hdg:
            idx = _flush(current_heading, current_lines, idx)
            current_heading = hdg_text
            current_lines   = []
        else:
            line = _block_text(block)
            if line:
                current_lines.append(line)

    # Flush last section
    _flush(current_heading, current_lines, idx)

    return chunks





# ── Upsert into Milvus ────────────────────────────────────────────────────────

def _make_chunk_id(page_id: str, chunk_index: int) -> str:
    """Stable, unique chunk ID."""
    raw = f"{page_id}:::{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()


def upsert_page_chunks(
    page_id:   str,
    title:     str,
    industry:  str,
    doc_type:  str,
    version:   str,
    chunks:    list[dict],
    embeddings: list[list[float]],
):
    """Upsert all chunks for a page into Milvus (overwrites existing)."""
    client = get_client()

    rows = []
    for chunk, emb in zip(chunks, embeddings):
        rows.append({
            "chunk_id":       _make_chunk_id(page_id, chunk["chunk_index"]),
            "embedding":      emb,
            "page_id":        page_id,
            "doc_title":      title[:512],
            "section_heading": chunk["heading"][:512],
            "doc_type":       doc_type[:256],
            "industry":       industry[:256],
            "version":        version[:32],
            "chunk_index":    chunk["chunk_index"],
            "raw_text":       chunk["text"][:4096],
        })

    if rows:
        client.upsert(collection_name=COLLECTION_NAME, data=rows)


def delete_page_chunks(page_id: str):
    """Delete all chunks for a given page_id (used when page deleted from Notion)."""
    client = get_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        filter=f'page_id == "{page_id}"',
    )


# ── Full ingest pipeline ──────────────────────────────────────────────────────

BATCH_SIZE = 20   # embed N chunks at a time to avoid rate limits

def ingest_all(force: bool = False) -> dict:
    """
    Full ingest: fetch all Notion pages → chunk → embed → upsert.
    Set force=True to re-ingest even unchanged pages.
    Returns summary dict.
    """
    print("[ingest] Starting full ingest…")
    pages   = fetch_all_library_pages()
    total_chunks = 0
    skipped      = 0

    for page in pages:
        pid      = page["page_id"]
        title    = page["title"]
        industry = page["industry"]
        doc_type = page["doc_type"]
        version  = page["version"]

        print(f"[ingest] Processing: {title}")

        try:
            blocks = fetch_page_blocks(pid)
            chunks = chunk_page_blocks(blocks)

            if not chunks:
                print(f"[ingest]   → no chunks, skipping")
                skipped += 1
                continue

            # Embed in batches
            all_embeddings = []
            texts = [c["text"] for c in chunks]

            for i in range(0, len(texts), BATCH_SIZE):
                batch     = texts[i : i + BATCH_SIZE]
                embeddings = embed_texts(batch)
                all_embeddings.extend(embeddings)
                time.sleep(0.2)   # small pause between batches

            # Upsert
            upsert_page_chunks(pid, title, industry, doc_type, version, chunks, all_embeddings)
            total_chunks += len(chunks)
            print(f"[ingest]   → {len(chunks)} chunks upserted")

        except Exception as e:
            print(f"[ingest]   → ERROR: {e}")
            continue

    print(f"[ingest] Done. {len(pages)} pages, {total_chunks} chunks, {skipped} skipped.")
    return {
        "pages_processed": len(pages),
        "chunks_upserted": total_chunks,
        "pages_skipped":   skipped,
    }


def ingest_single_page(page_id: str) -> dict:
    """Ingest or re-ingest a single page by ID."""
    pages = fetch_all_library_pages()
    page  = next((p for p in pages if p["page_id"] == page_id), None)
    if not page:
        raise ValueError(f"Page {page_id} not found in library")

    blocks = fetch_page_blocks(page_id)
    chunks = chunk_page_blocks(blocks)

    if not chunks:
        return {"chunks_upserted": 0}

    texts      = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)
    upsert_page_chunks(
        page_id, page["title"], page["industry"],
        page["doc_type"], page["version"],
        chunks, embeddings,
    )
    return {"chunks_upserted": len(chunks)}