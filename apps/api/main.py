"""
API Gateway for the Hierarchical Agent Coordination Framework.

- /api/v1/*   authenticated platform API (workflows, runs, approvals, registry, audit)
- /workflows/run   legacy unauthenticated endpoint, DISABLED unless HACFEW_ENABLE_LEGACY_API=1
"""
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from apps.api.routers import auth, registry, runs, workflows
from core.platform import config
from core.platform.db import init_platform_db, session_factory
from core.platform import engine as run_engine
from core.platform.security import seed_dev_users
from core.supervisor.orchestrator import SupervisorOrchestrator
from core.supervisor.schemas import WorkflowSynthesis

log = logging.getLogger("hacfew")


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.jwt_secret()  # fail fast if production is misconfigured
    init_platform_db()
    from mock_systems.db import init_db
    init_db()  # tables only; never reseeds or deletes existing mock data
    db = session_factory()()
    try:
        created = seed_dev_users(db)
        if created:
            log.warning("Development accounts created (%d). Password: HACFEW_DEV_PASSWORD (default 'hacfew-dev'). "
                        "Never use this in production.", created)
    finally:
        db.close()
    resumed = run_engine.recover_interrupted_runs()
    if resumed:
        log.warning("Recovered %d interrupted run(s) after restart.", resumed)
    yield


app = FastAPI(
    title="HAC-FEW Platform API",
    version="0.2.0",
    description="Governed multi-agent workflow platform: authenticated workflows, runs, approvals and audit.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

v1 = APIRouter(prefix="/api/v1")
for r in (auth.router, workflows.router, runs.router, registry.router):
    v1.include_router(r)
app.include_router(v1)


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "online", "gateway": "active"}


# ---------------------------------------------------------------- legacy endpoint
orchestrator = SupervisorOrchestrator()


class WorkflowRunRequest(BaseModel):
    user_id: str = Field(..., description="Requesting enterprise user ID")
    role: str = Field(default="employee", description="Client-asserted role (UNTRUSTED; legacy only)")
    request: str = Field(..., description="Natural language enterprise request")
    context: Dict[str, Any] = Field(default_factory=dict)


@app.post("/workflows/run", response_model=WorkflowSynthesis, tags=["Legacy"], deprecated=True)
def trigger_workflow(req: WorkflowRunRequest):
    """Legacy keyword-planner endpoint kept for the Streamlit console and existing tests.
    It trusts a client-supplied role, so it is off by default. Use /api/v1 instead."""
    if not config.legacy_api_enabled():
        raise HTTPException(status_code=410, detail="Legacy endpoint disabled. Use the authenticated /api/v1 API.")
    plan = orchestrator.plan_workflow(req.request)
    return orchestrator.execute_workflow(plan, user_role=req.role)
