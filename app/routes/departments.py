from fastapi import APIRouter
from app.db import get_db

router = APIRouter(prefix="/departments", tags=["Departments"])

@router.get("/")
def get_departments():
    db = get_db()
    
    departments = []
    cursor = db.Departments.find({})

    for dept in cursor:
        departments.append({
            "dept_id": dept["_id"],
            "dept_name": dept.get("name")
        })

    return departments
