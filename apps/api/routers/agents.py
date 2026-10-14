"""Agent registry (configuration), tool catalogue, and model-provider status."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from apps.api import schemas as s
from core.platform import agent_registry, gateway, tools
from core.platform.catalog import CATALOG
from core.platform.db import get_session
from core.platform.models import NodeRun, User
from core.platform.security import require

router = APIRouter(tags=["Agents & tools"])


def _stats(db: Session) -> dict[str, tuple[int, int]]:
    failed = func.sum(case((NodeRun.status == "failed", 1), else_=0))
    return {a: (int(c), int(f or 0)) for a, c, f in
            db.query(NodeRun.agent, func.count(NodeRun.id), failed)
            .filter(NodeRun.attempts > 0, NodeRun.agent.isnot(None)).group_by(NodeRun.agent).all()}


def _out(entry: dict, stats: dict, detail: bool = False):
    c = entry["config"]
    runs, fails = stats.get(entry["id"], (0, 0))
    types = sorted({t for t, n in CATALOG.items() if n.agent == entry["id"] or (n.kind == "rag" and c["level"] == 1)}) \
        if c["level"] == 1 else (["agent.task"] if c["level"] == 2 else [])
    base = dict(id=entry["id"], name=c["name"], role=c["role"] or c["description"], parent=c["parent_id"],
                tools=c["allowed_tools"], node_types=types, node_runs=runs, failures=fails, level=c["level"],
                status=entry["status"], version=entry["version"], capabilities=c["capabilities"],
                model_provider=c["model"]["provider"], permissions=c["permissions"])
    if detail:
        return s.AgentDetail(**base, description=c["description"], config=c, created_at=entry["created_at"],
                             updated_at=entry["updated_at"])
    return s.AgentOut(**base)


def _raise(exc: agent_registry.AgentConfigError):
    raise HTTPException(exc.status_code, detail={"message": str(exc), "issues": exc.issues})


@router.get("/agents", response_model=list[s.AgentOut])
def list_agents(include_archived: bool = Query(False), db: Session = Depends(get_session),
                _: User = Depends(require("registry:read"))):
    stats = _stats(db)
    return [_out(a, stats) for a in agent_registry.list_agents(db, include_archived)]


@router.get("/agents/{agent_id}", response_model=s.AgentDetail)
def get_agent(agent_id: str, db: Session = Depends(get_session), _: User = Depends(require("registry:read"))):
    a = agent_registry.get_agent(db, agent_id)
    if a is None:
        raise HTTPException(404, "Agent not found.")
    return _out(a, _stats(db), detail=True)


@router.get("/agents/{agent_id}/versions", response_model=list[s.AgentVersionOut])
def agent_versions(agent_id: str, db: Session = Depends(get_session), _: User = Depends(require("registry:read"))):
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(404, "Agent not found.")
    return [s.AgentVersionOut(version=v.version, created_by=v.created_by, created_at=v.created_at,
                              change_note=v.change_note, config=v.config) for v in agent_registry.list_versions(db, agent_id)]


@router.post("/agents", response_model=s.AgentDetail, status_code=201)
def create_agent(body: s.AgentWriteIn, db: Session = Depends(get_session), user: User = Depends(require("agent:write"))):
    try:
        a = agent_registry.create_agent(db, body.config, user.id, user.role)
    except agent_registry.AgentConfigError as exc:
        _raise(exc)
    return _out(a, _stats(db), detail=True)


@router.put("/agents/{agent_id}", response_model=s.AgentDetail)
def update_agent(agent_id: str, body: s.AgentWriteIn, db: Session = Depends(get_session),
                 user: User = Depends(require("agent:write"))):
    try:
        a = agent_registry.update_agent(db, agent_id, body.config, user.id, body.change_note, user.role)
    except agent_registry.AgentConfigError as exc:
        _raise(exc)
    return _out(a, _stats(db), detail=True)


@router.post("/agents/{agent_id}/status", response_model=s.AgentDetail)
def set_agent_status(agent_id: str, body: s.AgentStatusIn, db: Session = Depends(get_session),
                     user: User = Depends(require("agent:write"))):
    try:
        a = agent_registry.set_status(db, agent_id, body.status, user.id, user.role)
    except agent_registry.AgentConfigError as exc:
        _raise(exc)
    return _out(a, _stats(db), detail=True)


@router.get("/tools", response_model=list[s.ToolOut])
def list_tools(_: User = Depends(require("registry:read"))):
    return [s.ToolOut(**tools.describe(n)) for n in sorted(tools.all_tools())]


@router.get("/gateway/providers", response_model=list[s.ProviderStatusOut])
def providers(_: User = Depends(require("registry:read"))):
    return [s.ProviderStatusOut(**p) for p in gateway.provider_status()]
