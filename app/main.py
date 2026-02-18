from fastapi import FastAPI
from app.routes.departments import router as dept_router
from app.routes.templates import router as templates_router
from app.routes.sessions import router as sessions_router
from app.routes.session_routes import router as session_router



app = FastAPI(title="DocForge")

app.include_router(dept_router)
app.include_router(templates_router)
app.include_router(sessions_router)
app.include_router(session_router)

@app.get("/")
def health():
    return {"status": "running"}
