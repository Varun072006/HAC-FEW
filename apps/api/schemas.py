"""Typed API contracts (v1). The React client's types are generated from the OpenAPI document
that FastAPI derives from these models; see docs/API_CONTRACTS.md."""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["queued", "running", "awaiting_approval", "completed", "partial", "failed", "rejected", "cancelled"]
NodeStatus = Literal["pending", "running", "awaiting_approval", "completed", "failed", "skipped", "rejected", "cancelled"]
ApprovalStatus = Literal["pending", "approved", "rejected", "cancelled"]
RiskTier = Literal["low", "medium", "high"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    employee_id: Optional[str] = None
    permissions: list[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


class AuthConfig(BaseModel):
    environment: str
    dev_accounts: list[str] = Field(default_factory=list, description="Only populated in development.")


# ---- workflow definition
class Position(BaseModel):
    x: float = 0
    y: float = 0


class NodeDef(BaseModel):
    id: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_\-]+$")
    type: str
    label: Optional[str] = None
    position: Position = Field(default_factory=Position)
    params: dict[str, Any] = Field(default_factory=dict)


class EdgeDef(BaseModel):
    id: str
    source: str
    target: str
    branch: Optional[Literal["true", "false"]] = Field(default=None, description="Set on edges leaving a condition step.")


class WorkflowDefinition(BaseModel):
    nodes: list[NodeDef] = Field(max_length=100)
    edges: list[EdgeDef] = Field(max_length=300)


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: Optional[str] = None
    category: Optional[str] = Field(default=None, description="planning_failure | policy_rejection | budget_exceeded")


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue]


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    definition: WorkflowDefinition
    template_id: Optional[str] = None


class WorkflowUpdate(BaseModel):
    expected_version: int = Field(description="Optimistic concurrency: must equal the stored version.")
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    definition: Optional[WorkflowDefinition] = None


class WorkflowSummary(ORM):
    id: str
    name: str
    description: str
    version: int
    template_id: Optional[str] = None
    node_count: int
    created_by: str
    updated_at: datetime


class WorkflowDetail(WorkflowSummary):
    definition: WorkflowDefinition
    created_at: datetime
    validation: ValidationResult
    trigger_fields: list[dict[str, Any]]


class WorkflowList(BaseModel):
    items: list[WorkflowSummary]


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str
    definition: WorkflowDefinition


class CatalogParam(BaseModel):
    name: str
    label: str
    type: str
    required: bool
    default: Any = None
    help: str = ""
    options: list[str] = Field(default_factory=list)


class CatalogNode(BaseModel):
    type: str
    label: str
    category: str
    kind: str
    description: str
    agent: Optional[str] = None
    tool: Optional[str] = None
    side_effect: bool
    default_risk: RiskTier
    allowed_roles: list[str]
    outputs: list[str]
    params: list[CatalogParam]


# ---- runs
class RunCreate(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class PolicyDecisionOut(BaseModel):
    allowed: bool
    requires_human_approval: bool = False
    risk_level: RiskTier
    reason: str
    rule_id: Optional[str] = None
    suggested_approver: Optional[str] = None


class ToolCallOut(BaseModel):
    tool: str
    success: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None


class OperationOut(BaseModel):
    index: int
    tool: str
    effect: str
    replayed: bool = False
    latency_ms: Optional[int] = None
    approved_by: Optional[str] = None
    evidence_count: int = 0
    abstained: bool = False


class UsageOut(BaseModel):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    source: str = Field(default="none", description="provider | estimated | mixed | none. Never invented.")
    cost_usd: Optional[float] = Field(default=None, description="Always null: no price table is configured.")


class NodeRunOut(BaseModel):
    node_id: str
    node_type: str
    label: Optional[str]
    agent: Optional[str]
    status: NodeStatus
    attempts: int
    input: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    policy: Optional[PolicyDecisionOut] = None
    tool_calls: list[ToolCallOut] = Field(default_factory=list)
    summary: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    latency_ms: Optional[int] = None
    agent_version: Optional[int] = None
    delegation: list[str] = Field(default_factory=list, description="Delegation chain, supervisor first.")
    failure_class: Optional[str] = None
    usage: Optional[UsageOut] = None
    operations: list[OperationOut] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    criticality: Optional[str] = None
    pending_tool: Optional[str] = None


class RunSummary(BaseModel):
    id: str
    workflow_id: str
    workflow_name: str
    workflow_version: int
    status: RunStatus
    started_by: str
    started_by_name: str
    created_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    objective: Optional[str] = None


class RunList(BaseModel):
    items: list[RunSummary]
    total: int


class ApprovalDecisionOut(BaseModel):
    approver_id: str
    approver_name: str
    approver_role: str
    decision: Literal["approve", "reject"]
    comment: Optional[str] = None
    decided_at: datetime


class ApprovalOut(BaseModel):
    id: str
    run_id: str
    workflow_name: str
    node_id: str
    node_label: Optional[str] = None
    status: ApprovalStatus
    risk_level: RiskTier
    rule_id: Optional[str] = None
    reason: str
    tool_name: str
    agent: str
    op_index: int = 0
    evidence: list[Any] = Field(default_factory=list)
    params: dict[str, Any]
    required_slots: list[list[str]]
    filled_slots: list[int]
    requested_by: str
    requested_by_name: str
    requested_at: datetime
    decided_at: Optional[datetime] = None
    decisions: list[ApprovalDecisionOut]
    can_decide: bool = Field(description="Server-computed for the calling user; the UI must not infer this.")


class ApprovalList(BaseModel):
    items: list[ApprovalOut]


class ApprovalDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    comment: Optional[str] = Field(default=None, max_length=1000)


class RunDetail(RunSummary):
    inputs: dict[str, Any]
    definition: WorkflowDefinition
    node_runs: list[NodeRunOut]
    approvals: list[ApprovalOut]
    last_seq: int
    budget: dict[str, Any] = Field(default_factory=dict)
    usage: UsageOut = Field(default_factory=UsageOut)
    tool_calls_used: int = 0
    plan_id: Optional[str] = None
    cancel_requested: bool = False


class RunEventOut(BaseModel):
    seq: int
    ts: datetime
    type: str
    node_id: Optional[str] = None
    data: dict[str, Any]


class RunEventsPage(BaseModel):
    events: list[RunEventOut]
    next_after: int
    run_status: RunStatus
    terminal: bool


# ---- registry / observability
class AgentOut(BaseModel):
    id: str
    name: str
    role: str
    parent: Optional[str] = None
    tools: list[str]
    node_types: list[str]
    node_runs: int
    failures: int
    level: int = 1
    status: Literal["active", "disabled", "archived"] = "active"
    version: int = 1
    capabilities: list[str] = Field(default_factory=list)
    model_provider: str = "deterministic"
    permissions: dict[str, bool] = Field(default_factory=dict)


class AgentDetail(AgentOut):
    description: str = ""
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AgentVersionOut(BaseModel):
    version: int
    created_by: str
    created_at: datetime
    change_note: Optional[str] = None
    config: dict[str, Any]


class AgentStatusIn(BaseModel):
    status: Literal["active", "disabled", "archived"]


class AgentWriteIn(BaseModel):
    config: dict[str, Any] = Field(description="Full agent configuration; validated server-side (see AgentConfig).")
    change_note: Optional[str] = Field(default=None, max_length=300)


class ToolOut(BaseModel):
    name: str
    description: str
    effect: Literal["read", "write", "destructive"]
    connector: str
    capabilities: list[str]
    allowed_roles: list[str]
    timeout_s: float
    max_retries: int
    idempotent: bool
    input_schema: dict[str, Any]


class ProviderStatusOut(BaseModel):
    provider: str
    available: bool
    detail: str


class PlanCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=1000)
    mode: Literal["auto", "deterministic", "llm", "structured"] = "auto"
    plan: Optional[dict[str, Any]] = Field(default=None, description="Required when mode is 'structured'.")


class PlanOut(BaseModel):
    id: str
    objective: str
    status: Literal["draft", "invalid", "executed"]
    planner: str
    plan: dict[str, Any]
    issues: list[ValidationIssue]
    valid: bool
    failure_category: Optional[str] = None
    usage: Optional[UsageOut] = None
    definition: Optional[WorkflowDefinition] = None
    trigger_fields: list[dict[str, Any]] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    run_id: Optional[str] = None
    note: Optional[str] = None


class PlanExecuteIn(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class ConnectorOut(BaseModel):
    id: str
    name: str
    system: str
    mode: str
    status: Literal["healthy", "unreachable"]
    detail: dict[str, Any]
    tools: list[str]
    calls: int
    failures: int
    configurable: bool
    note: str


class PolicyOverview(BaseModel):
    agent_tool_permissions: dict[str, list[str]]
    rules: list[dict[str, Any]]
    approval_slots: dict[str, list[list[str]]]
    role_permissions: dict[str, list[str]]
    node_role_access: dict[str, list[str]]


class AuditEventOut(ORM):
    id: int
    ts: datetime
    actor_type: str
    actor_id: str
    actor_role: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    run_id: Optional[str] = None
    outcome: str
    risk: Optional[str] = None
    detail: dict[str, Any]
    hash: str


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    total: int


class AuditVerify(BaseModel):
    valid: bool
    checked: int
    first_invalid_id: Optional[int] = None


class NodeTypeUsage(BaseModel):
    node_type: str
    runs: int
    failures: int
    avg_latency_ms: Optional[float] = None
    max_latency_ms: Optional[int] = None


class UsageSummary(BaseModel):
    llm_backed: bool
    llm_calls: int
    input_tokens: int = 0
    output_tokens: int = 0
    usage_source: str = "none"
    note: str
    total_node_runs: int
    by_node_type: list[NodeTypeUsage]
    tool_calls: int
    tool_failures: int


class Overview(BaseModel):
    workflows: int
    runs_total: int
    runs_by_status: dict[str, int]
    pending_approvals: int
    approvals_awaiting_you: int
    recent_runs: list[RunSummary]


class OrgInfo(BaseModel):
    environment: str
    database: str
    users: list[UserOut]
    roles: list[str]
