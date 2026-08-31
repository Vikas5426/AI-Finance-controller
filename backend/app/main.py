import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.responses import Response

from app.core.config import settings
from app.core.redis import redis_manager
from app.db.database import init_db
from app.api.v1 import auth, sources, batches, transactions, exceptions, approvals, qa, audit, reports, agents


class RevalidatingStaticFiles(StaticFiles):
    """
    Serves static assets with mandatory revalidation.

    The frontend has no build step and therefore no content-hashed filenames.
    With no Cache-Control header, browsers apply heuristic freshness and will
    keep running a cached app.js for hours after a deploy — which means a
    shipped bug fix (or a credential removal) silently never reaches the user.
    ``no-cache`` still allows a cheap 304 via ETag/Last-Modified; it only
    forbids using the cached copy without asking first.
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan managing database seeding and optional Redis connectivity."""
    # 1. Initialize SQLite / PostgreSQL schemas and seed default controller data
    init_db()

    # 2. Attempt Redis connection (100% fail-open if Redis is disabled or unreachable)
    await redis_manager.connect()

    yield

    # 3. Graceful shutdown
    await redis_manager.disconnect()

app = FastAPI(
    title="AI Financial Controller API",
    description="Three-Way Settlement Reconciliation Engine with Bounded AI Investigator & Cryptographic Audit",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration (Issue 2.21: Standard-compliant credentials handling)
cors_kwargs = {
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
if "*" in settings.CORS_ORIGINS:
    cors_kwargs["allow_origin_regex"] = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
else:
    cors_kwargs["allow_origins"] = settings.CORS_ORIGINS

app.add_middleware(CORSMiddleware, **cors_kwargs)

# Include API v1 Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(sources.router, prefix=settings.API_V1_STR)
app.include_router(batches.router, prefix=settings.API_V1_STR)
app.include_router(transactions.router, prefix=settings.API_V1_STR)
app.include_router(exceptions.router, prefix=settings.API_V1_STR)
app.include_router(approvals.router, prefix=settings.API_V1_STR)
app.include_router(qa.router, prefix=settings.API_V1_STR)
app.include_router(audit.router, prefix=settings.API_V1_STR)
app.include_router(reports.router, prefix=settings.API_V1_STR)
app.include_router(agents.router, prefix=settings.API_V1_STR)

# Mount Frontend static directory dynamically
candidates = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend")),
    "/app/frontend",
    os.path.abspath("frontend"),
    os.path.join(os.getcwd(), "frontend")
]
frontend_dir = next((c for c in candidates if os.path.exists(os.path.join(c, "index.html")) or os.path.exists(os.path.join(c, "dist", "index.html"))), None)

if frontend_dir:
    dist_dir = os.path.join(frontend_dir, "dist")
    static_dir = os.path.join(frontend_dir, "static")

    if os.path.exists(static_dir):
        app.mount(
            "/static",
            RevalidatingStaticFiles(directory=static_dir),
            name="static",
        )

    if os.path.exists(os.path.join(dist_dir, "assets")):
        app.mount(
            "/assets",
            RevalidatingStaticFiles(directory=os.path.join(dist_dir, "assets")),
            name="assets",
        )

    @app.get("/")
    def serve_frontend_index():
        target_html = (
            os.path.join(dist_dir, "index.html")
            if os.path.exists(os.path.join(dist_dir, "index.html"))
            else os.path.join(frontend_dir, "index.html")
        )
        return FileResponse(
            target_html,
            headers={"Cache-Control": "no-store"},
        )


@app.get("/health")
@app.get("/api/v1/health")
def health_check():
    return {
        "status": "HEALTHY",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "redis_connected": redis_manager.is_connected
    }
