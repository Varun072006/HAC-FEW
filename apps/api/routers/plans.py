"""Structured planning: create and validate a plan, then execute it as a run."""
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from apps.api import schemas as s
from apps.api.serializers import run_summary, usage_out
from core.platform import agent_registry, audit, engine
from core.platform import planner as pl
from core.platform.db import get_session
from core.platform.events import emit
from core.platform.gateway import Usage
from core.platform.models import Plan, User, Workflow
from core.platform.security import permissions_for, require
from core.platform.validation import trigger_fields

router = APIRouter(tags=["Plans"])


def _plan_out(p: Plan) -> s.PlanOut:
    definition = None
    try:
        definition = s.WorkflowDefinition(**pl.plan_to_definition(pl.Plan.model_validate(p.plan)))
    except ValidationError:
        pass
    issues = [s.ValidationIssue(**i) for i in p.issues]
    return s.PlanOut(id=p.id, objective=p.objective, status=p.status, planner=p.planner, plan=p.plan, issues=issues,
                     valid=not any(i.severity == "error" for i in issues), failure_category=pl.failure_category(p.issues),
                     usage=usage_out(p.usage), definition=definition,
                     trigger_fields=trigger_fields(definition.model_dump()) if definition else [],
                     created_by=p.created_by, created_at=p.created_at, run_id=p.run_id,
                     note=(p.usage or {}).get("note"))


def _visible(db: Session, plan_id: str, user: User) -> Plan:
    p = db.get(Plan, plan_id)
    if p is None or (p.created_by != user.id and "run:read_all" not in permissions_for(user.role)):
        raise HTTPException(404, "Plan not found.")
    return p


@router.post("/plans", response_model=s.PlanOut, status_code=201)
def create_plan(body: s.PlanCreate, db: Session = Depends(get_session), user: User = Depends(require("workflow:run"))):
    note, usage, planner, issues, plan_dict = None, Usage(), body.mode, [], {}
    t0 = time.perf_counter()
    supervisor = agent_registry.get_agent(db, "supervisor")
    sup_cfg = supervisor["config"] if supervisor and supervisor["status"] == "active" else None
    plan: Optional[pl.Plan] = None
    try:
        if body.mode == "structured":
            if body.plan is None:
                raise HTTPException(422, "mode 'structured' needs a plan.")
            plan = pl.Plan.model_validate(body.plan)
        else:
            use_llm = body.mode == "llm" or (body.mode == "auto" and sup_cfg and sup_cfg["model"]["provider"] != "deterministic")
            if use_llm:
                if not sup_cfg or sup_cfg["model"]["provider"] == "deterministic":
                    raise HTTPException(422, "The supervisor has no model configured; use mode 'deterministic' or 'structured'.")
                planner = "llm"
                try:
                    plan, issues, usage = pl.llm_plan(db, body.objective, sup_cfg, user.role)
                except pl.PlanningFailure as exc:
                    if body.mode == "auto" and any(i["code"] == "PROVIDER_ERROR" for i in exc.issues):
                        note = f"Model planner unavailable ({exc}); fell back to the deterministic planner."
                        planner, plan = "deterministic", pl.deterministic_plan(body.objective)
                    else:
                        raise
            else:
                planner, plan = "deterministic", pl.deterministic_plan(body.objective)
    except ValidationError as exc:
        issues = [{"severity": "error", "code": "MALFORMED_PLAN", "category": "planning_failure", "node_id": None,
                   "message": f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"} for e in exc.errors()[:20]]
        plan_dict = body.plan or {}
    except pl.PlanningFailure as exc:
        issues = exc.issues or [{"severity": "error", "code": "PLANNING_FAILED", "category": "planning_failure",
                                 "node_id": None, "message": str(exc)}]
        plan_dict = {"objective": body.objective, "inputs": [], "tasks": []}
    if plan is not None:
        plan_dict = plan.model_dump(mode="json")
        issues = pl.validate_plan(db, plan, user.role)
    ud = usage.to_dict()
    ud["note"], ud["planning_ms"] = note, int((time.perf_counter() - t0) * 1000)
    status = "invalid" if pl.has_errors(issues) or plan is None else "draft"
    row = Plan(id=f"plan_{uuid.uuid4().hex[:12]}", objective=body.objective, status=status, planner=planner,
               plan=plan_dict, issues=issues, usage=ud, created_by=user.id)
    db.add(row)
    db.commit()
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="plan.created",
                 outcome="success" if status == "draft" else "denied", resource_type="plan", resource_id=row.id,
                 detail={"planner": planner, "errors": sum(1 for i in issues if i["severity"] == "error"),
                         "category": pl.failure_category(issues)})
    return _plan_out(row)


@router.get("/plans/{plan_id}", response_model=s.PlanOut)
def get_plan(plan_id: str, db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    return _plan_out(_visible(db, plan_id, user))


@router.post("/plans/{plan_id}/execute", response_model=s.RunSummary, status_code=202)
def execute_plan(plan_id: str, body: s.PlanExecuteIn, db: Session = Depends(get_session),
                 user: User = Depends(require("workflow:run"))):
    p = _visible(db, plan_id, user)
    if p.status == "executed":
        raise HTTPException(409, "This plan was already executed. Create a new plan to run it again.")
    # Re-validate now: the registry, agent states or the user's role may have changed since planning.
    plan = pl.Plan.model_validate(p.plan)
    issues = pl.validate_plan(db, plan, user.role)
    if pl.has_errors(issues):
        raise HTTPException(422, detail={"message": "Plan failed validation at execution time.", "issues": issues,
                                         "failure_category": pl.failure_category(issues)})
    wf = Workflow(id=f"wf_{uuid.uuid4().hex[:10]}", name=f"Plan: {p.objective[:60]}", description=p.objective,
                  definition=pl.plan_to_definition(plan), template_id="plan", created_by=user.id)
    db.add(wf)
    db.commit()
    try:
        run = engine.create_run(db, wf, body.inputs, user, objective=p.objective, plan_id=p.id,
                                constraints=plan.constraints.model_dump())
    except engine.RunRejected as exc:
        raise HTTPException(422, detail={"message": str(exc), "issues": exc.issues})
    emit(db, run.id, "plan.started", data={"plan_id": p.id, "planner": p.planner, "objective": p.objective})
    emit(db, run.id, "plan.completed", data={"plan_id": p.id, "planner": p.planner, "tasks": len(plan.tasks),
                                             "usage": {k: v for k, v in (p.usage or {}).items() if k != "note"},
                                             "planned_at": p.created_at.isoformat()})
    p.status, p.run_id = "executed", run.id
    db.commit()
    engine.submit(run.id)
    db.refresh(run)
    return run_summary(db, run)
