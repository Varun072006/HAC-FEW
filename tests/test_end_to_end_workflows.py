"""
End-to-End integration tests for all 3 Flagship Workflows and Governance Gates.
"""
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from mock_systems.db import SessionLocal
from mock_systems.models import AuditLog

client = TestClient(app)


def test_api_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["gateway"] == "active"


import uuid

def test_workflow_employee_onboarding_e2e():
    """Flagship Workflow 1: Onboard new engineer (HR -> IT & Finance)"""
    test_email = f"elena.{uuid.uuid4().hex[:6]}@company.test"
    payload = {
        "user_id": "manager_001",
        "role": "manager",
        "request": f"Please onboard Elena Rostova ({test_email}) as Staff Frontend Engineer in Engineering. Set up payroll and assign laptop."
    }
    res = client.post("/workflows/run", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert len(data["subtask_results"]) == 3

    # Check that HR employee was created
    hr_task = next(t for t in data["subtask_results"] if t["task_id"] == "task_hr_01")
    assert hr_task["status"] == "completed"
    assert "EMP-" in hr_task["output"]["id"]

    # Check IT laptop ticket created
    it_task = next(t for t in data["subtask_results"] if t["task_id"] == "task_it_01")
    assert it_task["status"] == "completed"
    assert "INC-" in it_task["output"]["id"]

    # Check Finance payroll setup
    fin_task = next(t for t in data["subtask_results"] if t["task_id"] == "task_fin_01")
    assert fin_task["status"] == "completed"


def test_workflow_low_value_expense_auto_approved():
    """Flagship Workflow 2a: Low-value expense (< $100) auto-approved"""
    payload = {
        "user_id": "EMP-001",
        "role": "employee",
        "request": "Submit expense reimbursement for EMP-001: $45.00 for client coffee with receipt attached."
    }
    res = client.post("/workflows/run", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    
    fin_submit = next(t for t in data["subtask_results"] if t["task_id"] == "task_fin_submit")
    assert fin_submit["output"]["status"] == "approved"


def test_workflow_moderate_value_expense_requires_approval():
    """Flagship Workflow 2b: Moderate-value expense ($100 - $1,000) line manager gate"""
    payload = {
        "user_id": "EMP-001",
        "role": "employee",
        "request": "Submit expense reimbursement for EMP-001: $350.00 for client dinner. Receipt attached."
    }
    res = client.post("/workflows/run", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "awaiting_human_approval"
    
    fin_submit = next(t for t in data["subtask_results"] if t["task_id"] == "task_fin_submit")
    assert fin_submit["output"]["status"] == "awaiting_approval"
    assert fin_submit["output"]["approver"] == "Line_Manager"


def test_workflow_high_value_expense_dual_approval():
    """Flagship Workflow 2c: High-value expense (> $1,000) dual approval gate"""
    payload = {
        "user_id": "EMP-001",
        "role": "employee",
        "request": "Submit expense reimbursement for EMP-001: $2,400.00 for annual tech conference. Receipt attached."
    }
    res = client.post("/workflows/run", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "awaiting_human_approval"
    
    fin_submit = next(t for t in data["subtask_results"] if t["task_id"] == "task_fin_submit")
    assert fin_submit["output"]["approver"] == "Director_and_Controller"


def test_workflow_expense_missing_receipt_rejected():
    """Flagship Workflow 2d: Missing receipt policy violation rejection"""
    payload = {
        "user_id": "EMP-001",
        "role": "employee",
        "request": "Submit expense reimbursement for EMP-001: $85.00 for taxi fare without receipt."
    }
    res = client.post("/workflows/run", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed_with_errors"
    fin_submit = next(t for t in data["subtask_results"] if t["task_id"] == "task_fin_submit")
    assert fin_submit["status"] == "failed"
    assert "Policy Violation" in fin_submit["error_message"]


def test_workflow_it_incident_triage():
    """Flagship Workflow 3: IT Incident triage with policy RAG and ticket creation"""
    payload = {
        "user_id": "user_it",
        "role": "it_admin",
        "request": "Critical alert: Total production database outage across all zones. Customers 500 error."
    }
    res = client.post("/workflows/run", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"

    it_ticket = next(t for t in data["subtask_results"] if t["task_id"] == "task_it_ticket")
    assert it_ticket["status"] == "completed"
    assert it_ticket["output"]["severity"] == "SEV-1"
    assert it_ticket["output"]["assigned_to"] == "SecOps-Escalation"


def test_audit_log_records():
    """Verify that immutable audit logs were recorded for mutating writes"""
    db = SessionLocal()
    audit_count = db.query(AuditLog).count()
    db.close()
    assert audit_count > 0
