"""
app/tools/create_ticket.py

LangChain @tool — creates a ticket in the CiteRAG Tickets Notion database.

Behaviour:
- Idempotency: same question → returns existing ticket ID silently
- LLM auto-assigns Priority (High / Medium / Low)
- Writes 7 fields: Ticket ID, Question, Status, Priority, Industry,
  Retrieved Attempts, Session Summary
  (Created At is auto-set by Notion as created_time — do NOT pass it)
- Returns ticket_id, status, priority, notion_url
"""

import os
import uuid
import logging
from dotenv import load_dotenv

import requests as http_requests
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI

load_dotenv()

logger = logging.getLogger(__name__)

# ── Notion config ──────────────────────────────────────────────────────────────
NOTION_API_KEY      = os.getenv("NOTION_API_KEY", "")
NOTION_TICKET_DB_ID = os.getenv("NOTION_TICKET_DB_ID", "")
NOTION_VERSION      = "2022-06-28"
NOTION_BASE         = "https://api.notion.com/v1"

VALID_PRIORITIES = {"High", "Medium", "Low"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _notion_headers() -> dict:
    return {
        "Authorization":  f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type":   "application/json",
    }


def _llm_assign_priority(question: str) -> str:
    """Use LLM to assign ticket priority. Falls back to Medium on failure."""
    try:
        llm = AzureChatOpenAI(
            azure_endpoint   = os.getenv("AZURE_LLM_ENDPOINT", ""),
            azure_deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI", ""),
            api_key          = os.getenv("AZURE_OPENAI_LLM_KEY", ""),
            api_version      = os.getenv("AZURE_LLM_API_VERSION", ""),
            temperature      = 0,
        )
        prompt = (
            "You are a compliance helpdesk triage assistant.\n"
            "Assign a priority to this unanswered compliance/policy question.\n\n"
            "Rules:\n"
            "- High: urgent regulatory, legal risk, safety, or blocking issue\n"
            "- Medium: standard policy clarification or multi-step question\n"
            "- Low: general info request, minor clarification, simple lookup\n\n"
            f"Question: {question}\n\n"
            "Respond with exactly one word — High, Medium, or Low."
        )
        response = llm.invoke(prompt)
        priority = response.content.strip()
        if priority in VALID_PRIORITIES:
            return priority
        logger.warning(f"[create_ticket] Unexpected priority '{priority}' — defaulting to Medium")
        return "Medium"
    except Exception as e:
        logger.warning(f"[create_ticket] Priority LLM failed: {e} — defaulting to Medium")
        return "Medium"


def _find_existing_ticket(question: str) -> tuple[str | None, str | None, str | None]:
    """
    Check for existing ticket covering the same topic.
    First tries exact match, then semantic similarity via LLM.
    Returns (page_id, matched_question, notion_url) or (None, None, None).
    """
    url  = f"{NOTION_BASE}/databases/{NOTION_TICKET_DB_ID}/query"
    body = {"page_size": 50}

    try:
        resp = http_requests.post(url, headers=_notion_headers(), json=body)
        resp.raise_for_status()
        results = resp.json().get("results", [])

        if not results:
            return None, None, None

        # Extract existing questions + URLs
        existing = []
        for page in results:
            props = page.get("properties", {})
            arr   = props.get("Question", {}).get("rich_text", [])
            q     = "".join(t.get("plain_text", "") for t in arr).strip()
            if q:
                existing.append({
                    "id":         page["id"],
                    "question":   q,
                    "notion_url": page.get("url", f"https://notion.so/{page['id'].replace('-', '')}"),
                })

        # Step 1 — exact match
        for e in existing:
            if e["question"].lower() == question.lower():
                return e["id"], e["question"], e["notion_url"]

        # Step 2 — semantic match via LLM — only match if VERY similar topic
        try:
            llm = AzureChatOpenAI(
                azure_endpoint   = os.getenv("AZURE_LLM_ENDPOINT", ""),
                azure_deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI", ""),
                api_key          = os.getenv("AZURE_OPENAI_LLM_KEY", ""),
                api_version      = os.getenv("AZURE_LLM_API_VERSION", ""),
                temperature      = 0,
            )
            existing_list = "\n".join(
                f"{i+1}. {e['question']}" for i, e in enumerate(existing)
            )
            prompt = (
                f"New question: \"{question}\"\n\n"
                f"Existing tickets:\n{existing_list}\n\n"
                f"Does any existing ticket cover the EXACT SAME specific question as the new one?\n"
                f"Be STRICT — only match if they are asking about the identical topic with the same intent.\n"
                f"Do NOT match if they are about the same general subject but asking different things.\n"
                f"Examples of matches: 'what is overtime pay?' vs 'how much is overtime compensation?'\n"
                f"Examples of non-matches: 'who is Rohit Mehra?' vs 'what job title was offered to him?'\n\n"
                f"Reply with just the NUMBER of the matching ticket, or 0 if none match closely enough."
            )
            response = llm.invoke(prompt)
            num = response.content.strip()
            if num.isdigit():
                idx = int(num) - 1
                if 0 <= idx < len(existing):
                    e = existing[idx]
                    return e["id"], e["question"], e["notion_url"]
        except Exception as e:
            logger.warning(f"[create_ticket] Semantic duplicate check failed: {e}")

    except Exception as e:
        logger.warning(f"[create_ticket] Idempotency check failed: {e}")

    return None, None, None


# ── @tool ──────────────────────────────────────────────────────────────────────

@tool
def create_ticket(
    question: str,
    industry: str = "",
    retrieved_attempts: int = 0,
    session_summary: str = "",
) -> dict:
    """
    Create a support ticket in the CiteRAG Tickets Notion database
    when the RAG system cannot answer a question.

    Args:
        question:            The unanswered user question.
        industry:            Industry filter active when question was asked.
        retrieved_attempts:  Number of retrieval attempts made before failing.
        session_summary:     Brief summary of the conversation context.

    Returns:
        dict with keys:
            ticket_id   — Notion page ID
            status      — "created" or "exists"
            priority    — assigned priority value
            notion_url  — direct Notion URL for the ticket
    """
    if not NOTION_API_KEY:
        raise EnvironmentError("[create_ticket] NOTION_API_KEY is not set.")
    if not NOTION_TICKET_DB_ID:
        raise EnvironmentError("[create_ticket] NOTION_TICKET_DB_ID is not set.")

    # ── Idempotency — exact + semantic duplicate check ────────────────────────
    existing_id, matched_q, existing_url = _find_existing_ticket(question)
    if existing_id:
        notion_url = existing_url or f"https://notion.so/{existing_id.replace('-', '')}"
        logger.info(f"[create_ticket] Duplicate found (matched: '{matched_q[:60] if matched_q else ''}') — returning existing {existing_id}")
        return {
            "ticket_id":        existing_id,
            "status":           "exists",
            "priority":         None,
            "notion_url":       notion_url,
            "matched_question": matched_q,
        }

    # ── Priority ──────────────────────────────────────────────────────────────
    priority  = _llm_assign_priority(question)
    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"

    # ── Payload ───────────────────────────────────────────────────────────────
    # Only fields confirmed to exist in the Notion DB:
    # Ticket ID (title), Question, Status, Priority,
    # Industry, Retrieved Attempts, Session Summary
    # Created At is created_time — auto-set by Notion, do NOT pass it
    payload = {
        "parent": {"database_id": NOTION_TICKET_DB_ID},
        "properties": {
            "Ticket ID": {
                "title": [{"text": {"content": ticket_id}}]
            },
            "Question": {
                "rich_text": [{"text": {"content": question[:2000]}}]
            },
            "Status": {
                "select": {"name": "Open"}
            },
            "Priority": {
                "select": {"name": priority}
            },
            "Industry": {
                "rich_text": [{"text": {"content": industry[:500] if industry else ""}}]
            },
            "Retrieved Attempts": {
                "rich_text": [{"text": {"content": str(retrieved_attempts)}}]
            },
            "Session Summary": {
                "rich_text": [{"text": {"content": session_summary[:2000] if session_summary else ""}}]
            },
        }
    }

    # ── Write to Notion ───────────────────────────────────────────────────────
    resp = http_requests.post(
        f"{NOTION_BASE}/pages",
        headers=_notion_headers(),
        json=payload,
    )

    if resp.status_code not in (200, 201):
        logger.error(f"[create_ticket] Notion error {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    page       = resp.json()
    page_id    = page["id"]
    notion_url = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")

    logger.info(f"[create_ticket] Created {ticket_id} → {page_id} | Priority: {priority}")

    return {
        "ticket_id":    page_id,
        "ticket_title": ticket_id,   # TKT-XXXXXXXX — human readable
        "status":       "created",
        "priority":     priority,
        "notion_url":   notion_url,
    }