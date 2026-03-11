import logging
import requests as http_requests
from fastapi import APIRouter, HTTPException

from app.routes.sessions import (
    NOTION_API_KEY, NOTION_DATABASE_ID,
    NOTION_VERSION, NOTION_BASE_URL,
    REQUEST_INTERVAL_SEC, _notion_request,
)

logger = logging.getLogger("docforge.notion_library")
router = APIRouter(prefix="/notion", tags=["Notion Library"])


@router.get("/library")
def get_notion_library():
    """Fetch all documents from the Notion liberary database."""

    # Query the Notion database — sorted by created time descending
    payload = {
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 50,
    }

    try:
        result = _notion_request(
            "POST",
            f"{NOTION_BASE_URL}/databases/{NOTION_DATABASE_ID}/query",
            payload,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Notion fetch failed: {str(e)}")

    docs = []
    for page in result.get("results", []):
        props = page.get("properties", {})

        def get_text(prop_name):
            prop = props.get(prop_name, {})
            ptype = prop.get("type")
            if ptype == "title":
                items = prop.get("title", [])
            elif ptype == "rich_text":
                items = prop.get("rich_text", [])
            else:
                return ""
            return "".join(t.get("plain_text", "") for t in items)

        docs.append({
            "title":        get_text("Name"),
            "industry":     get_text("industry"),
            "version":      get_text("version"),
            "tags":         get_text("tags"),
            "url":          page.get("url", ""),
            "created_time": page.get("created_time", ""),
            "page_id":      page.get("id", ""),
        })

    return {"docs": docs, "total": len(docs)}