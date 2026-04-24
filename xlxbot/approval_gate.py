from dataclasses import dataclass

from .policy_engine import PolicyDecision


@dataclass
class ApprovalResult:
    approved: bool
    requires_approval: bool
    fallback: str
    reason: str


class ApprovalGate:
    """Approval gate interface; currently returns the default policy result."""

    def decide(self, decision: PolicyDecision):
        if not decision.allowed:
            return ApprovalResult(
                approved=False,
                requires_approval=False,
                fallback=decision.fallback,
                reason=decision.reason,
            )
        return ApprovalResult(
            approved=not decision.approval_required,
            requires_approval=decision.approval_required,
            fallback=decision.fallback,
            reason=decision.reason,
        )
