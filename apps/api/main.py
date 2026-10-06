"""
API Gateway for Hierarchical Agent Coordination Framework.
Handles:
- Authentication & RBAC token decoding
- Incoming workflow requests
- Routing to LangGraph Supervisor
- Streaming execution trace & human-in-the-loop approvals
"""
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import uuid

app = FastAPI(
    title="Hierarchical Agent Coordination Framework API Gateway",
    version="0.1.0",
    description="Enterprise API Gateway orchestrating Supervisor & Department Agents"
)

from core.supervisor.orchestrator import SupervisorOrchestrator
from core.supervisor.schemas import WorkflowSynthesis

orchestrator = SupervisorOrchestrator()


class WorkflowRunRequest(BaseModel):
    user_id: str = Field(..., description="Requesting enterprise user ID")
    role: str = Field(default="employee", description="Role: employee, manager, admin, hr_rep, it_admin")
    request: str = Field(..., description="Natural language enterprise request")
    context: Dict[str, Any] = Field(default_factory=dict, description="Metadata or parameters")


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "online", "gateway": "active"}


@app.post("/workflows/run", response_model=WorkflowSynthesis, tags=["Workflows"])
def trigger_workflow(req: WorkflowRunRequest):
    plan = orchestrator.plan_workflow(req.request)
    result = orchestrator.execute_workflow(plan, user_role=req.role)
    return result
