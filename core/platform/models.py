from datetime import datetime, timezone
from sqlalchemy import (
    JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index,
)
from core.platform.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id = Column(String(40), primary_key=True)
    username = Column(String(60), unique=True, nullable=False)
    display_name = Column(String(120), nullable=False)
    role = Column(String(40), nullable=False)
    employee_id = Column(String(50), nullable=True)  # link to HRMS record, used for ABAC
    password_hash = Column(String(300), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Workflow(Base):
    __tablename__ = "workflows"
    id = Column(String(40), primary_key=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, default="", nullable=False)
    definition = Column(JSON, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    template_id = Column(String(60), nullable=True)
    created_by = Column(String(40), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Run(Base):
    __tablename__ = "runs"
    id = Column(String(40), primary_key=True)
    workflow_id = Column(String(40), ForeignKey("workflows.id"), nullable=False)
    workflow_name = Column(String(160), nullable=False)
    workflow_version = Column(Integer, nullable=False)
    definition_snapshot = Column(JSON, nullable=False)
    inputs = Column(JSON, nullable=False)
    status = Column(String(30), nullable=False)  # queued|running|awaiting_approval|completed|partial|failed|rejected|cancelled
    started_by = Column(String(40), ForeignKey("users.id"), nullable=False)
    started_by_role = Column(String(40), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    next_seq = Column(Integer, default=1, nullable=False)
    # --- agent runtime (migration 0002) ---
    objective = Column(Text, nullable=True)
    plan_id = Column(String(40), nullable=True)
    budget = Column(JSON, nullable=True)           # workflow-level resource limits chosen at run creation
    agent_snapshot = Column(JSON, nullable=True)   # configs of every agent the run may use (version-pinned)
    cancel_requested = Column(Boolean, default=False, nullable=False)
    __table_args__ = (Index("ix_runs_status", "status"), Index("ix_runs_started_by", "started_by"))


class NodeRun(Base):
    __tablename__ = "node_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(40), ForeignKey("runs.id"), nullable=False)
    node_id = Column(String(60), nullable=False)
    node_type = Column(String(60), nullable=False)
    label = Column(String(160), nullable=True)
    agent = Column(String(60), nullable=True)
    # pending|running|awaiting_approval|completed|failed|skipped|rejected|cancelled
    status = Column(String(30), nullable=False, default="pending")
    attempts = Column(Integer, default=0, nullable=False)
    input = Column(JSON, nullable=True)
    output = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    policy = Column(JSON, nullable=True)
    tool_calls = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    # --- agent runtime (migration 0002) ---
    agent_version = Column(Integer, nullable=True)
    delegation = Column(JSON, nullable=True)       # ["supervisor", "finance", "expense_specialist"]
    usage = Column(JSON, nullable=True)            # model/tool usage for this task, with provenance
    checkpoint = Column(JSON, nullable=True)       # resumable agent state (completed ops, pending op)
    failure_class = Column(String(30), nullable=True)
    __table_args__ = (UniqueConstraint("run_id", "node_id", name="uq_node_run"),)


class RunEvent(Base):
    __tablename__ = "run_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(40), ForeignKey("runs.id"), nullable=False)
    seq = Column(Integer, nullable=False)
    ts = Column(DateTime, default=utcnow, nullable=False)
    type = Column(String(40), nullable=False)
    node_id = Column(String(60), nullable=True)
    data = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),)


class Approval(Base):
    __tablename__ = "approvals"
    id = Column(String(40), primary_key=True)
    run_id = Column(String(40), ForeignKey("runs.id"), nullable=False)
    node_id = Column(String(60), nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending|approved|rejected|cancelled
    risk_level = Column(String(10), nullable=False)
    rule_id = Column(String(60), nullable=True)
    reason = Column(Text, nullable=False)
    tool_name = Column(String(80), nullable=False)
    agent = Column(String(60), nullable=False)
    params_snapshot = Column(JSON, nullable=False)  # immutable: exactly what will execute
    required_slots = Column(JSON, nullable=False)   # list of lists of eligible roles
    requested_by = Column(String(40), ForeignKey("users.id"), nullable=False)
    requested_at = Column(DateTime, default=utcnow, nullable=False)
    decided_at = Column(DateTime, nullable=True)
    op_index = Column(Integer, default=0, nullable=False)   # which operation of the task is protected
    evidence = Column(JSON, nullable=True)                  # what the task had established when it paused
    __table_args__ = (UniqueConstraint("run_id", "node_id", "op_index", name="uq_approval_node_op"),
                      Index("ix_approvals_status", "status"))


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    approval_id = Column(String(40), ForeignKey("approvals.id"), nullable=False)
    approver_id = Column(String(40), ForeignKey("users.id"), nullable=False)
    approver_role = Column(String(40), nullable=False)
    decision = Column(String(10), nullable=False)  # approve|reject
    comment = Column(Text, nullable=True)
    slot_index = Column(Integer, nullable=True)
    decided_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("approval_id", "approver_id", name="uq_decision_approver"),
                      UniqueConstraint("approval_id", "slot_index", name="uq_decision_slot"))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=utcnow, nullable=False)
    actor_type = Column(String(20), nullable=False)  # user|agent|system
    actor_id = Column(String(60), nullable=False)
    actor_role = Column(String(40), nullable=True)
    action = Column(String(80), nullable=False)
    resource_type = Column(String(40), nullable=True)
    resource_id = Column(String(60), nullable=True)
    run_id = Column(String(40), nullable=True)
    outcome = Column(String(20), nullable=False)  # success|denied|failure|pending
    risk = Column(String(10), nullable=True)
    detail = Column(JSON, nullable=False, default=dict)
    prev_hash = Column(String(64), nullable=False)
    hash = Column(String(64), nullable=False)
    __table_args__ = (Index("ix_audit_run", "run_id"), Index("ix_audit_action", "action"))


class Agent(Base):
    """Lifecycle record of an agent. Configuration lives in AgentVersion; execution state lives in NodeRun."""
    __tablename__ = "agents"
    id = Column(String(60), primary_key=True)
    status = Column(String(20), nullable=False, default="active")  # active|disabled|archived
    current_version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(40), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AgentVersion(Base):
    """Immutable, validated configuration of one agent version."""
    __tablename__ = "agent_versions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(60), ForeignKey("agents.id"), nullable=False)
    version = Column(Integer, nullable=False)
    level = Column(Integer, nullable=False)
    parent_id = Column(String(60), nullable=True)
    config = Column(JSON, nullable=False)
    change_note = Column(Text, nullable=True)
    created_by = Column(String(40), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_version"),
                      Index("ix_agent_versions_parent", "parent_id"))


class Plan(Base):
    __tablename__ = "plans"
    id = Column(String(40), primary_key=True)
    objective = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="draft")  # draft|executed|invalid
    planner = Column(String(30), nullable=False)                  # deterministic|llm|structured
    plan = Column(JSON, nullable=False)
    issues = Column(JSON, nullable=False, default=list)
    usage = Column(JSON, nullable=True)
    created_by = Column(String(40), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    run_id = Column(String(40), nullable=True)


class ToolExecution(Base):
    """One bounded tool operation. The unique idempotency key is what stops a side effect running twice."""
    __tablename__ = "tool_executions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    idempotency_key = Column(String(64), nullable=False)
    run_id = Column(String(40), ForeignKey("runs.id"), nullable=False)
    node_id = Column(String(60), nullable=False)
    op_index = Column(Integer, nullable=False)
    tool = Column(String(80), nullable=False)
    effect = Column(String(12), nullable=False)       # read|write|destructive
    status = Column(String(12), nullable=False)       # started|succeeded|failed
    args = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_tool_idem"),
                      Index("ix_tool_exec_run", "run_id"))
