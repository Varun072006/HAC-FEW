from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"          # Read-only actions, automated execution
    MEDIUM = "medium"    # Reversible writes, logged and monitored
    HIGH = "high"        # Financial, permissions, external sends; requires approval


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DepartmentAgent(str, Enum):
    HR = "hr"
    FINANCE = "finance"
    IT = "it"
    LEGAL = "legal"
    ANALYTICS = "analytics"


class SubTask(BaseModel):
    task_id: str = Field(..., description="Unique task identifier, e.g., task_1")
    agent: DepartmentAgent = Field(..., description="Target department agent")
    description: str = Field(..., description="Actionable instruction for the agent")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Structured parameters for execution")
    dependencies: List[str] = Field(default_factory=list, description="IDs of tasks that must finish before this task")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="Assessed risk level")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TaskGraph(BaseModel):
    workflow_name: str = Field(..., description="Flagship or custom workflow identifier")
    user_request: str = Field(..., description="Raw user prompt")
    tasks: List[SubTask] = Field(default_factory=list, description="List of decomposed sub-tasks")
    max_steps: int = Field(default=10, description="Circuit breaker for loop execution")


class AgentExecutionResult(BaseModel):
    task_id: str
    agent: DepartmentAgent
    status: TaskStatus
    output: Dict[str, Any] = Field(default_factory=dict)
    citations: List[str] = Field(default_factory=list, description="Cited document/chunk IDs from RAG")
    tool_calls_made: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class WorkflowSynthesis(BaseModel):
    workflow_id: str
    status: str
    summary: str
    subtask_results: List[AgentExecutionResult]
    citations: List[str] = Field(default_factory=list)
    total_tokens: Optional[int] = None
    wall_clock_seconds: Optional[float] = None
