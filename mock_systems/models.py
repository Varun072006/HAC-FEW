from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Employee(Base):
    __tablename__ = "employees"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    department = Column(String(50), nullable=False)
    role = Column(String(100), nullable=False)
    status = Column(String(50), default="active")
    start_date = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExpenseRecord(Base):
    __tablename__ = "expenses"

    id = Column(String(50), primary_key=True)
    employee_id = Column(String(50), nullable=False)
    category = Column(String(100), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    receipt_attached = Column(Boolean, default=True)
    description = Column(Text, nullable=False)
    status = Column(String(50), default="submitted")  # submitted, approved, rejected, awaiting_approval
    approved_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ITTicket(Base):
    __tablename__ = "tickets"

    id = Column(String(50), primary_key=True)
    title = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    priority = Column(String(50), default="medium")  # low, medium, high, critical
    severity = Column(String(50), default="SEV-3")   # SEV-1, SEV-2, SEV-3
    assigned_to = Column(String(100), default="IT-Support")
    description = Column(Text, nullable=False)
    status = Column(String(50), default="open")      # open, in_progress, resolved, closed
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    actor_agent = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    target_system = Column(String(50), nullable=False)
    payload_json = Column(Text, nullable=False)
    risk_level = Column(String(20), default="low")
    status = Column(String(50), default="success")
    reason = Column(Text, nullable=True)
