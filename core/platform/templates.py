"""Workflow templates. Each one is a plain definition built only from catalog nodes."""
from typing import Optional


def _n(node_id, type_, x, y, params=None, label=None):
    return {"id": node_id, "type": type_, "label": label, "position": {"x": x, "y": y}, "params": params or {}}


def _e(source, target):
    return {"id": f"{source}->{target}", "source": source, "target": target}


TEMPLATES = [
    {
        "id": "expense-approval",
        "name": "Expense reimbursement",
        "description": "Looks up the expense policy, then submits the claim. Policy auto-approves small claims, "
                       "routes mid-size claims to a manager, and requires Director + Controller for large ones.",
        "definition": {
            "nodes": [
                _n("trigger", "trigger.manual", 0, 120, {"fields": [
                    {"name": "employee_id", "type": "string", "required": True, "default": "EMP-001"},
                    {"name": "amount", "type": "number", "required": True},
                    {"name": "receipt_attached", "type": "boolean", "required": True, "default": True},
                    {"name": "description", "type": "string", "required": True},
                ]}, "Request"),
                _n("policy", "policy.search", 300, 120, {
                    "agent": "finance", "query": "expense reimbursement threshold approval receipts"}, "Expense policy"),
                _n("submit", "finance.submit_expense", 620, 120, {
                    "employee_id": "{{trigger.employee_id}}", "category": "Travel / Meals",
                    "amount": "{{trigger.amount}}", "receipt_attached": "{{trigger.receipt_attached}}",
                    "description": "{{trigger.description}}"}, "Submit expense"),
            ],
            "edges": [_e("trigger", "policy"), _e("policy", "submit")],
        },
    },
    {
        "id": "employee-onboarding",
        "name": "Employee onboarding",
        "description": "Creates the HR record, then provisions payroll and a laptop ticket from the new employee ID.",
        "definition": {
            "nodes": [
                _n("trigger", "trigger.manual", 0, 160, {"fields": [
                    {"name": "name", "type": "string", "required": True},
                    {"name": "email", "type": "string", "required": True},
                    {"name": "department", "type": "string", "required": True, "default": "Engineering"},
                    {"name": "role", "type": "string", "required": True, "default": "Software Engineer"},
                ]}, "New hire"),
                _n("hr", "hr.create_employee", 300, 160, {
                    "name": "{{trigger.name}}", "email": "{{trigger.email}}",
                    "department": "{{trigger.department}}", "role": "{{trigger.role}}",
                    "start_date": "2026-11-01"}, "Register employee"),
                _n("payroll", "finance.setup_payroll", 620, 60, {
                    "employee_id": "{{nodes.hr.output.id}}", "base_salary": 95000}, "Payroll setup"),
                _n("laptop", "it.create_ticket", 620, 260, {
                    "title": "Provision laptop for {{trigger.name}}", "category": "Hardware/Provisioning",
                    "priority": "medium", "severity": "SEV-3",
                    "description": "Configure laptop and accounts for {{nodes.hr.output.id}}."}, "Laptop ticket"),
            ],
            "edges": [_e("trigger", "hr"), _e("hr", "payroll"), _e("hr", "laptop")],
        },
    },
    {
        "id": "it-incident-triage",
        "name": "IT incident triage",
        "description": "Retrieves the incident severity policy, opens a ticket, and notifies stakeholders.",
        "definition": {
            "nodes": [
                _n("trigger", "trigger.manual", 0, 120, {"fields": [
                    {"name": "summary", "type": "string", "required": True},
                    {"name": "severity", "type": "string", "required": True, "default": "SEV-3"},
                ]}, "Incident report"),
                _n("policy", "policy.search", 300, 120, {
                    "agent": "it", "query": "incident severity classification SLA {{trigger.summary}}"}, "Severity policy"),
                _n("ticket", "it.create_ticket", 620, 120, {
                    "title": "{{trigger.summary}}", "category": "General Support", "priority": "high",
                    "severity": "{{trigger.severity}}", "description": "{{trigger.summary}}"}, "Open ticket"),
                _n("notify", "notify.send_email", 940, 120, {
                    "recipient": "oncall@company.test", "subject": "Incident {{nodes.ticket.output.id}} opened",
                    "body": "{{trigger.summary}}"}, "Notify on-call"),
            ],
            "edges": [_e("trigger", "policy"), _e("policy", "ticket"), _e("ticket", "notify")],
        },
    },
]


def get_template(template_id: str) -> Optional[dict]:
    return next((t for t in TEMPLATES if t["id"] == template_id), None)
