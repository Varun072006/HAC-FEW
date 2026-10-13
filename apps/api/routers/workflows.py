import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from apps.api import schemas as s
from apps.api.serializers import run_summary, workflow_detail, workflow_summary
from core.platform import audit, engine
from core.platform.catalog import catalog_json
from core.platform.db import get_session
from core.platform.models import Run, User, Workflow, utcnow
from core.platform.security import require
from core.platform.templates import TEMPLATES
from core.platform.validation import has_errors, validate_definition

router = APIRouter(tags=["Workflows"])


def _defn(d: s.WorkflowDefinition) -> dict[str, Any]:
    return d.model_dump(mode="json")


@router.get("/catalog/nodes", response_model=list[s.CatalogNode])
def node_catalog(_: User = Depends(require("workflow:read"))):
    return catalog_json()


@router.get("/templates", response_model=list[s.TemplateOut])
def templates(_: User = Depends(require("workflow:read"))):
    return TEMPLATES


@router.post("/workflows/validate", response_model=s.ValidationResult)
def validate(defn: s.WorkflowDefinition, user: User = Depends(require("workflow:read"))):
    issues = validate_definition(_defn(defn), user_role=user.role)
    return s.ValidationResult(valid=not has_errors(issues), issues=issues)


@router.get("/workflows", response_model=s.WorkflowList)
def list_workflows(db: Session = Depends(get_session), _: User = Depends(require("workflow:read"))):
    rows = db.query(Workflow).order_by(Workflow.updated_at.desc()).all()
    return s.WorkflowList(items=[workflow_summary(w) for w in rows])


@router.post("/workflows", response_model=s.WorkflowDetail, status_code=status.HTTP_201_CREATED)
def create_workflow(body: s.WorkflowCreate, db: Session = Depends(get_session),
                    user: User = Depends(require("workflow:write"))):
    w = Workflow(id=f"wf_{uuid.uuid4().hex[:10]}", name=body.name.strip(), description=body.description,
                 definition=_defn(body.definition), version=1, template_id=body.template_id, created_by=user.id)
    db.add(w)
    db.commit()
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="workflow.created",
                 outcome="success", resource_type="workflow", resource_id=w.id, detail={"name": w.name})
    return workflow_detail(w, user.role)


@router.get("/workflows/{workflow_id}", response_model=s.WorkflowDetail)
def get_workflow(workflow_id: str, db: Session = Depends(get_session), user: User = Depends(require("workflow:read"))):
    w = db.get(Workflow, workflow_id)
    if not w:
        raise HTTPException(404, "Workflow not found.")
    return workflow_detail(w, user.role)


@router.put("/workflows/{workflow_id}", response_model=s.WorkflowDetail)
def update_workflow(workflow_id: str, body: s.WorkflowUpdate, db: Session = Depends(get_session),
                    user: User = Depends(require("workflow:write"))):
    w = db.get(Workflow, workflow_id)
    if not w:
        raise HTTPException(404, "Workflow not found.")
    if w.version != body.expected_version:
        raise HTTPException(409, f"Workflow was changed by someone else (stored v{w.version}, yours v{body.expected_version}). "
                                 "Reload before saving.")
    if body.name is not None:
        w.name = body.name.strip()
    if body.description is not None:
        w.description = body.description
    if body.definition is not None:
        w.definition = _defn(body.definition)
    w.version += 1
    w.updated_at = utcnow()
    db.commit()
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="workflow.updated",
                 outcome="success", resource_type="workflow", resource_id=w.id, detail={"version": w.version})
    return workflow_detail(w, user.role)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: str, db: Session = Depends(get_session), user: User = Depends(require("workflow:write"))):
    w = db.get(Workflow, workflow_id)
    if not w:
        raise HTTPException(404, "Workflow not found.")
    if db.query(Run).filter(Run.workflow_id == w.id).first():
        raise HTTPException(409, "This workflow has execution history and cannot be deleted. Runs reference its snapshot.")
    db.delete(w)
    db.commit()
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="workflow.deleted",
                 outcome="success", resource_type="workflow", resource_id=workflow_id)
    return Response(status_code=204)


@router.post("/workflows/{workflow_id}/runs", response_model=s.RunSummary, status_code=status.HTTP_202_ACCEPTED)
def start_run(workflow_id: str, body: s.RunCreate, db: Session = Depends(get_session),
              user: User = Depends(require("workflow:run"))):
    w = db.get(Workflow, workflow_id)
    if not w:
        raise HTTPException(404, "Workflow not found.")
    try:
        run = engine.create_run(db, w, body.inputs, user)
    except engine.RunRejected as exc:
        raise HTTPException(422, detail={"message": str(exc), "issues": exc.issues})
    engine.submit(run.id)
    db.refresh(run)
    return run_summary(db, run)
