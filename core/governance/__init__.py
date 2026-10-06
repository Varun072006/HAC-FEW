"""
Governance & Safety Module:
- Policy Engine: Evaluates pre-execution write policies
- RBAC Engine: Restricts agent access to allowed tools and department domains
- Human-in-the-Loop Approval Gate: Intercepts High-Risk tasks
- Audit Logging: Immutable, structured logging of state transitions and calls
- Circuit Breaker: Enforces hard limits (max steps, retries, tokens, wall-clock time)
"""
from typing import Optional
from pydantic import BaseModel, Field


class PolicyEvaluationResult(BaseModel):
    allowed: bool
    requires_approval: bool = False
    reason: str
    rule_id: Optional[str] = None
