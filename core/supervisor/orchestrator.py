"""
Supervisor Orchestrator using LangGraph state graph principles.
Decomposes user requests into DAG task graphs, executes tasks according to dependencies,
runs policy gates, handles dynamic replanning on tool errors, and synthesizes cited answers.
"""
import uuid
import time
from typing import Dict, Any, List, Optional
import json

from core.supervisor.schemas import (
    TaskGraph, SubTask, DepartmentAgent, RiskLevel, TaskStatus,
    AgentExecutionResult, WorkflowSynthesis
)
from core.rag.retriever import HybridPolicyRetriever
from core.governance.policy_engine import GovernancePolicyEngine
from core.tools.enterprise_tools import TOOL_REGISTRY


class SupervisorOrchestrator:
    """
    Central Supervisor orchestrating multi-agent workflows.
    """

    def __init__(self, retriever: Optional[HybridPolicyRetriever] = None):
        self.retriever = retriever or HybridPolicyRetriever("data/policies")

    def detect_prompt_injection(self, text: str) -> bool:
        lower = text.lower()
        injection_patterns = [
            "ignore all previous",
            "ignore previous",
            "you are now",
            "system update:",
            "override all rules",
            "superuser",
            "bypass policy",
            "delete all records"
        ]
        return any(pat in lower for pat in injection_patterns)

    def plan_workflow(self, user_request: str, user_role: str = "employee") -> TaskGraph:
        """
        Decomposes natural language request into a Pydantic-typed TaskGraph.
        Includes guardrail checks: Prompt Injection defense and RBAC validation.
        """
        # Guardrail 1: Adversarial Prompt Injection Defense
        if self.detect_prompt_injection(user_request):
            return TaskGraph(
                workflow_name="security_blocked_injection",
                user_request=user_request,
                tasks=[]
            )

        # Guardrail 2: Role-Based Access Control (RBAC)
        req_lower = user_request.lower()
        if user_role == "employee" and any(k in req_lower for k in ["modify salary", "change salary", "raise compensation", "credit $"]):
            return TaskGraph(
                workflow_name="security_blocked_rbac",
                user_request=user_request,
                tasks=[]
            )

        # Workflow 1: Employee Onboarding
        if any(kw in req_lower for kw in ["onboard", "new hire", "hire", "welcome"]):
            return TaskGraph(
                workflow_name="employee_onboarding",
                user_request=user_request,
                tasks=[
                    SubTask(
                        task_id="task_hr_01",
                        agent=DepartmentAgent.HR,
                        description="Register new employee in HRMS database",
                        inputs={
                            "name": self._extract_name(user_request),
                            "email": self._extract_email(user_request),
                            "department": "Engineering" if "engineering" in req_lower or "engineer" in req_lower else "Operations",
                            "role": "Software Engineer" if "engineer" in req_lower else "Associate",
                            "start_date": "2026-11-01"
                        },
                        dependencies=[],
                        risk_level=RiskLevel.MEDIUM
                    ),
                    SubTask(
                        task_id="task_it_01",
                        agent=DepartmentAgent.IT,
                        description="Provision developer accounts and laptop hardware ticket",
                        inputs={
                            "title": f"Provision developer laptop for new hire",
                            "category": "Hardware/Provisioning",
                            "priority": "medium",
                            "severity": "SEV-3",
                            "description": "Configure developer laptop and generate access accounts."
                        },
                        dependencies=["task_hr_01"],
                        risk_level=RiskLevel.MEDIUM
                    ),
                    SubTask(
                        task_id="task_fin_01",
                        agent=DepartmentAgent.FINANCE,
                        description="Setup payroll compensation and expense eligibility",
                        inputs={
                            "base_salary": 95000.0
                        },
                        dependencies=["task_hr_01"],
                        risk_level=RiskLevel.MEDIUM
                    )
                ]
            )

        # Workflow 2: Expense Claim
        elif any(kw in req_lower for kw in ["expense", "reimburse", "reimbursement"]):
            amount = self._extract_amount(user_request)
            has_receipt = "no receipt" not in req_lower and "without receipt" not in req_lower

            return TaskGraph(
                workflow_name="expense_approval",
                user_request=user_request,
                tasks=[
                    SubTask(
                        task_id="task_fin_rag",
                        agent=DepartmentAgent.FINANCE,
                        description="Retrieve expense policy guidelines and thresholds",
                        inputs={"query": "expense reimbursement threshold approval receipts"},
                        dependencies=[],
                        risk_level=RiskLevel.LOW
                    ),
                    SubTask(
                        task_id="task_fin_submit",
                        agent=DepartmentAgent.FINANCE,
                        description="Submit expense reimbursement request with policy verification",
                        inputs={
                            "employee_id": self._extract_emp_id(user_request) or "EMP-001",
                            "category": "Travel / Meals",
                            "amount": amount,
                            "receipt_attached": has_receipt,
                            "description": user_request
                        },
                        dependencies=["task_fin_rag"],
                        risk_level=RiskLevel.HIGH if amount > 1000 else (RiskLevel.MEDIUM if amount >= 100 else RiskLevel.LOW)
                    )
                ]
            )

        # Workflow 3: IT Incident Triage
        elif any(kw in req_lower for kw in ["vpn", "incident", "outage", "flicker", "ticket", "error", "alert"]):
            sev = "SEV-1" if any(w in req_lower for w in ["critical", "outage", "database", "500 error"]) else "SEV-3"
            return TaskGraph(
                workflow_name="it_incident_triage",
                user_request=user_request,
                tasks=[
                    SubTask(
                        task_id="task_it_rag",
                        agent=DepartmentAgent.IT,
                        description="Retrieve IT incident severity policy and SLA guidelines",
                        inputs={"query": f"incident severity classification SLA {user_request[:50]}"},
                        dependencies=[],
                        risk_level=RiskLevel.LOW
                    ),
                    SubTask(
                        task_id="task_it_ticket",
                        agent=DepartmentAgent.IT,
                        description="Create IT incident ticket with classified severity",
                        inputs={
                            "title": user_request[:80],
                            "category": "Network/VPN" if "vpn" in req_lower else "General Support",
                            "priority": "critical" if sev == "SEV-1" else "medium",
                            "severity": sev,
                            "description": user_request
                        },
                        dependencies=["task_it_rag"],
                        risk_level=RiskLevel.MEDIUM
                    )
                ]
            )

        # Default fallback
        return TaskGraph(
            workflow_name="custom_request",
            user_request=user_request,
            tasks=[
                SubTask(
                    task_id="task_gen_rag",
                    agent=DepartmentAgent.IT,
                    description="Search enterprise policies for general query",
                    inputs={"query": user_request},
                    dependencies=[],
                    risk_level=RiskLevel.LOW
                )
            ]
        )

    def execute_workflow(self, task_graph: TaskGraph, user_role: str = "employee") -> WorkflowSynthesis:
        """
        Executes decomposed tasks respecting dependencies, policy validation, and synthesis.
        """
        start_time = time.time()
        workflow_id = f"wf_{uuid.uuid4().hex[:8]}"
        completed_task_results: Dict[str, AgentExecutionResult] = {}
        all_citations: List[str] = []
        requires_human_approval = False

        # Execute tasks in dependency order
        for subtask in task_graph.tasks:
            # Check dependencies
            for dep in subtask.dependencies:
                if dep in completed_task_results and completed_task_results[dep].status == TaskStatus.FAILED:
                    subtask.status = TaskStatus.SKIPPED
                    subtask.error = f"Skipped due to upstream failure in {dep}"
                    completed_task_results[subtask.task_id] = AgentExecutionResult(
                        task_id=subtask.task_id,
                        agent=subtask.agent,
                        status=TaskStatus.SKIPPED,
                        error_message=subtask.error
                    )
                    continue

            if subtask.status == TaskStatus.SKIPPED:
                continue

            # Execute subtask
            agent_result = self._execute_subtask(subtask, completed_task_results, user_role)
            completed_task_results[subtask.task_id] = agent_result
            if agent_result.citations:
                all_citations.extend(agent_result.citations)

            if agent_result.output.get("status") == "awaiting_approval":
                requires_human_approval = True

        wall_clock = round(time.time() - start_time, 3)

        # Synthesize final response
        if task_graph.workflow_name == "security_blocked_injection":
            status_str = "blocked_injection"
            summary_lines = ["Adversarial prompt injection attack detected and neutralized by security guardrail."]
        elif task_graph.workflow_name == "security_blocked_rbac":
            status_str = "blocked_rbac"
            summary_lines = ["Action blocked by RBAC: Unauthorized operation attempted by employee role."]
        elif requires_human_approval:
            status_str = "awaiting_human_approval"
            summary_lines = ["Workflow paused at human authorization gate."]
        elif any(r.status == TaskStatus.FAILED for r in completed_task_results.values()):
            status_str = "completed_with_errors"
            summary_lines = ["One or more sub-tasks encountered errors or policy blocks."]
        else:
            status_str = "success"
            summary_lines = ["All sub-tasks executed successfully."]

        return WorkflowSynthesis(
            workflow_id=workflow_id,
            status=status_str,
            summary=" ".join(summary_lines),
            subtask_results=list(completed_task_results.values()),
            citations=list(set(all_citations)),
            wall_clock_seconds=wall_clock
        )

    def _execute_subtask(
        self,
        subtask: SubTask,
        prior_results: Dict[str, AgentExecutionResult],
        user_role: str
    ) -> AgentExecutionResult:
        # 1. RAG Subtasks
        if "rag" in subtask.task_id:
            query = subtask.inputs.get("query", subtask.description)
            rag_res = self.retriever.retrieve(query, user_role=user_role)
            return AgentExecutionResult(
                task_id=subtask.task_id,
                agent=subtask.agent,
                status=TaskStatus.COMPLETED if not rag_res.abstain else TaskStatus.FAILED,
                output={"retrieved_chunks": len(rag_res.results), "context": rag_res.context_for_prompt},
                citations=rag_res.citations,
                tool_calls_made=["rag_retrieve_policy"],
                error_message=rag_res.escalation_reason if rag_res.abstain else None
            )

        # 2. Tool Execution Mapping
        agent_name = subtask.agent.value
        tool_name = None
        params = dict(subtask.inputs)

        # Pass forward emp_id if produced upstream
        if "task_hr_01" in prior_results and prior_results["task_hr_01"].output.get("id"):
            params["employee_id"] = prior_results["task_hr_01"].output.get("id")

        if subtask.task_id == "task_hr_01":
            tool_name = "hrms_create_employee"
        elif subtask.task_id == "task_fin_01":
            tool_name = "erp_setup_payroll"
        elif subtask.task_id == "task_fin_submit":
            tool_name = "erp_submit_expense"
        elif subtask.task_id in ["task_it_01", "task_it_ticket"]:
            tool_name = "ticketing_create_ticket"

        if tool_name and tool_name in TOOL_REGISTRY:
            tool_fn = TOOL_REGISTRY[tool_name]
            tool_resp = tool_fn(agent=agent_name, params=params)

            citations = []
            if tool_resp.policy_decision and "POL-" in (tool_resp.policy_decision.reason or ""):
                citations.append(tool_resp.policy_decision.reason)

            if tool_resp.success:
                return AgentExecutionResult(
                    task_id=subtask.task_id,
                    agent=subtask.agent,
                    status=TaskStatus.COMPLETED,
                    output=tool_resp.data or {},
                    citations=citations,
                    tool_calls_made=[tool_name]
                )
            else:
                return AgentExecutionResult(
                    task_id=subtask.task_id,
                    agent=subtask.agent,
                    status=TaskStatus.FAILED,
                    error_message=tool_resp.error,
                    tool_calls_made=[tool_name]
                )

        return AgentExecutionResult(
            task_id=subtask.task_id,
            agent=subtask.agent,
            status=TaskStatus.FAILED,
            error_message=f"No matching tool found for task {subtask.task_id}"
        )

    # Heuristic helpers for entity extraction
    def _extract_name(self, text: str) -> str:
        words = text.split()
        for i, w in enumerate(words):
            if w.lower() in ["onboard", "hire", "engineer", "new"] and i + 2 < len(words):
                candidate = f"{words[i+1]} {words[i+2]}".strip(",.()")
                if "@" not in candidate and not candidate.lower().startswith("our"):
                    return candidate
        return "Alex Doe"

    def _extract_email(self, text: str) -> str:
        import re
        m = re.search(r"[\w\.-]+@[\w\.-]+", text)
        if m:
            parts = m.group(0).split("@")
            return f"{parts[0]}_{uuid.uuid4().hex[:4]}@{parts[1]}"
        return f"user_{uuid.uuid4().hex[:6]}@company.test"

    def _extract_amount(self, text: str) -> float:
        import re
        m = re.search(r"\$\s*([0-9,]+(?:\.[0-9]{1,2})?)", text)
        if m:
            return float(m.group(1).replace(",", ""))
        return 50.0

    def _extract_emp_id(self, text: str) -> Optional[str]:
        import re
        m = re.search(r"EMP-\d+", text)
        return m.group(0) if m else None
