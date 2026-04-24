from dataclasses import dataclass


@dataclass
class PolicyDecision:
    allowed: bool
    approval_required: bool
    fallback: str
    reason: str


class PolicyEngine:
    """Policy interface with a safe default decision."""

    def evaluate(self, *, intent, action, risk, metadata=None):
        metadata = metadata or {}
        tool_name = str(metadata.get('tool_name', '')).strip()
        high_risk_actions = {
            'code_change',
            'deploy',
            'write_formal_knowledge',
            'formal_knowledge_write',
            'execute',
        }
        medium_risk_actions = {
            'sidecar_dispatch',
            'docs_draft',
            'command_review',
        }

        if risk == 'high' or action in high_risk_actions or tool_name in high_risk_actions:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                fallback='forbidden',
                reason=f'forbidden_policy intent={intent} action={action} risk={risk} tool={tool_name or "n/a"}',
            )

        if risk == 'medium' or action in medium_risk_actions:
            return PolicyDecision(
                allowed=True,
                approval_required=True,
                fallback='pending_review',
                reason=f'pending_review_policy intent={intent} action={action} risk={risk} tool={tool_name or "n/a"}',
            )

        return PolicyDecision(
            allowed=True,
            approval_required=False,
            fallback='none',
            reason=f'allow_policy intent={intent} action={action} risk={risk} tool={tool_name or "n/a"}',
        )
