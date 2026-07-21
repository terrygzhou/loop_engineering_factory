"""
Loop Engineering — FastAPI Routes

API endpoints for workflow interaction, approval, input, and real-time updates.
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from api.services import WorkflowService
from api.schemas.workflow import WorkflowStartRequest, WorkflowStatusResponse
from api.schemas.approval import ApprovalRequest, ApprovalResponse
from api.middleware.logging import log_request

router = APIRouter()
workflow_service = WorkflowService()


@router.post("/workflow/start", response_model=WorkflowStatusResponse)
async def start_workflow(req: WorkflowStartRequest):
    """Start a new workflow with project configuration."""
    log_request("POST /workflow/start", workflow_id=req.project_name)
    try:
        state = await workflow_service.start(req.project_name, req.spec_text, req.context_folder)
        return WorkflowStatusResponse.from_state(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workflow/status", response_model=WorkflowStatusResponse)
async def get_status(workflow_id: str = ""):
    """Get current workflow status."""
    state = workflow_service.get_status(workflow_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowStatusResponse.from_state(state)


@router.post("/workflow/approval", response_model=ApprovalResponse)
async def submit_approval(req: ApprovalRequest):
    """Submit human approval/rejection with feedback."""
    log_request("POST /workflow/approval", workflow_id=req.workflow_id, approved=req.approved)
    result = workflow_service.submit_approval(req.workflow_id, req.approved, req.feedback or "", req.section_feedback or {})
    return ApprovalResponse.from_result(result)


@router.post("/workflow/input")
async def submit_input(req: ApprovalRequest):
    """Submit user input for pending requests (interview, review, etc.)."""
    log_request("POST /workflow/input", workflow_id=req.workflow_id)
    result = workflow_service.submit_input(req.workflow_id, req.input_data or {})
    return ApprovalResponse.from_result(result)


@router.get("/workflow/input/pending")
async def get_pending_inputs(workflow_id: str = ""):
    """Get list of pending input requests."""
    inputs = workflow_service.get_pending_inputs(workflow_id)
    return {"pending_inputs": inputs}


@router.post("/workflow/cancel")
async def cancel_workflow(workflow_id: str = ""):
    """Cancel an active workflow."""
    success = workflow_service.cancel(workflow_id)
    return {"status": "cancelled" if success else "not_found"}


@router.websocket("/ws/{workflow_id}")
async def websocket_endpoint(websocket: WebSocket, workflow_id: str):
    """WebSocket for real-time workflow updates and input collection."""
    await websocket.accept()
    await workflow_service.register_websocket(workflow_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages (input submission, commands)
            workflow_service.handle_websocket_message(workflow_id, data)
    except WebSocketDisconnect:
        await workflow_service.unregister_websocket(workflow_id)


@router.get("/workflow/diagrams")
async def get_diagrams(workflow_id: str = ""):
    """Get architecture diagrams for a workflow."""
    diagrams = workflow_service.get_diagrams(workflow_id)
    if not diagrams:
        raise HTTPException(status_code=404, detail="No diagrams generated yet")
    return {"diagrams": diagrams}


@router.post("/workflow/diagrams/review", response_model=ApprovalResponse)
async def review_diagrams(req: ApprovalRequest):
    """Submit architecture diagram review approval/rejection."""
    log_request("POST /workflow/diagrams/review", workflow_id=req.workflow_id, approved=req.approved)
    result = workflow_service.submit_diagram_review(req.workflow_id, req.approved, req.feedback or "")
    return ApprovalResponse.from_result(result)