"""
Seed script to generate:
- ~200 employees
- ~500 expenses
- ~300 IT tickets
as specified in Section 7 of the Build Plan.
"""
import random
from datetime import datetime, timedelta
from mock_systems.db import init_db, SessionLocal
from mock_systems.models import Employee, ExpenseRecord, ITTicket, AuditLog

DEPARTMENTS = ["Engineering", "Finance", "HR", "IT", "Operations", "Marketing", "Legal"]
ROLES = {
    "Engineering": ["Junior Backend Engineer", "Senior Backend Engineer", "Staff Engineer", "Frontend Developer", "DevOps Engineer"],
    "Finance": ["Financial Analyst", "Accountant", "Payroll Specialist", "Finance Controller"],
    "HR": ["HR Coordinator", "Talent Acquisition Specialist", "HR Business Partner", "People Operations Director"],
    "IT": ["IT Support Technician", "Systems Administrator", "Network Engineer", "SecOps Analyst"],
    "Operations": ["Operations Associate", "Supply Chain Manager", "Project Coordinator"],
    "Marketing": ["Content Strategist", "Growth Marketing Lead", "Product Marketer"],
    "Legal": ["Corporate Counsel", "Compliance Officer", "Legal Operations Lead"]
}

FIRST_NAMES = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth", 
               "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen",
               "Christopher", "Nancy", "Daniel", "Lisa", "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
              "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"]

EXPENSE_CATEGORIES = [
    ("Travel / Airfare", 150.0, 1500.0),
    ("Meals / Team Dinner", 25.0, 400.0),
    ("Software Subscription", 15.0, 300.0),
    ("Office Supplies", 10.0, 120.0),
    ("Hardware Peripheral", 40.0, 250.0),
    ("Client Entertainment", 80.0, 600.0)
]

TICKET_TEMPLATES = [
    ("VPN connection dropping", "Network/VPN", "high", "SEV-2"),
    ("Monitor display flickering when waking from sleep", "Hardware", "low", "SEV-3"),
    ("Password reset request", "Identity/Access", "low", "SEV-3"),
    ("Provision new development laptop", "Hardware/Provisioning", "medium", "SEV-3"),
    ("Production database replica unresponsive", "Infrastructure", "critical", "SEV-1"),
    ("Slack app access permission", "Software/Access", "low", "SEV-3"),
    ("Email phishing attempt report", "Security", "high", "SEV-2"),
    ("Docking station port defect", "Hardware", "low", "SEV-3"),
    ("Git repository commit access", "Identity/Access", "low", "SEV-3"),
    ("Company portal 500 error", "Software/Web", "medium", "SEV-2")
]


def seed_database(num_employees=200, num_expenses=500, num_tickets=300):
    init_db()
    db = SessionLocal()

    # Clear existing data for idempotent re-seed
    db.query(AuditLog).delete()
    db.query(ExpenseRecord).delete()
    db.query(ITTicket).delete()
    db.query(Employee).delete()
    db.commit()

    print(f"[*] Generating {num_employees} employees...")
    employees = []
    start_base = datetime(2023, 1, 1)
    
    for i in range(1, num_employees + 1):
        emp_id = f"EMP-{i:03d}"
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        name = f"{fn} {ln}"
        email = f"{fn.lower()}.{ln.lower()}{i}@company.test"
        dept = random.choice(DEPARTMENTS)
        role = random.choice(ROLES[dept])
        start_date = (start_base + timedelta(days=random.randint(0, 1000))).strftime("%Y-%m-%d")
        
        emp = Employee(
            id=emp_id,
            name=name,
            email=email,
            department=dept,
            role=role,
            status="active" if i > 5 else "onboarding",
            start_date=start_date
        )
        employees.append(emp)
        db.add(emp)

    db.commit()
    print(f"[+] Successfully seeded {len(employees)} employees.")

    print(f"[*] Generating {num_expenses} expenses...")
    for i in range(1, num_expenses + 1):
        exp_id = f"EXP-{i:04d}"
        emp = random.choice(employees)
        cat_info = random.choice(EXPENSE_CATEGORIES)
        cat_name = cat_info[0]
        amount = round(random.uniform(cat_info[1], cat_info[2]), 2)
        has_receipt = random.random() > 0.05  # 95% have receipts
        
        status = "submitted"
        if amount < 100.0:
            status = "approved" if has_receipt else "rejected"
        elif amount > 1000.0:
            status = random.choice(["awaiting_approval", "approved", "rejected"])
        else:
            status = random.choice(["approved", "awaiting_approval"])

        record = ExpenseRecord(
            id=exp_id,
            employee_id=emp.id,
            category=cat_name,
            amount=amount,
            currency="USD",
            receipt_attached=has_receipt,
            description=f"Business expense for {cat_name.lower()} during Q{random.randint(1, 4)}",
            status=status,
            approved_by="Manager-Auto" if status == "approved" and amount < 100 else ("Department Director" if status == "approved" else None)
        )
        db.add(record)

    db.commit()
    print(f"[+] Successfully seeded {num_expenses} expense records.")

    print(f"[*] Generating {num_tickets} IT tickets...")
    for i in range(1, num_tickets + 1):
        t_id = f"INC-{i:04d}"
        template = random.choice(TICKET_TEMPLATES)
        emp = random.choice(employees)
        
        ticket = ITTicket(
            id=t_id,
            title=f"{template[0]} (reported by {emp.name})",
            category=template[1],
            priority=template[2],
            severity=template[3],
            assigned_to="IT-Support" if template[3] != "SEV-1" else "SecOps-Escalation",
            description=f"Ticket details: {template[0]}. Requested by {emp.id} in {emp.department}.",
            status=random.choice(["open", "in_progress", "resolved", "closed"])
        )
        db.add(ticket)

    db.commit()
    print(f"[+] Successfully seeded {num_tickets} IT tickets.")
    db.close()
    print("[+] Database seeding complete!")


if __name__ == "__main__":
    seed_database()
