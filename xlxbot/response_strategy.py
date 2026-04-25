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
    action = (next_action or '').strip() or '請提供可核對來源後再詢問。'
    return (
        '目前本地知識庫與可查核官方來源都沒有這項資訊，或目前提供的社團資料不足以確認。\n'
        f'next_action：{action}'
    )
