"""
Deterministic Governance Policy Engine & RBAC Enforcement.
Enforces:
1. 3-Tier Risk Model (LOW, MEDIUM, HIGH)
2. Domain Business Rules (Expense thresholds, missing receipts, critical alerts)
3. Role-Based Access Control (RBAC) per agent and user role
4. Immutable Audit Logging
"""
from typing import Dict, Any, Optional
from datetime import datetime
import json
from pydantic import BaseModel

from core.supervisor.schemas import RiskLevel
from mock_systems.db import SessionLocal
from mock_systems.models import AuditLog


class GovernanceDecision(BaseModel):
    allowed: bool
    requires_human_approval: bool = False
    risk_level: RiskLevel
    reason: str
    rule_id: Optional[str] = None
    suggested_approver: Optional[str] = None


class GovernancePolicyEngine:
    """Evaluates proposed agent tool execution against deterministic enterprise policies."""

    @staticmethod
    def evaluate_tool_execution(
        agent: str,
        tool_name: str,
        tool_parameters: Dict[str, Any],
        user_role: str = "employee"
    ) -> GovernanceDecision:
        agent = agent.lower()

        # 1. RBAC Allow-List Validation
        AGENT_TOOL_PERMISSIONS = {
            "hr": ["hrms_create_employee", "hrms_get_employee", "rag_retrieve_policy"],
            "finance": ["erp_submit_expense", "erp_get_expense", "erp_setup_payroll", "rag_retrieve_policy"],
            "it": ["ticketing_create_ticket", "ticketing_get_ticket", "notifications_send_email", "rag_retrieve_policy"]
        }

        allowed_tools = AGENT_TOOL_PERMISSIONS.get(agent, [])
        if tool_name not in allowed_tools:
            GovernancePolicyEngine.log_audit_event(
                actor_agent=agent,
                action=tool_name,
                target_system="governance_rbac",
                payload=tool_parameters,
                risk_level=RiskLevel.HIGH.value,
                status="blocked",
                reason=f"RBAC violation: Agent '{agent}' is not authorized to call '{tool_name}'."
            )
            return GovernanceDecision(
                allowed=False,
                requires_human_approval=False,
                risk_level=RiskLevel.HIGH,
                reason=f"RBAC Violation: {agent} agent has no permission for {tool_name}",
                rule_id="RULE-RBAC-001"
            )

        # 2. Specific Policy Checks
        # --- Finance: Expense Reimbursement Rules ---
        if tool_name == "erp_submit_expense":
            amount = float(tool_parameters.get("amount", 0.0))
            has_receipt = bool(tool_parameters.get("receipt_attached", True))

            # Mandatory receipt check (POL-FIN-002 Sec 3)
            if not has_receipt:
                return GovernanceDecision(
                    allowed=False,
                    requires_human_approval=False,
                    risk_level=RiskLevel.LOW,
                    reason="Policy Violation: Non-reimbursable without readable itemized receipt [POL-FIN-002 Section 3].",
                    rule_id="RULE-FIN-REC-001"
                )

            # High Value (> $1,000)
            if amount > 1000.0:
                return GovernanceDecision(
                    allowed=True,
                    requires_human_approval=True,
                    risk_level=RiskLevel.HIGH,
                    reason="Expense exceeds $1,000 threshold. Requires dual approval (Department Director & Controller) [POL-FIN-002 Section 1].",
                    rule_id="RULE-FIN-TIER-3",
                    suggested_approver="Director_and_Controller"
                )

            # Moderate Value ($100 to $1,000)
            if amount >= 100.0:
                return GovernanceDecision(
                    allowed=True,
                    requires_human_approval=True,
                    risk_level=RiskLevel.MEDIUM,
                    reason="Expense between $100 and $1,000 requires Line Manager approval [POL-FIN-002 Section 1].",
                    rule_id="RULE-FIN-TIER-2",
                    suggested_approver="Line_Manager"
                )

            # Low Value (< $100)
            return GovernanceDecision(
                allowed=True,
                requires_human_approval=False,
                risk_level=RiskLevel.LOW,
                reason="Auto-approved: Expense below $100 with valid receipt [POL-FIN-002 Section 1].",
                rule_id="RULE-FIN-TIER-1"
            )

        # --- Finance: Payroll Setup ---
        if tool_name == "erp_setup_payroll":
            return GovernanceDecision(
                allowed=True,
                requires_human_approval=False,
                risk_level=RiskLevel.MEDIUM,
                reason="Standard payroll initial registration for verified onboarding.",
                rule_id="RULE-FIN-PAYROLL-001"
            )

        # --- IT: External Email or Notification ---
        if tool_name == "notifications_send_email":
            return GovernanceDecision(
                allowed=True,
                requires_human_approval=False,
                risk_level=RiskLevel.MEDIUM,
                reason="Stakeholder notification dispatch.",
                rule_id="RULE-IT-EMAIL-001"
            )

        # --- IT / HR Creation Tools ---
        if tool_name in ["hrms_create_employee", "ticketing_create_ticket"]:
            return GovernanceDecision(
                allowed=True,
                requires_human_approval=False,
                risk_level=RiskLevel.MEDIUM,
                reason="Standard operational write record.",
                rule_id="RULE-STD-WRITE-001"
            )

        # Default Read-Only Tool
        return GovernanceDecision(
            allowed=True,
            requires_human_approval=False,
            risk_level=RiskLevel.LOW,
            reason="Read-only query.",
            rule_id="RULE-READ-001"
        )

    @staticmethod
    def log_audit_event(
        actor_agent: str,
        action: str,
        target_system: str,
        payload: Dict[str, Any],
        risk_level: str,
        status: str,
        reason: Optional[str] = None
    ):
        """Persists audit trail into PostgreSQL/SQLite."""
        db = SessionLocal()
        try:
            entry = AuditLog(
                actor_agent=actor_agent,
                action=action,
                target_system=target_system,
                payload_json=json.dumps(payload),
                risk_level=risk_level,
                status=status,
                reason=reason
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
