from .teaching_planner import TeachingPlan


def format_teaching_plan_for_prompt(plan: TeachingPlan, intent: str) -> str:
    steps_value = '\n'.join(f'- {step}' for step in plan.steps) if plan.steps else '- （非 HOW_TO：本欄省略）'
    mistakes_value = '\n'.join(f'- {item}' for item in plan.common_mistakes) if plan.common_mistakes else '- （暫無）'
    return (
        '【TeachingPlan】\n'
        f'- conclusion: {plan.conclusion}\n'
        f'- principle: {plan.principle}\n'
        f'- example: {plan.example}\n'
        f'- steps:\n{steps_value}\n'
        f'- common_mistakes:\n{mistakes_value}\n'
        f'- next_action: {plan.next_action}\n'
        f'- intent: {intent}\n'
    )


def build_insufficient_knowledge_response(next_action: str) -> str:
    action = (next_action or '').strip() or '需由管理員補充可核對的正式來源。'
    if action.startswith('請提供') or action.startswith('請先提供'):
        action = '需由管理員補充可核對的正式來源。'
    official_lookup_action = (
        '系統已優先查核已核可官方來源（官網、課表、當期幹部、理事會、公告/活動頁與官方社群）；'
        '若官方來源仍沒有，需由管理員補充正式資料。'
    )
    if not any(keyword in action for keyword in ['官方', '官網', 'OpenClaw', '課表', '公告', '理事會']):
        action = f'{official_lookup_action} 補充：{action}'
    return (
        '我已查核目前可用的本地知識庫與已核可官方來源，但沒有取得足夠明確的資料可以回答這題。\n'
        f'處理狀態：{action}'
    )
