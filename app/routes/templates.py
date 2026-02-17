from fastapi import APIRouter, Depends, Query
from app.db import get_db

router = APIRouter(prefix="/templates", tags=["Templates"])


@router.get("/")
def get_templates(dept_id: str = Query(...)):
    db = get_db()

    templates = []
    cursor = db.document_templates.find({"dept_id": dept_id})

    for doc in cursor:
        templates.append({
            "label": doc.get("doc_name"),
            "id": doc["_id"]
        })

    return templates
