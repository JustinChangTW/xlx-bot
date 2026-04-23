from dataclasses import dataclass


@dataclass
class ActionResult:
    action: str
    status: str
    note: str


def run_action(action: str) -> ActionResult:
    action_name = (action or 'answer').lower()
    if action_name == 'execute':
        return ActionResult(action='execute', status='not-enabled', note='execute action is not enabled yet')

    if action_name in {'answer', 'suggest', 'plan', 'report'}:
        return ActionResult(action=action_name, status='enabled', note='ok')

    return ActionResult(action='answer', status='enabled', note='fallback:unknown-action')
