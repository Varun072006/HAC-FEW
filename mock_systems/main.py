"""
Mock Enterprise Systems API
Provides mock endpoints for HRMS, ERP (Finance), IT Ticketing, and Notification (Email).
Connected directly to SQLite / PostgreSQL database via SQLAlchemy.
"""
from fastapi import FastAPI, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from mock_systems.db import init_db, get_db
from mock_systems.models import Employee, ExpenseRecord, ITTicket, AuditLog

app = FastAPI(
    title="Mock Enterprise Systems (HRMS, ERP, Ticketing, Email)",
    version="1.0.0",
    description="Simulated backend microservices for Hierarchical Multi-Agent testing"
)

# Initialize schema on startup
@app.on_event("startup")
def on_startup():
    init_db()


# --- HRMS Endpoints ---
class EmployeeCreateRequest(BaseModel):
    name: str
    email: str
    department: str
    role: str
    start_date: str


@app.post("/hrms/employees", tags=["HRMS"], status_code=status.HTTP_201_CREATED)
def create_employee(req: EmployeeCreateRequest, db: Session = Depends(get_db)):
    # Check for existing email conflict
    existing = db.query(Employee).filter(Employee.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Employee with email {req.email} already exists")

    count = db.query(Employee).count()
    emp_id = f"EMP-{count + 1:03d}"
    new_emp = Employee(
        id=emp_id,
        name=req.name,
        email=req.email,
        department=req.department,
        role=req.role,
        status="onboarding",
        start_date=req.start_date
    )
    db.add(new_emp)
    db.commit()
    db.refresh(new_emp)
    return {
        "status": "success",
        "employee": {
            "id": new_emp.id,
            "name": new_emp.name,
            "email": new_emp.email,
            "department": new_emp.department,
            "role": new_emp.role,
            "status": new_emp.status,
            "start_date": new_emp.start_date
        }
    }


@app.get("/hrms/employees/{emp_id}", tags=["HRMS"])
def get_employee(emp_id: str, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {
        "id": emp.id,
        "name": emp.name,
        "email": emp.email,
        "department": emp.department,
        "role": emp.role,
        "status": emp.status,
        "start_date": emp.start_date
    }


# --- ERP (Finance) Endpoints ---
class PayrollSetupRequest(BaseModel):
    employee_id: str
    base_salary: float = 95000.0
    tax_bracket: str = "Standard"
    bank_account_last4: str = "1234"


class ExpenseSubmitRequest(BaseModel):
    employee_id: str
    category: str
    amount: float
    currency: str = "USD"
    receipt_attached: bool = True
    description: str


@app.post("/erp/payroll/setup", tags=["ERP-Finance"])
def setup_payroll(req: PayrollSetupRequest, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == req.employee_id).first()
    if not emp:
        raise HTTPException(status_code=400, detail="Invalid employee ID")
    return {
        "status": "success",
        "message": f"Payroll account active for {req.employee_id}",
        "setup_timestamp": datetime.utcnow().isoformat()
    }


@app.post("/erp/expenses/submit", tags=["ERP-Finance"])
def submit_expense(req: ExpenseSubmitRequest, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == req.employee_id).first()
    if not emp:
        raise HTTPException(status_code=400, detail="Invalid employee ID for expense")

    count = db.query(ExpenseRecord).count()
    exp_id = f"EXP-{count + 1:04d}"

    # Determine status based on financial rules
    if not req.receipt_attached:
        exp_status = "rejected"
    elif req.amount < 100.0:
        exp_status = "approved"
    else:
        exp_status = "awaiting_approval"

    record = ExpenseRecord(
        id=exp_id,
        employee_id=req.employee_id,
        category=req.category,
        amount=req.amount,
        currency=req.currency,
        receipt_attached=req.receipt_attached,
        description=req.description,
        status=exp_status
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "status": "success",
        "expense": {
            "id": record.id,
            "employee_id": record.employee_id,
            "category": record.category,
            "amount": record.amount,
            "status": record.status,
            "receipt_attached": record.receipt_attached
        }
    }


@app.get("/erp/expenses/{exp_id}", tags=["ERP-Finance"])
def get_expense(exp_id: str, db: Session = Depends(get_db)):
    rec = db.query(ExpenseRecord).filter(ExpenseRecord.id == exp_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Expense record not found")
    return {
        "id": rec.id,
        "employee_id": rec.employee_id,
        "category": rec.category,
        "amount": rec.amount,
        "status": rec.status,
        "receipt_attached": rec.receipt_attached,
        "description": rec.description
    }


# --- Ticketing & IT Endpoints ---
class TicketCreateRequest(BaseModel):
    title: str
    category: str
    priority: str = "medium"
    severity: str = "SEV-3"
    assigned_to: Optional[str] = "IT-Support"
    description: str


@app.post("/ticketing/tickets", tags=["Ticketing"])
def create_ticket(req: TicketCreateRequest, db: Session = Depends(get_db)):
    count = db.query(ITTicket).count()
    ticket_id = f"INC-{count + 1:04d}"
    assigned = "SecOps-Escalation" if req.severity == "SEV-1" else req.assigned_to

    ticket = ITTicket(
        id=ticket_id,
        title=req.title,
        category=req.category,
        priority=req.priority,
        severity=req.severity,
        assigned_to=assigned,
        description=req.description,
        status="open"
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return {
        "status": "success",
        "ticket": {
            "id": ticket.id,
            "title": ticket.title,
            "category": ticket.category,
            "priority": ticket.priority,
            "severity": ticket.severity,
            "assigned_to": ticket.assigned_to,
            "status": ticket.status
        }
    }


@app.get("/ticketing/tickets/{ticket_id}", tags=["Ticketing"])
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    t = db.query(ITTicket).filter(ITTicket.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {
        "id": t.id,
        "title": t.title,
        "category": t.category,
        "priority": t.priority,
        "severity": t.severity,
        "assigned_to": t.assigned_to,
        "status": t.status,
        "description": t.description
    }


# --- Mock Email / Notification Service ---
class EmailSendRequest(BaseModel):
    recipient: str
    subject: str
    body: str


@app.post("/notifications/email", tags=["Notifications"])
def send_email(req: EmailSendRequest):
    return {
        "status": "sent",
        "recipient": req.recipient,
        "subject": req.subject,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
    return {
        "status": "healthy",
        "database_counts": {
            "employees": db.query(Employee).count(),
            "expenses": db.query(ExpenseRecord).count(),
            "tickets": db.query(ITTicket).count()
        }
    }
