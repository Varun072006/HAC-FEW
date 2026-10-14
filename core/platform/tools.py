"""Central tool registry (hierarchy Level 3: tools and bounded operations).

A tool is the only thing that touches a business system. Each declares its input model, effect class
(read | write | destructive), capabilities, roles, timeout, retry behaviour and idempotency. Agents
never call these directly: every call goes through core.platform.operations, which validates arguments,
checks authorization and policy, obtains approval, enforces idempotency and writes the audit trail.

Tool inputs are pydantic models with extra="forbid": a model that invents an argument is rejected,
not silently ignored."""
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

EFFECTS = ("read", "write", "destructive")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransientToolError(Exception):
    """Raised by a handler for failures worth retrying (timeouts, 5xx, rate limits)."""


@dataclass
class ToolContext:
    run_id: str
    node_id: str
    agent_id: str
    department: str            # L1 ancestor: the scope the governance policy engine reasons about
    user_role: str
    user_employee_id: Optional[str] = None
    approved_by: Optional[str] = None
    user_id: str = ""
    epoch: int = 0              # bumped by a manual node retry so the retry gets a fresh artifact / idempotency slot


@dataclass
class ToolResult:
    success: bool
    data: dict = field(default_factory=dict)
    error: Optional[str] = None
    evidence: list = field(default_factory=list)   # citations / record ids this result is grounded in
    abstained: bool = False                        # retrieval found nothing it could stand behind
    failure_class: Optional[str] = None            # e.g. validation_error: lets a tool say *why* it failed


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    effect: str                                   # read | write | destructive
    capabilities: tuple
    input_model: type
    handler: Callable[[ToolContext, dict], ToolResult]
    connector: str
    output_required: tuple = ()
    allowed_roles: tuple = ("employee", "manager", "director", "controller", "hr_rep", "it_admin", "admin")
    timeout_s: float = 30.0
    max_retries: int = 0                          # transient-failure retries; only honoured for reads
    idempotent: bool = False                      # safe to repeat with the same arguments
    needs_approval_context: bool = False          # handler receives ctx.approved_by after human approval
    owner_field: Optional[str] = None             # employees may only act on records where this arg is their own id
    output_model: Optional[type] = None           # typed contract for what the tool returns (validated before any downstream use)
    policy_hook: Optional[Callable[[Any, dict], Optional[dict]]] = None   # may tighten the policy decision using run state
    retry_transient_writes: bool = False          # a TransientToolError from this write PROVES nothing was sent, so retrying is safe

    def schema(self) -> dict:
        return self.input_model.model_json_schema()


_registry: dict[str, ToolSpec] = {}
_lock = threading.Lock()


def register(spec: ToolSpec) -> ToolSpec:
    if spec.effect not in EFFECTS:
        raise ValueError(f"Unknown effect class '{spec.effect}'.")
    with _lock:
        _registry[spec.name] = spec
    return spec


def unregister(name: str) -> None:
    with _lock:
        _registry.pop(name, None)


def get(name: str) -> Optional[ToolSpec]:
    return _registry.get(name)


def all_tools() -> dict[str, ToolSpec]:
    return dict(_registry)


def describe(name: str) -> dict:
    t = _registry[name]
    return {"name": t.name, "description": t.description, "effect": t.effect, "connector": t.connector,
            "capabilities": list(t.capabilities), "allowed_roles": list(t.allowed_roles),
            "timeout_s": t.timeout_s, "max_retries": t.max_retries, "idempotent": t.idempotent,
            "input_schema": t.schema()}


# ------------------------------------------------------------------ inputs
class PolicySearchIn(Strict):
    query: str = Field(min_length=3, max_length=500)


class EmployeeGetIn(Strict):
    emp_id: str = Field(min_length=1, max_length=40)


class EmployeeCreateIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")
    department: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    start_date: str = Field(default="2026-11-01", pattern=r"^\d{4}-\d{2}-\d{2}$")


class PayrollIn(Strict):
    employee_id: str = Field(min_length=1, max_length=40)
    base_salary: float = Field(default=95000.0, gt=0, le=10_000_000)


class ExpenseIn(Strict):
    employee_id: str = Field(min_length=1, max_length=40)
    category: str = Field(default="Travel / Meals", max_length=80)
    amount: float = Field(gt=0, le=1_000_000)
    receipt_attached: bool = True
    description: str = Field(min_length=1, max_length=500)


class TicketIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="General Support", max_length=80)
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    severity: str = Field(default="SEV-3", pattern="^SEV-[123]$")
    description: str = Field(min_length=1, max_length=2000)


class EmailIn(Strict):
    recipient: str = Field(min_length=3, max_length=200)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=4000)


class ReconcileCheck(Strict):
    name: str = Field(min_length=1, max_length=80)
    expected: Any = None
    actual: Any = None


class ReconcileIn(Strict):
    checks: list[ReconcileCheck] = Field(min_length=1, max_length=50)


# ------------------------------------------------------------------ handlers
_retriever = None
_retriever_lock = threading.Lock()
_mock_lock = threading.Lock()   # the bundled mock systems share one in-process SQLite file


def get_retriever():
    global _retriever
    with _retriever_lock:
        if _retriever is None:
            from core.rag.retriever import HybridPolicyRetriever
            _retriever = HybridPolicyRetriever("data/policies")
        return _retriever


# Platform roles that policy documents do not name explicitly are mapped for retrieval filtering.
RETRIEVAL_ROLE = {"controller": "finance_rep", "director": "manager"}


def _policy_search(ctx: ToolContext, a: dict) -> ToolResult:
    res = get_retriever().retrieve(a["query"], user_role=RETRIEVAL_ROLE.get(ctx.user_role, ctx.user_role))
    data = {"retrieved_chunks": len(res.results), "citations": res.citations, "top_score": round(res.top_score, 4),
            "abstained": res.abstain, "context": res.context_for_prompt}
    return ToolResult(True, data, evidence=list(res.citations), abstained=bool(res.abstain))


OWNER = {"hrms": "hr", "erp": "finance", "ticketing": "it", "notifications": "it"}


def _legacy(name: str, with_approval: bool = False) -> Callable[[ToolContext, dict], ToolResult]:
    """Adapt an existing enterprise tool to the registry. The legacy function repeats the governance check
    as the system that owns the tool's department (defence in depth); who may call it at all was already
    decided by the operation pipeline from the agent registry, so a custom department is not locked out."""
    owner = OWNER[name.split("_")[0]]
    def handler(ctx: ToolContext, a: dict) -> ToolResult:
        from core.tools.enterprise_tools import TOOL_REGISTRY
        kwargs = {"approved_by": ctx.approved_by} if with_approval else {}
        try:
            with _mock_lock:
                resp = TOOL_REGISTRY[name](agent=owner, params=a, **kwargs)
        except Exception as exc:  # connector transport failure: the caller decides whether to retry
            raise TransientToolError(str(exc)) from exc
        data = resp.data or {}
        if resp.success and data.get("status") == "awaiting_approval":
            return ToolResult(False, {}, "Tool reported an unresolved approval gate; refusing to continue.")
        evidence = [str(data["id"])] if resp.success and "id" in data else []
        return ToolResult(resp.success, data, resp.error, evidence=evidence)
    return handler


def _reconcile(ctx: ToolContext, a: dict) -> ToolResult:
    def norm(v):
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return str(v).strip().lower() if isinstance(v, str) else v
    results = [{"name": c["name"], "passed": norm(c.get("expected")) == norm(c.get("actual")),
                "expected": c.get("expected"), "actual": c.get("actual")} for c in a["checks"]]
    failed = [r["name"] for r in results if not r["passed"]]
    data = {"all_passed": not failed, "checks": results, "failed": failed}
    if failed:
        return ToolResult(False, data, f"Reconciliation failed: {', '.join(failed)}")
    return ToolResult(True, data)


_STAFF = ("manager", "director", "controller", "hr_rep", "admin")

for _spec in [
    ToolSpec("rag_retrieve_policy", "Search the enterprise policy knowledge base; returns cited passages.",
             "read", ("retrieval", "policy_lookup"), PolicySearchIn, _policy_search, "knowledge",
             output_required=("citations", "abstained"), timeout_s=30, max_retries=1, idempotent=True),
    ToolSpec("hrms_get_employee", "Read one employee record from the HRMS.", "read",
             ("employee_lookup",), EmployeeGetIn, _legacy("hrms_get_employee"), "hrms",
             timeout_s=15, max_retries=2, idempotent=True),
    ToolSpec("hrms_create_employee", "Create an employee record in the HRMS.", "write",
             ("employee_onboarding",), EmployeeCreateIn, _legacy("hrms_create_employee"), "hrms",
             output_required=("id",), allowed_roles=_STAFF),
    ToolSpec("erp_setup_payroll", "Register payroll for an existing employee in the ERP.", "write",
             ("payroll_setup",), PayrollIn, _legacy("erp_setup_payroll"), "erp",
             output_required=("status",), allowed_roles=_STAFF),
    ToolSpec("erp_submit_expense", "Submit an expense reimbursement; policy decides approval.", "write",
             ("expense_processing",), ExpenseIn, _legacy("erp_submit_expense", with_approval=True), "erp",
             output_required=("id", "status"), needs_approval_context=True, owner_field="employee_id"),
    ToolSpec("ticketing_create_ticket", "Open an IT incident or provisioning ticket.", "write",
             ("incident_response", "it_provisioning"), TicketIn, _legacy("ticketing_create_ticket"), "ticketing",
             output_required=("id",)),
    ToolSpec("notifications_send_email", "Send a stakeholder notification through the mock email service.", "write",
             ("notification",), EmailIn, _legacy("notifications_send_email"), "notifications",
             output_required=("status",)),
    ToolSpec("reconcile_results", "Deterministically compare expected and actual values from earlier tasks.",
             "read", ("reconciliation",), ReconcileIn, _reconcile, "internal",
             output_required=("all_passed",), idempotent=True),
]:
    register(_spec)


from core.platform import tools_automation  # noqa: E402,F401  (registers the business-automation tools)
