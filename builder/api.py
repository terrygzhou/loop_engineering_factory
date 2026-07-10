"""
FastAPI application for the Loop Factory Builder service.
"""
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from builder.state import BuildRequest, BuildStatus, BuildResponse
from builder.runner import BuildRunner

app = FastAPI(title="Loop Factory Builder")

# In-memory build registry: build_id → {status, progress, artifacts, errors, cancelled, runner}
builds: dict = {}


@app.post("/api/build", response_model=BuildResponse)
async def submit_build(req: BuildRequest):
    """Submit a build request. Returns 202-accepted; build runs in background."""
    if req.build_id in builds:
        raise HTTPException(status_code=409, detail="Build already exists")

    builds[req.build_id] = {
        "status": "running",
        "sub_phase": "queued",
        "progress": [],
        "artifacts": {},
        "errors": [],
        "completed_at": None,
        "cancelled": False,
        "request": req,
    }

    asyncio.create_task(execute_build(req.build_id, req))
    return BuildResponse(build_id=req.build_id, status="accepted")


@app.get("/api/build/{build_id}")
async def get_status(build_id: str) -> BuildStatus:
    """Poll build status."""
    if build_id not in builds:
        raise HTTPException(status_code=404, detail="Build not found")

    entry = builds[build_id]
    return BuildStatus(
        build_id=build_id,
        status=entry["status"],
        sub_phase=entry.get("sub_phase", "unknown"),
        progress=entry.get("progress", []),
        artifacts=entry.get("artifacts", {}),
        errors=entry.get("errors", []),
        completed_at=entry.get("completed_at"),
    )


@app.post("/api/build/{build_id}/cancel")
async def cancel_build(build_id: str) -> dict:
    """Cancel a running build."""
    if build_id not in builds:
        raise HTTPException(status_code=404, detail="Build not found")

    entry = builds[build_id]
    if entry["status"] in ("pass", "fail", "partial"):
        return {"build_id": build_id, "status": entry["status"], "message": "Build already completed"}

    entry["cancelled"] = True
    entry["status"] = "partial"
    return {"build_id": build_id, "status": "cancelling"}


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


async def execute_build(build_id: str, request: BuildRequest):
    """Run the full build pipeline in a background task."""
    entry = builds[build_id]
    try:
        runner = BuildRunner(request)
        entry["runner"] = runner

        # Run build synchronously in executor (blocking in the background task)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, runner.run_build)

        # Update entry with final result
        if entry.get("cancelled"):
            result["status"] = "partial"

        entry["status"] = result["status"]
        entry["sub_phase"] = result.get("sub_phase", "COMPLETE")
        entry["progress"] = result.get("progress", [])
        entry["artifacts"] = result.get("artifacts", {})
        entry["errors"] = result.get("errors", [])
        entry["completed_at"] = result.get("completed_at")

    except Exception as e:
        entry["status"] = "fail"
        entry["sub_phase"] = "error"
        entry["errors"].append(f"Build execution failed: {e}")
        entry["completed_at"] = datetime.now(timezone.utc).isoformat()