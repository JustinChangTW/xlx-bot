from dataclasses import dataclass, field


@dataclass
class TeachingPlan:
    conclusion: str
    principle: str
    example: str
    steps: list[str] = field(default_factory=list)
    common_mistakes: list[str] = field(default_factory=list)
    next_action: str = ''


def build_teaching_plan(intent: str, user_input: str) -> TeachingPlan:
    is_how_to = intent == 'HOW_TO'
    normalized_question = (user_input or '').strip() or '目前問題'

    return TeachingPlan(
        conclusion='先回答核心問題，再補充最多兩點可核對資訊。',
        principle='僅根據知識庫可確認內容回答；資料不足時明確拒答。',
        example=f'例如：針對「{normalized_question}」，先給短答，再附上一到兩個依據。',
        steps=[
            '先確認問題要解決的目標與限制。',
            '從知識內容挑出最直接可驗證的資訊。',
            '用條列整理成可執行步驟。',
        ] if is_how_to else [],
        common_mistakes=[
            '用推測補齊缺少的現況資訊。',
            '沒有直接回答問題就先展開背景介紹。',
        ],
        next_action='若資訊不足，請提供可核對的來源（公告、課表、幹部名單）後再詢問。',
    )
