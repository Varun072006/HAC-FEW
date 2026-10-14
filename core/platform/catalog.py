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
    type: str = "string"            # string | text | number | boolean | select | fields | json
    required: bool = True
    default: object = None
    help: str = ""
    options: tuple = ()


@dataclass(frozen=True)
class NodeSpecDef:
    type: str
    label: str
    category: str                   # trigger | knowledge | hr | finance | it | notify | agent | data | audit | control
    kind: str                       # trigger | rag | tool | agent | flow | approval
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
        type="agent.task", label="Agent task", category="agent", kind="agent",
        description="Delegates a task to a configured agent. The agent may only use the tools in its registry "
                    "entry, and every tool call still passes validation, policy and approval.",
        agent=None, tool=None,
        params=(
            Param("agent_id", "Agent", "string", help="Id of an active specialist or coordinator in the agent registry."),
            Param("objective", "Objective", "text", help="What this task must accomplish. Supports {{...}} references."),
            Param("operations", "Operations", "json", required=False, default=[],
                  help='Scripted tool calls: [{"tool": "...", "arguments": {...}}]. Leave empty to let a '
                       "model-backed agent decide, within its allowed tools."),
            Param("inputs", "Context inputs", "json", required=False, default={},
                  help='Named upstream values shared with a model-backed agent, e.g. {"policy": "{{nodes.policy.output.result.context}}"}.'),
            Param("criticality", "Criticality", "select", default="required", options=("required", "optional"),
                  help="An optional task may fail without failing the run; its dependents are skipped."),
            Param("complexity", "Complexity", "select", default="medium", options=("low", "medium", "high"),
                  help="Selects the agent's small, default or large model tier."),
            Param("require_evidence", "Require evidence", "boolean", required=False, default=False,
                  help="Fail with 'insufficient evidence' unless a tool returned citations or record ids."),
            Param("required_capabilities", "Required capabilities", "json", required=False, default=[]),
            Param("completion_criteria", "Completion criteria", "json", required=False, default=[]),
            Param("expected_output", "Expected output keys", "json", required=False, default=[],
                  help="Top-level keys the task output must contain (e.g. [\"result\"])."),
            Param("timeout_s", "Timeout (s)", "number", required=False, default=None),
        ),
        outputs=("result", "results", "summary", "evidence"),
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


# ---------------------------------------------------------------- business automation nodes
# Tool-backed nodes map one-to-one onto a governed tool (core/platform/tools_automation.py): param names ARE the tool's
# argument names, `agent` is the registry agent that performs it, and `outputs` is the typed contract later nodes may
# reference (the validator rejects references to fields that are not declared here).
_AUDIT = ("manager", "director", "controller", "admin")
_AUDIT_SCHEMA_DEFAULT = {
    "required_columns": ["txn_id", "date", "vendor", "amount"],
    "columns": {
        "txn_id": {"type": "string", "required": True, "unique": True, "max_length": 40},
        "date": {"type": "date", "required": True, "not_future": True},
        "vendor": {"type": "string", "required": True, "max_length": 120},
        "department": {"type": "string", "max_length": 80},
        "category": {"type": "string", "max_length": 80},
        "amount": {"type": "decimal", "required": True, "min": "-10000000", "max": "10000000"},
        "currency": {"type": "string", "allowed": ["USD", "EUR", "GBP", "INR"]},
        "approved_by": {"type": "string", "max_length": 80},
        "receipt_id": {"type": "string", "max_length": 60},
    },
    "max_invalid_ratio": 0.5,
}
CONDITION_OPERATORS = ("eq", "ne", "gt", "gte", "lt", "lte", "contains", "is_true", "is_false")

CATALOG.update({n.type: n for n in [
    NodeSpecDef(
        type="file.read_table", label="Read Excel / CSV", category="data", kind="tool",
        description="Opens an uploaded .xlsx or .csv file and reports its sheet, columns and row count. Reads only; nothing is changed.",
        agent="data_validation_specialist", tool="file_read_table",
        params=(Param("file_id", "File", help="Usually {{trigger.<file field>}}. The file must be one you uploaded."),
                Param("sheet", "Sheet", required=False, help="Leave blank for the first sheet. CSV files have a single sheet.")),
        outputs=("file_id", "name", "sheet", "sheets", "columns", "row_count", "header_row", "preview", "source_sha256", "evidence"),
        allowed_roles=_AUDIT, default_risk="low",
    ),
    NodeSpecDef(
        type="data.validate", label="Validate data", category="data", kind="tool",
        description="Checks the sheet against a schema (required columns, types, ranges, duplicates). Bad rows are quarantined with their row "
                    "numbers; missing required columns stop the workflow.",
        agent="data_validation_specialist", tool="data_validate",
        params=(Param("file_id", "File", help="Usually {{nodes.<read step>.output.file_id}}."),
                Param("sheet", "Sheet", required=False, help="Usually {{nodes.<read step>.output.sheet}}."),
                Param("schema", "Schema", "json", required=False, default=_AUDIT_SCHEMA_DEFAULT,
                      help="required_columns, columns {type, required, unique, allowed, min, max, max_length, not_future}, max_invalid_ratio.")),
        outputs=("dataset_file_id", "rows_read", "rows_valid", "rows_quarantined", "error_total", "errors", "quarantined_rows", "columns", "source", "evidence"),
        allowed_roles=_AUDIT, default_risk="medium",
    ),
    NodeSpecDef(
        type="audit.analyze", label="Analyze discrepancies", category="audit", kind="tool",
        description="Applies deterministic audit rules (missing approval or receipt, duplicates, split payments, outliers, control totals). "
                    "Every finding lists the source rows it came from.",
        agent="audit_analysis_specialist", tool="audit_analyze",
        params=(Param("dataset_file_id", "Validated dataset", help="Usually {{nodes.<validate step>.output.dataset_file_id}}."),
                Param("rules", "Rule thresholds", "json", required=False,
                      default={"approval_threshold": 1000, "receipt_threshold": 75, "duplicate_window_days": 3, "outlier_z": 3.0, "outlier_min_group": 8},
                      help="Thresholds apply to the stated amount; there is no currency conversion."),
                Param("expected_total", "Control total", "number", required=False, help="If set, the dataset total must match exactly."),
                Param("expected_count", "Control row count", "number", required=False)),
        outputs=("findings_file_id", "findings_count", "high_count", "medium_count", "low_count", "total_exposure", "total_amount",
                 "rows_analyzed", "top_findings", "source", "evidence"),
        allowed_roles=_AUDIT, default_risk="medium",
    ),
    NodeSpecDef(
        type="flow.condition", label="Route by condition", category="control", kind="flow",
        description="Sends the run down its true or false branch. Connect each output to the steps for that branch; steps on the other "
                    "branch are skipped (not failed).",
        agent=None, tool=None,
        params=(Param("left", "Value", help="A reference such as {{nodes.<step>.output.findings_count}}."),
                Param("operator", "Operator", "select", default="gt", options=CONDITION_OPERATORS),
                Param("right", "Compare to", required=False, default="0", help="A literal or a reference. Not used by is_true / is_false.")),
        outputs=("result", "branch", "left", "operator", "right"),
        allowed_roles=_AUDIT, default_risk="low",
    ),
    NodeSpecDef(
        type="report.generate", label="Generate audit report", category="audit", kind="tool",
        description="Renders the audit report (HTML) and a findings CSV from the analysis. Reports are always stored as confidential.",
        agent="report_generation_specialist", tool="report_generate",
        params=(Param("findings_file_id", "Findings", help="{{nodes.<analyze step>.output.findings_file_id}}"),
                Param("dataset_file_id", "Validated dataset", help="{{nodes.<validate step>.output.dataset_file_id}}"),
                Param("title", "Report title", default="Audit report"),
                Param("prepared_for", "Prepared for", required=False, default="Audit committee"),
                Param("narrative", "AI narrative", "text", required=False, help="Optional text written by a model-backed step. Must cite real finding ids."),
                Param("narrative_cites", "Narrative cites", "json", required=False, default=[])),
        outputs=("report_file_id", "report_sha256", "csv_file_id", "csv_sha256", "findings_count", "high_count", "medium_count", "low_count",
                 "title", "size", "sensitivity", "evidence"),
        allowed_roles=_AUDIT, default_risk="medium",
    ),
    NodeSpecDef(
        type="approval.human", label="Human approval", category="control", kind="approval",
        description="Pauses the run until the configured approvers decide. The approval is bound to the report content listed under Subject, "
                    "so a changed report can no longer be sent on the strength of it.",
        agent=None, tool=None,
        params=(Param("title", "Title", default="Approve audit report"),
                Param("instructions", "Instructions for approvers", "text", required=False, default="Review the report before it is sent."),
                Param("approver_roles", "Approver roles", "json", default=[["director", "controller", "admin"]],
                      help="One list per required approval; any role in a list can fill it. Example: [[\"director\"],[\"controller\"]] needs both."),
                Param("subject", "Subject", "json", required=False, default={},
                      help="What is being approved. Keys ending in _sha256 bind the approval to that exact content.")),
        outputs=("approved", "approval_id", "approved_by", "decided_at", "bound", "evidence"),
        allowed_roles=_AUDIT, default_risk="medium",
    ),
    NodeSpecDef(
        type="email.send", label="Send email", category="notify", kind="tool",
        description="Sends a message with files generated by this run. A confidential report is only sent if a review gate approved that exact "
                    "content; otherwise the send itself waits for approval. Uses the mock mailbox unless real SMTP is configured on the server.",
        agent="audit_coordinator", tool="email_send", side_effect=True,
        params=(Param("to", "To", help="Comma-separated addresses."),
                Param("subject", "Subject"),
                Param("body", "Message", "text", required=False),
                Param("attachments", "Attachments", "json", required=False, default=[], help="File ids from earlier steps, e.g. [\"{{nodes.report.output.report_file_id}}\"]."),
                Param("approval_id", "Approval", required=False, help="{{nodes.<approval step>.output.approval_id}}")),
        outputs=("delivery_id", "status", "mode", "recipients", "message_id", "attempts", "attachment_ids", "evidence"),
        allowed_roles=_AUDIT, default_risk="high",
    ),
    NodeSpecDef(
        type="log.record", label="Record result", category="control", kind="tool",
        description="Writes the workflow's outcome, report reference and delivery status onto the run record and the audit trail.",
        agent="audit_coordinator", tool="run_record_result",
        params=(Param("outcome", "Outcome", "select", default="completed", options=("delivered", "no_findings", "failed", "completed")),
                Param("summary", "Summary", "text", required=False),
                Param("data", "Extra data", "json", required=False, default={})),
        outputs=("recorded", "outcome", "result", "evidence"),
        allowed_roles=_AUDIT, default_risk="low",
    ),
]})


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
