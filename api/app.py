"""
Loop Engineering FastAPI application.
Entry point for API layer — serves workflow interactions, approvals, and real-time updates.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from api.routes import router
from service import health as health_module


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    # ── Startup ──
    from service.otel_instrumentor import tracer
    tracer.configure()
    health_module.start_health_server()
    yield
    # ── Shutdown ──
    # Cleanup if needed


app = FastAPI(
    title="Loop Engineering API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="")


@app.get("/health")
async def health():
    return {"status": "ok"}


# Allow running as main
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port)
