"""Node catalog: the small set of node types the engine can actually execute.

Every node here maps to a real tool or retrieval call. Adding a node means adding it here
and nowhere else: the validator, the engine, and the UI palette all read this registry."""
from dataclasses import dataclass, field
from typing import Optional

ALL_ROLES = ["employee", "manager", "director", "controller", "hr_rep", "it_admin", "admin"]
PRIVILEGED = ["manager", "director", "controller", "hr_rep", "admin"]


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    type: str = "string"            # string | text | number | boolean | select | fields
    required: bool = True
    default: object = None
    help: str = ""
    options: tuple = ()


@dataclass(frozen=True)
class NodeSpecDef:
    type: str
    label: str
    category: str                   # trigger | knowledge | hr | finance | it | notify
    kind: str                       # trigger | rag | tool
    description: str
    agent: Optional[str]            # department agent responsible (None for the trigger)
    tool: Optional[str]             # key into TOOL_REGISTRY for kind == "tool"
    params: tuple = ()
    outputs: tuple = ()
    side_effect: bool = False       # writes to an external system: never auto-retried
    allowed_roles: tuple = tuple(ALL_ROLES)
    default_risk: str = "low"


CATALOG: dict[str, NodeSpecDef] = {n.type: n for n in [
    NodeSpecDef(
        type="trigger.manual", label="Manual trigger", category="trigger", kind="trigger",
        description="Starts the workflow. Declares the input fields the person running it must provide.",
        agent=None, tool=None,
        params=(Param("fields", "Input fields", "fields", required=False, default=[],
                      help="Each field becomes an input in the run dialog and is referenced as {{trigger.<name>}}."),),
        outputs=(),
    ),
    NodeSpecDef(
        type="policy.search", label="Policy search", category="knowledge", kind="rag",
        description="Retrieves cited policy passages from the enterprise knowledge base, filtered by the caller's role.",
        agent="finance",
        tool=None,
        params=(
            Param("agent", "Responsible agent", "select", default="finance", options=("hr", "finance", "it")),
            Param("query", "Query", "text", help="Natural-language question. Supports {{...}} references."),
        ),
        outputs=("retrieved_chunks", "citations", "top_score", "abstained", "context"),
    ),
    NodeSpecDef(
        type="hr.create_employee", label="Create employee", category="hr", kind="tool",
        description="Registers a new employee record in the HRMS.", agent="hr", tool="hrms_create_employee",
        params=(
            Param("name", "Full name"), Param("email", "Email"),
            Param("department", "Department"), Param("role", "Job role"),
            Param("start_date", "Start date", default="2026-11-01", help="YYYY-MM-DD"),
        ),
        outputs=("id", "name", "email", "department", "role", "status", "start_date"),
        side_effect=True, allowed_roles=tuple(PRIVILEGED), default_risk="medium",
    ),
    NodeSpecDef(
        type="finance.setup_payroll", label="Set up payroll", category="finance", kind="tool",
        description="Registers payroll for an existing employee in the ERP.", agent="finance", tool="erp_setup_payroll",
        params=(Param("employee_id", "Employee ID"),
                Param("base_salary", "Base salary (USD)", "number", default=95000)),
        outputs=("status", "message", "setup_timestamp"),
        side_effect=True, allowed_roles=tuple(PRIVILEGED), default_risk="medium",
    ),
    NodeSpecDef(
        type="finance.submit_expense", label="Submit expense", category="finance", kind="tool",
        description="Submits an expense reimbursement. Policy decides: auto-approve, human approval, or reject.",
        agent="finance", tool="erp_submit_expense",
        params=(
            Param("employee_id", "Employee ID"),
            Param("category", "Category", default="Travel / Meals"),
            Param("amount", "Amount (USD)", "number"),
            Param("receipt_attached", "Receipt attached", "boolean", default=True),
            Param("description", "Description", "text"),
        ),
        outputs=("id", "status", "amount", "category", "employee_id", "approved_by"),
        side_effect=True, default_risk="medium",
    ),
    NodeSpecDef(
        type="it.create_ticket", label="Create IT ticket", category="it", kind="tool",
        description="Opens an incident or provisioning ticket. SEV-1 tickets are escalated to SecOps.",
        agent="it", tool="ticketing_create_ticket",
        params=(
            Param("title", "Title"),
            Param("category", "Category", default="General Support"),
            Param("priority", "Priority", "select", default="medium", options=("low", "medium", "high", "critical")),
            Param("severity", "Severity", "select", default="SEV-3", options=("SEV-1", "SEV-2", "SEV-3")),
            Param("description", "Description", "text"),
        ),
        outputs=("id", "title", "category", "priority", "severity", "assigned_to", "status"),
        side_effect=True, default_risk="medium",
    ),
    NodeSpecDef(
        type="notify.send_email", label="Send notification", category="notify", kind="tool",
        description="Sends a stakeholder notification through the mock email service.",
        agent="it", tool="notifications_send_email",
        params=(Param("recipient", "Recipient"), Param("subject", "Subject"), Param("body", "Body", "text")),
        outputs=("status", "recipient", "subject", "timestamp"),
        side_effect=True, default_risk="medium",
    ),
]}


def catalog_json() -> list[dict]:
    out = []
    for n in CATALOG.values():
        out.append({
            "type": n.type, "label": n.label, "category": n.category, "kind": n.kind,
            "description": n.description, "agent": n.agent, "tool": n.tool,
            "side_effect": n.side_effect, "default_risk": n.default_risk,
            "allowed_roles": list(n.allowed_roles), "outputs": list(n.outputs),
            "params": [{"name": p.name, "label": p.label, "type": p.type, "required": p.required,
                        "default": p.default, "help": p.help, "options": list(p.options)} for p in n.params],
        })
    return out
