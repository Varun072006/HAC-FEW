"""
Unit tests for Mock Enterprise Systems API (HRMS, ERP, Ticketing, Email).
"""
import pytest
from fastapi.testclient import TestClient
from mock_systems.main import app

import uuid

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database_counts"]["employees"] >= 200
    assert data["database_counts"]["expenses"] >= 500
    assert data["database_counts"]["tickets"] >= 300


def test_hrms_create_and_get_employee():
    unique_email = f"sarah.{uuid.uuid4().hex[:6]}@company.test"
    payload = {
        "name": "Sarah Connor",
        "email": unique_email,
        "department": "Engineering",
        "role": "Security Specialist",
        "start_date": "2026-11-01"
    }
    res = client.post("/hrms/employees", json=payload)
    assert res.status_code == 201
    created = res.json()["employee"]
    emp_id = created["id"]
    assert created["name"] == "Sarah Connor"
    assert created["status"] == "onboarding"

    # Fetch created
    get_res = client.get(f"/hrms/employees/{emp_id}")
    assert get_res.status_code == 200
    assert get_res.json()["email"] == payload["email"]


def test_hrms_duplicate_email_conflict():
    unique_email = f"dup.{uuid.uuid4().hex[:6]}@company.test"
    payload = {
        "name": "Sarah Original",
        "email": unique_email,
        "department": "Engineering",
        "role": "Security Specialist",
        "start_date": "2026-11-01"
    }
    first_res = client.post("/hrms/employees", json=payload)
    assert first_res.status_code == 201

    # Second attempt with same email must fail with 400
    res = client.post("/hrms/employees", json=payload)
    assert res.status_code == 400


def test_erp_payroll_setup():
    res = client.post("/erp/payroll/setup", json={
        "employee_id": "EMP-001",
        "base_salary": 110000.0,
        "tax_bracket": "Tier 2",
        "bank_account_last4": "5566"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "success"


def test_erp_expense_submit():
    res = client.post("/erp/expenses/submit", json={
        "employee_id": "EMP-001",
        "category": "Travel / Airfare",
        "amount": 45.0,
        "currency": "USD",
        "receipt_attached": True,
        "description": "Airport taxi fare"
    })
    assert res.status_code == 200
    exp = res.json()["expense"]
    assert exp["status"] == "approved"  # < 100 auto-approved


def test_ticketing_create_and_get():
    res = client.post("/ticketing/tickets", json={
        "title": "VPN Outage Unit Test",
        "category": "Network/VPN",
        "priority": "critical",
        "severity": "SEV-1",
        "assigned_to": "IT-Support",
        "description": "Global VPN failure"
    })
    assert res.status_code == 200
    ticket = res.json()["ticket"]
    assert ticket["severity"] == "SEV-1"
    assert ticket["assigned_to"] == "SecOps-Escalation"

    # Get ticket
    t_id = ticket["id"]
    get_res = client.get(f"/ticketing/tickets/{t_id}")
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "VPN Outage Unit Test"


def test_notification_email():
    res = client.post("/notifications/email", json={
        "recipient": "admin@company.test",
        "subject": "System Notice",
        "body": "Test alert"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "sent"
