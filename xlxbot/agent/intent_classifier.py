FACT = 'FACT'
CONCEPT = 'CONCEPT'
HOW_TO = 'HOW_TO'
PROJECT = 'PROJECT'
DEBUG = 'DEBUG'

VALID_INTENTS = (FACT, CONCEPT, HOW_TO, PROJECT, DEBUG)

_INTENT_KEYWORDS = {
    DEBUG: ['debug', '除錯', '錯誤', 'exception', 'traceback', '修復', '故障'],
    PROJECT: ['專案', 'project', 'roadmap', '里程碑', '重構', '整合', '交付', '規劃'],
    HOW_TO: ['如何', '怎麼', '步驟', '教我', '指南', '教學', 'how to'],
    CONCEPT: ['是什麼', '概念', '原理', '差異', '比較', '為什麼', 'explain'],
}


def classify_intent(user_input: str) -> tuple[str, str]:
    """Rule-based intent classifier for agent path.

    Returns:
        (intent, reason)
    """
    text = (user_input or '').strip().lower()
    if not text:
        return FACT, 'rule:empty->fact'

    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return intent, f'rule:keyword:{intent.lower()}'

    return FACT, 'rule:default-fact'
