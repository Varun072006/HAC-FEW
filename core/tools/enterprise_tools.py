"""
Typed Enterprise Tools wrapping Mock ERP, HRMS, and Ticketing systems.
Enforces:
- Separation of Read tools vs Write tools
- Pydantic input/output schemas
- Allow-list assignment per agent role
- Governance policy checks on every write
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import httpx
from fastapi.testclient import TestClient

from core.governance.policy_engine import GovernancePolicyEngine, GovernanceDecision
from mock_systems.main import app as mock_app

# Using FastAPI TestClient to execute mock calls in-process without requiring background server
mock_client = TestClient(mock_app)


class ToolExecutionResponse(BaseModel):
    success: bool
    tool_name: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    policy_decision: Optional[GovernanceDecision] = None
    audit_logged: bool = True


# ==========================================
# 1. HR Tools
# ==========================================
class HRCreateEmployeeInput(BaseModel):
    name: str
    email: str
    department: str
    role: str
    start_date: str = "2026-11-01"


class HRGetEmployeeInput(BaseModel):
    emp_id: str


def hrms_create_employee(agent: str, params: Dict[str, Any]) -> ToolExecutionResponse:
    # Governance Check
    decision = GovernancePolicyEngine.evaluate_tool_execution(agent, "hrms_create_employee", params)
    if not decision.allowed:
        return ToolExecutionResponse(success=False, tool_name="hrms_create_employee", error=decision.reason, policy_decision=decision)

    res = mock_client.post("/hrms/employees", json=params)
    if res.status_code == 201:
        data = res.json()["employee"]
        GovernancePolicyEngine.log_audit_event(
            actor_agent=agent, action="hrms_create_employee", target_system="HRMS",
            payload=params, risk_level=decision.risk_level.value, status="success"
        )
        return ToolExecutionResponse(success=True, tool_name="hrms_create_employee", data=data, policy_decision=decision)
    else:
        err = res.json().get("detail", "Failed to create employee")
        GovernancePolicyEngine.log_audit_event(
            actor_agent=agent, action="hrms_create_employee", target_system="HRMS",
            payload=params, risk_level=decision.risk_level.value, status="failed", reason=err
        )
        return ToolExecutionResponse(success=False, tool_name="hrms_create_employee", error=err, policy_decision=decision)


def hrms_get_employee(agent: str, params: Dict[str, Any]) -> ToolExecutionResponse:
    emp_id = params.get("emp_id")
    res = mock_client.get(f"/hrms/employees/{emp_id}")
    if res.status_code == 200:
        return ToolExecutionResponse(success=True, tool_name="hrms_get_employee", data=res.json())
    return ToolExecutionResponse(success=False, tool_name="hrms_get_employee", error=f"Employee {emp_id} not found")


# ==========================================
# 2. Finance Tools
# ==========================================
class ERPExpenseSubmitInput(BaseModel):
    employee_id: str
    category: str
    amount: float
    receipt_attached: bool = True
    description: str


class ERPPayrollSetupInput(BaseModel):
    employee_id: str
    base_salary: float = 95000.0


def erp_submit_expense(agent: str, params: Dict[str, Any]) -> ToolExecutionResponse:
    decision = GovernancePolicyEngine.evaluate_tool_execution(agent, "erp_submit_expense", params)
    if not decision.allowed:
        return ToolExecutionResponse(success=False, tool_name="erp_submit_expense", error=decision.reason, policy_decision=decision)

    if decision.requires_human_approval:
        # Route to approval state
        GovernancePolicyEngine.log_audit_event(
            actor_agent=agent, action="erp_submit_expense", target_system="ERP-Finance",
            payload=params, risk_level=decision.risk_level.value, status="awaiting_approval", reason=decision.reason
        )
        return ToolExecutionResponse(
            success=True,
            tool_name="erp_submit_expense",
            data={"status": "awaiting_approval", "approver": decision.suggested_approver, "details": params},
            policy_decision=decision
        )

    res = mock_client.post("/erp/expenses/submit", json=params)
    if res.status_code == 200:
        data = res.json()["expense"]
        GovernancePolicyEngine.log_audit_event(
            actor_agent=agent, action="erp_submit_expense", target_system="ERP-Finance",
            payload=params, risk_level=decision.risk_level.value, status="auto_approved"
        )
        return ToolExecutionResponse(success=True, tool_name="erp_submit_expense", data=data, policy_decision=decision)
    return ToolExecutionResponse(success=False, tool_name="erp_submit_expense", error=res.json().get("detail", "Error"))


def erp_setup_payroll(agent: str, params: Dict[str, Any]) -> ToolExecutionResponse:
    decision = GovernancePolicyEngine.evaluate_tool_execution(agent, "erp_setup_payroll", params)
    if not decision.allowed:
        return ToolExecutionResponse(success=False, tool_name="erp_setup_payroll", error=decision.reason, policy_decision=decision)

    res = mock_client.post("/erp/payroll/setup", json=params)
    if res.status_code == 200:
        return ToolExecutionResponse(success=True, tool_name="erp_setup_payroll", data=res.json(), policy_decision=decision)
    return ToolExecutionResponse(success=False, tool_name="erp_setup_payroll", error=res.json().get("detail", "Error"))


# ==========================================
# 3. IT Tools
# ==========================================
class ITTicketCreateInput(BaseModel):
    title: str
    category: str
    priority: str = "medium"
    severity: str = "SEV-3"
    description: str


def ticketing_create_ticket(agent: str, params: Dict[str, Any]) -> ToolExecutionResponse:
    decision = GovernancePolicyEngine.evaluate_tool_execution(agent, "ticketing_create_ticket", params)
    if not decision.allowed:
        return ToolExecutionResponse(success=False, tool_name="ticketing_create_ticket", error=decision.reason, policy_decision=decision)

    res = mock_client.post("/ticketing/tickets", json=params)
    if res.status_code == 200:
        data = res.json()["ticket"]
        GovernancePolicyEngine.log_audit_event(
            actor_agent=agent, action="ticketing_create_ticket", target_system="IT-Ticketing",
            payload=params, risk_level=decision.risk_level.value, status="success"
        )
        return ToolExecutionResponse(success=True, tool_name="ticketing_create_ticket", data=data, policy_decision=decision)
    return ToolExecutionResponse(success=False, tool_name="ticketing_create_ticket", error=res.json().get("detail", "Error"))


def notifications_send_email(agent: str, params: Dict[str, Any]) -> ToolExecutionResponse:
    decision = GovernancePolicyEngine.evaluate_tool_execution(agent, "notifications_send_email", params)
    if not decision.allowed:
        return ToolExecutionResponse(success=False, tool_name="notifications_send_email", error=decision.reason, policy_decision=decision)

    res = mock_client.post("/notifications/email", json=params)
    if res.status_code == 200:
        return ToolExecutionResponse(success=True, tool_name="notifications_send_email", data=res.json(), policy_decision=decision)
    return ToolExecutionResponse(success=False, tool_name="notifications_send_email", error="Email failure")


# Tool Registry
TOOL_REGISTRY = {
    "hrms_create_employee": hrms_create_employee,
    "hrms_get_employee": hrms_get_employee,
    "erp_submit_expense": erp_submit_expense,
    "erp_setup_payroll": erp_setup_payroll,
    "ticketing_create_ticket": ticketing_create_ticket,
    "notifications_send_email": notifications_send_email
}
