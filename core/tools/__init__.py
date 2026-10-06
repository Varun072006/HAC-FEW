"""
Typed tool layer wrapping mock enterprise systems.
Enforces:
- Separation of Read tools vs Write tools
- Pydantic input/output schemas
- Allow-list assignment per agent role
- Governance policy checks on every write
"""
from typing import Dict, Any, List
from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    description: str
    is_write: bool = False
    allowed_agents: List[str] = Field(default_factory=list)
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
