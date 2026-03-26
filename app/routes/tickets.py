"""
app/routes/tickets.py

POST /tickets/create  — manually create a ticket
GET  /tickets         — fetch all tickets from Notion CiteRAG Tickets DB
"""

import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import requests as http_requests
from dotenv import load_dotenv

from app.tools.create_ticket import create_ticket

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["Tickets"])

NOTION_API_KEY      = os.getenv("NOTION_API_KEY", "")
NOTION_TICKET_DB_ID = os.getenv("NOTION_TICKET_DB_ID", "")
NOTION_VERSION      = "2022-06-28"
NOTION_BASE         = "https://api.notion.com/v1"


def _notion_headers() -> dict:
    return {
        "Authorization":  f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type":   "application/json",
    }


# ── Request / Response models ─────────────────────────────────────────────────

class TicketCreateRequest(BaseModel):
    question:           str
    industry:           Optional[str] = ""
    doc_type:           Optional[str] = ""
    retrieved_attempts: Optional[int] = 0
    session_summary:    Optional[str] = ""


class TicketCreateResponse(BaseModel):
    ticket_id:     str
    status:        str        # "created" | "exists"
    priority:      Optional[str] = None


class TicketOut(BaseModel):
    ticket_id:          str   # Notion page ID
    title:              str   # TKT-XXXXXXXX
    question:           str
    status:             str
    priority:           str
    industry:           str
    doc_type:           str
    retrieved_attempts: str
    session_summary:    str
    created_at:         Optional[str] = None
    notion_url:         Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create", response_model=TicketCreateResponse)
def create_ticket_endpoint(req: TicketCreateRequest):
    """
    Manually create a support ticket in the CiteRAG Tickets Notion DB.
    Idempotent — returns existing ticket ID if same question already exists.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        result = create_ticket.invoke({
            "question":           req.question,
            "industry":           req.industry or "",
            "doc_type":           req.doc_type or "",
            "retrieved_attempts": req.retrieved_attempts or 0,
            "session_summary":    req.session_summary or "",
        })
        return TicketCreateResponse(
            ticket_id = result["ticket_id"],
            status    = result["status"],
            priority  = result.get("priority"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ticket creation failed: {str(e)}")


class TicketUpdateRequest(BaseModel):
    priority: Optional[str] = None   # High, Medium, Low
    status:   Optional[str] = None   # Open, In Progress, Resolved


@router.patch("/{ticket_id}", response_model=TicketCreateResponse)
def update_ticket(ticket_id: str, req: TicketUpdateRequest):
    """
    Update priority and/or status of an existing ticket.
    """
    if not NOTION_API_KEY:
        raise HTTPException(status_code=500, detail="Notion credentials not configured")

    properties = {}
    if req.priority and req.priority in ("High", "Medium", "Low"):
        properties["Priority"] = {"select": {"name": req.priority}}
    if req.status and req.status in ("Open", "In Progress", "Resolved"):
        properties["Status"] = {"select": {"name": req.status}}

    if not properties:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    try:
        resp = http_requests.patch(
            f"{NOTION_BASE}/pages/{ticket_id}",
            headers=_notion_headers(),
            json={"properties": properties},
        )
        resp.raise_for_status()
        return TicketCreateResponse(
            ticket_id=ticket_id,
            status="updated",
            priority=req.priority,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ticket update failed: {str(e)}")
def get_tickets(status: Optional[str] = None):
    """
    Fetch all tickets from the CiteRAG Tickets Notion DB.
    Optional ?status=Open|In Progress|Resolved filter.
    Used by the My Tickets tab in the Streamlit UI.
    """
    if not NOTION_API_KEY or not NOTION_TICKET_DB_ID:
        raise HTTPException(status_code=500, detail="Notion credentials not configured")

    url  = f"{NOTION_BASE}/databases/{NOTION_TICKET_DB_ID}/query"
    body = {"page_size": 100, "sorts": [{"timestamp": "created_time", "direction": "descending"}]}

    # Optional status filter
    if status and status in ("Open", "In Progress", "Resolved"):
        body["filter"] = {
            "property": "Status",
            "select":   {"equals": status}
        }

    try:
        tickets = []
        while True:
            resp = http_requests.post(url, headers=_notion_headers(), json=body)
            resp.raise_for_status()
            data = resp.json()

            for page in data.get("results", []):
                props = page.get("properties", {})

                def _rich(key):
                    arr = props.get(key, {}).get("rich_text", [])
                    return "".join(t.get("plain_text", "") for t in arr).strip()

                def _select(key):
                    sel = props.get(key, {}).get("select")
                    return sel.get("name", "") if sel else ""

                def _title(key):
                    arr = props.get(key, {}).get("title", [])
                    return "".join(t.get("plain_text", "") for t in arr).strip()

                def _date(key):
                    d = props.get(key, {}).get("date")
                    return d.get("start", "") if d else ""

                tickets.append(TicketOut(
                    ticket_id          = page["id"],
                    title              = _title("Ticket ID"),
                    question           = _rich("Question"),
                    status             = _select("Status"),
                    priority           = _select("Priority"),
                    industry           = _rich("Industry"),
                    doc_type           = _rich("Doc Type"),
                    retrieved_attempts = _rich("Retrieved Attempts"),
                    session_summary    = _rich("Session Summary"),
                    created_at         = _date("Created At"),
                    notion_url         = page.get("url"),
                ))

            if not data.get("has_more"):
                break
            body["start_cursor"] = data["next_cursor"]

        logger.info(f"[GET /tickets] Returned {len(tickets)} tickets (status_filter={status})")
        return tickets

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch tickets: {str(e)}")