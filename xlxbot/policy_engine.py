from dataclasses import dataclass


@dataclass
class PolicyDecision:
    approval_required: bool
    fallback: str
    reason: str


class PolicyEngine:
    """Policy interface with a safe default decision."""

    def evaluate(self, *, intent, action, risk, metadata=None):
        _ = metadata
        return PolicyDecision(
            approval_required=False,
            fallback='deny_with_insufficient_data',
            reason=f'default_policy intent={intent} action={action} risk={risk}',
        )
