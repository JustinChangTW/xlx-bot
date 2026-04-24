from dataclasses import dataclass


ALLOWED_ACTIONS = {'suggest', 'plan', 'report'}


@dataclass
class ActionResult:
    action: str
    status: str
    note: str


def run_action(action: str) -> ActionResult:
    action_name = (action or '').lower().strip()

    if action_name == 'execute':
        return ActionResult(action='execute', status='forbidden', note='execute action is forbidden by default')

    if action_name in ALLOWED_ACTIONS:
        return ActionResult(action=action_name, status='enabled', note='ok')

    fallback_action = 'suggest'
    return ActionResult(
        action=fallback_action,
        status='enabled',
        note=f'fallback:forbidden-or-unknown-action:{action_name or "empty"}',
    )
