import logging
import traceback

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routes.departments import router as dept_router
from app.routes.templates import router as templates_router
from app.routes.sessions import router as sessions_router
from app.routes.cache_routes import router as cache_router
from app.routes.notion_library import router as notion_library_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("docforge")

app = FastAPI(title="DocForge")

app.include_router(dept_router)
app.include_router(templates_router)
app.include_router(sessions_router)
app.include_router(cache_router)
app.include_router(notion_library_router)

# ── 422 Wrong request body / missing fields ──────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    try:
        errors = exc.errors()
        logger.warning("Validation error | %s %s | %s", request.method, request.url.path, errors)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error":  "Validation Error",
                "detail": errors,
                "hint":   "Check your request body — a required field may be missing or wrong type.",
            },
        )
    except Exception as e:
        logger.error("Error in validation handler: %s", str(e))
        return JSONResponse(status_code=422, content={"error": str(exc)})


# ── 4xx / 5xx HTTP errors raised by your routes ──────────────
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    try:
        logger.error("HTTP %s | %s %s | %s", exc.status_code, request.method, request.url.path, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error":  f"HTTP {exc.status_code}",
                "detail": exc.detail,
            },
        )
    except Exception as e:
        logger.error("Error in HTTP handler: %s", str(e))
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


# ── Completely unhandled / unexpected exceptions ──────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    try:
        tb = traceback.format_exc()
        logger.error("Unhandled exception | %s %s\n%s", request.method, request.url.path, tb)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error":     "Internal Server Error",
                "type":      type(exc).__name__,
                "detail":    str(exc),
                "traceback": tb.splitlines()[-5:],
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Fatal error", "detail": str(e)},
        )


# ── Health check ─────────────────────────────────────────────
@app.get("/")
def health():
    try:
        return {"status": "running"}
    except Exception as e:
        logger.error("Health check failed: %s", str(e))
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})
    