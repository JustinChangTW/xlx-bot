from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SidecarRequest:
    user_input: str
    task_type: str
    intent: str
    trace_id: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class SidecarResult:
    status: str
    task_type: str
    confidence: float
    outputs: list[str]
    risk_level: str
    requires_approval: bool
    audit_ref: str
    error: str = ''
    execution_allowed: bool = False
    execution_result: Optional['ExecutionResult'] = None


@dataclass
class DispatchDecision:
    should_call_sidecar: bool
    reason: str
    task_type: str
