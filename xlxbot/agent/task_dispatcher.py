from dataclasses import dataclass

from .intent_classifier import CONCEPT, DEBUG, FACT, HOW_TO, PROJECT


@dataclass
class TaskDecision:
    intent: str
    action: str
    reason: str


INTENT_TO_ACTION = {
    FACT: 'answer',
    CONCEPT: 'answer',
    HOW_TO: 'plan',
    PROJECT: 'suggest',
    DEBUG: 'report',
}


def dispatch_task(intent: str, user_input: str) -> TaskDecision:
    text = (user_input or '').lower()
    if any(keyword in text for keyword in ['執行', 'execute', 'run it', '直接做']):
        return TaskDecision(intent=intent, action='execute', reason='rule:execute-requested')

    action = INTENT_TO_ACTION.get(intent, 'answer')
    return TaskDecision(intent=intent, action=action, reason=f'rule:intent-map:{intent.lower()}')
