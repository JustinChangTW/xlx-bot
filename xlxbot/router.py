import re
import time

from .knowledge import load_knowledge_sections


INTENT_FACT = 'FACT_QUERY'
INTENT_MEMBER = 'MEMBER_QUERY'
INTENT_ACTIVITY = 'ACTIVITY_QUERY'
INTENT_ANNOUNCEMENT = 'ANNOUNCEMENT_QUERY'
INTENT_HISTORY = 'HISTORY_INTRO'
INTENT_OVERVIEW = 'GENERAL_OVERVIEW'
INTENT_RULE = 'RULE_QUERY'
INTENT_COURSE = 'COURSE_QUERY'
INTENT_ORG = 'ORG_QUERY'
MANUAL_PRIORITY_INTENTS = {INTENT_RULE, INTENT_COURSE, INTENT_ORG}


def classify_request_with_rules(state, user_input):
    # 先用關鍵字做快速分類，避免每次都要額外呼叫模型判斷。
    text = (user_input or '').lower()
    local_keywords = ['私密', '隱私', '保密', '機密', '內部', '個資', '公司背景', '講師手冊', '學員回饋', '回饋紀錄', '內網', '私房教材', 'sensitive', 'private']
    expert_keywords = ['程式', 'code', 'python', 'javascript', 'bug', '除錯', 'debug', '架構', '邏輯', '辯論', '講稿架構', '深度講評', '分析', '設計', '演算法', 'api', 'prompt', 'router', 'routing']
    general_keywords = ['開場', '破冰', '金句', '手勢', '聲音', '文案', '海報', '修辭', '短文', '標題', '口號']
    if any(keyword in text for keyword in local_keywords):
        return state.route_local, 'keyword:private'
    if any(keyword in text for keyword in expert_keywords):
        return state.route_expert, 'keyword:expert'
    if any(keyword in text for keyword in general_keywords):
        return state.route_general, 'keyword:general'
    return None, None


def classify_request_with_model(config, state, providers, user_input):
    if not config.router_enabled:
        return None, None
    # 關鍵字分不出來時，再用本地模型把請求分成 GENERAL / EXPERT / LOCAL。
    router_prompt = (
        '你是請求分類器，請只回傳一個標籤，不要解釋。\n'
        '可選標籤只有：GENERAL、EXPERT、LOCAL。\n'
        '判斷規則：\n'
        '- GENERAL：一般閒聊、技巧型訓練、速度優先、需要多樣點子。\n'
        '- EXPERT：複雜邏輯、程式、辯論推理、講稿架構、深度分析。\n'
        '- LOCAL：涉及私密資料、公司背景、學員回饋、講師手冊、不可外送資訊。\n'
        f'使用者請求：{user_input}\n'
        '請只輸出 GENERAL 或 EXPERT 或 LOCAL'
    )
    result = providers.ask_ollama_with_model(router_prompt, config.router_model_name)
    if not result:
        return None, None
    label = result.strip().upper()
    for candidate in (state.route_general, state.route_expert, state.route_local):
        if candidate in label:
            return candidate, 'model:router'
    return None, None


def classify_request(config, state, providers, user_input):
    rule_label, rule_reason = classify_request_with_rules(state, user_input)
    if rule_label:
        return rule_label, rule_reason
    model_label, model_reason = classify_request_with_model(config, state, providers, user_input)
    if model_label:
        return model_label, model_reason
    return state.route_general, 'default:general'


def classify_question_intent(user_input):
    text = (user_input or '').lower()

    if any(keyword in text for keyword in ['規則', '章程', '制度', '請假規定', '出席規則', 'rule', 'policy']):
        return INTENT_RULE
    if any(keyword in text for keyword in ['課程', '課表', '上課', '教學', 'workshop', 'curriculum']):
        return INTENT_COURSE
    if any(keyword in text for keyword in ['組織', '架構', '組別', '職責', '社長', '副社長', 'officer structure']):
        return INTENT_ORG
    if any(keyword in text for keyword in ['幹部', '成員', '幹部是誰', 'who is', 'officer']):
        return INTENT_MEMBER
    if any(keyword in text for keyword in ['公告', '報名', '注意事項', '最新消息', 'news', 'announcement']):
        return INTENT_ANNOUNCEMENT
    if any(keyword in text for keyword in ['活動', '工作坊', '聚會', '最近', '近期', '最新', '現任', 'current', 'recent']):
        return INTENT_ACTIVITY
    if any(keyword in text for keyword in ['沿革', '歷史', '成立', '里程碑', 'timeline']):
        return INTENT_HISTORY
    if any(keyword in text for keyword in ['是什麼', '介紹', '特色', '文化', '做什麼', '宗旨']):
        return INTENT_OVERVIEW
    return INTENT_FACT


def get_route_provider_chain(state, route_label):
    # 不同類型問題走不同 provider 順序，兼顧成本、速度與保密需求。
    route_map = {
        state.route_general: ['groq', 'xai', 'github', 'gemini', 'ollama'],
        state.route_expert: ['github', 'xai', 'gemini', 'ollama', 'groq'],
        state.route_local: ['ollama']
    }
    return route_map.get(route_label, ['ollama', 'gemini'])


def is_club_manual(path):
    return path.lower().endswith('knowledge/club_manual.md')


def is_relevant_section(file_path, intent):
    path = file_path.lower()
    if intent in MANUAL_PRIORITY_INTENTS:
        return is_club_manual(path)
    if intent == INTENT_MEMBER:
        return any(tag in path for tag in ['40_current_officers', '30_org_structure', '80_faq', 'club_manual'])
    if intent == INTENT_ANNOUNCEMENT:
        return any(tag in path for tag in ['60_announcements', '50_programs_and_events', '80_faq', 'club_manual'])
    if intent == INTENT_ACTIVITY:
        return any(tag in path for tag in ['50_programs_and_events', '60_announcements', '80_faq', 'club_manual'])
    if intent == INTENT_HISTORY:
        return any(tag in path for tag in ['20_history', '10_club_basic', '80_faq', 'club_manual'])
    if intent == INTENT_OVERVIEW:
        return any(tag in path for tag in ['10_club_basic', '70_culture', '80_faq', 'club_manual'])
    # 事實查詢預設使用基本資料 + FAQ + 待補提示。
    return any(tag in path for tag in ['10_club_basic', '80_faq', '99_data_todo', 'club_manual'])


def split_markdown_sections(content):
    sections = []
    current_title = 'ROOT'
    current_lines = []
    for line in content.splitlines():
        if re.match(r'^#{1,6}\s+', line):
            if current_lines:
                sections.append((current_title, '\n'.join(current_lines).strip()))
            current_title = re.sub(r'^#{1,6}\s+', '', line).strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        sections.append((current_title, '\n'.join(current_lines).strip()))
    return sections


def extract_club_manual_context(content, intent):
    mapping = {
        INTENT_RULE: ['規則', '章程', '制度', '注意事項'],
        INTENT_COURSE: ['課程', '課表', '教學', '訓練'],
        INTENT_ORG: ['組織', '架構', '幹部', '職責', '社長', '副社長']
    }
    keywords = mapping.get(intent, [])
    if not keywords:
        return content, True

    matched_blocks = []
    for title, body in split_markdown_sections(content):
        normalized = f'{title}\n{body}'
        if any(keyword in normalized for keyword in keywords):
            matched_blocks.append(f'## {title}\n{body}'.strip())

    if not matched_blocks:
        return '', False
    return '\n\n'.join(matched_blocks), True


def build_knowledge_context(sections, intent):
    matched = [s for s in sections if is_relevant_section(s.path, intent)]
    if not matched:
        matched = sections

    manual_exists = any(is_club_manual(s.path) for s in sections)
    manual_hit = False
    useful = []

    if intent in MANUAL_PRIORITY_INTENTS:
        manual_sections = [s for s in matched if is_club_manual(s.path)]
        if manual_sections:
            manual_context, manual_hit = extract_club_manual_context(manual_sections[0].content, intent)
            if manual_context:
                useful.append(f"--- 來自 {manual_sections[0].path}（優先來源） ---\n{manual_context}")
        return '\n\n'.join(useful), manual_exists, manual_hit

    for section in matched:
        if section.path.startswith('memory/'):
            continue
        useful.append(f"--- 來自 {section.path} ---\n{section.content}")

    return '\n\n'.join(useful), manual_exists, manual_hit


def build_prompt(state, user_input, knowledge_content, intent, manual_exists, manual_hit, history=None):
    # 統一在這裡組 prompt，把知識庫、規則、歷史與本次問題串起來。
    prompt_parts = [
        '你現在是「健言小龍蝦」，你的任務是根據提供的知識庫回答。\n'
        '【回答硬性規則】\n'
        '1. 只能使用「知識內容」中已明確出現的資訊。\n'
        '2. 若知識內容沒有明確答案，必須直接回答「目前知識庫沒有這項資訊」或「目前提供的社團資料不足以確認」。\n'
        '3. 禁止自行補人物、時間、活動、職位、經歷；禁止把推測當成事實。\n'
        '4. 先回答使用者真正問的核心問題，再補充最多 2 點相關資訊。\n'
        '5. 若問題含有「目前、最近、現任、最新」等時間語意，優先使用知識中的『最新公告/近期活動/目前資訊』段落。\n'
        '6. 回答要貼題、簡潔、可核對；避免空泛長篇。\n'
        '7. 不要要求或假設你已經上網查詢；本回合僅依賴提供的知識內容。\n'
        '8. 若問題意圖是 RULE_QUERY / COURSE_QUERY / ORG_QUERY，必須優先使用 club_manual.md；若 club_manual 找不到答案，直接回覆資料不足。\n\n'
        f'問題意圖分類：{intent}\n'
        f'club_manual 是否存在：{manual_exists}\n'
        f'club_manual 是否命中可用段落：{manual_hit}\n\n'
        f'知識內容：\n{knowledge_content or "[無可用知識片段]"}\n\n'
    ]
    if lessons_guidance:
        prompt_parts.append(f'回答前套用 Lessons Learned：\n{lessons_guidance}\n\n')
    if history:
        prompt_parts.append('對話歷史（僅供語氣連貫，不可覆蓋知識事實）：\n')
        for i, (user_msg, ai_msg) in enumerate(history[-state.max_history_length:], 1):
            prompt_parts.append(f'{i}. 用戶：{user_msg}\n   小龍蝦：{ai_msg}\n')
        prompt_parts.append('\n')
    prompt_parts.append(f'當前用戶問題：{user_input}\n\n')
    prompt_parts.append('請用繁體中文作答。')
    return ''.join(prompt_parts)


def build_route_prompt(state, route_label, user_input, knowledge_content, intent, manual_exists, manual_hit, history=None):
    route_note_map = {
        state.route_general: '本題屬於一般訓練或技巧型需求，請優先提供快速、實用、貼題的回答。',
        state.route_expert: '本題屬於深度分析或複雜邏輯需求，請優先提供嚴謹、條理清楚的回答。',
        state.route_local: '本題涉及私密或內部資料，請以保密、謹慎、不外送敏感資訊為最高原則。'
    }
    routed_knowledge = (
        f"--- 請求路由判定 ---\n"
        f"分類：{route_label}\n"
        f"原則：{route_note_map.get(route_label, '')}\n\n"
        f"{knowledge_content}"
    )
    return build_prompt(state, user_input, routed_knowledge, intent, manual_exists, manual_hit, history)


def ask_ai(config, state, logger, providers, user_input, history=None):
    sections = load_knowledge_sections(config, logger)
    if not sections:
        logger.error('Cannot load knowledge base sections')
        return '小龍蝦找不到知識庫，請稍後再試。'

    intent = classify_question_intent(user_input)
    scoped_knowledge, manual_exists, manual_hit = build_knowledge_context(sections, intent)

    # 規則/課程/組織類問題若 club_manual 無命中，直接明確回覆資料不足。
    if intent in MANUAL_PRIORITY_INTENTS and (not manual_exists or not manual_hit):
        return '目前提供的社團資料不足以確認（club_manual 尚無對應內容）。'

    # 活動/公告題型仍可追加官網資料，但回答必須可追溯到上下文。
    course_info = providers.query_course_info(user_input)
    if course_info and intent in {INTENT_ACTIVITY, INTENT_ANNOUNCEMENT, INTENT_COURSE}:
        scoped_knowledge += f'\n\n--- 來自 台北市健言社官網 ---\n{course_info}'

    route_label, route_reason = classify_request(config, state, providers, user_input)
    prompt = build_route_prompt(state, route_label, user_input, scoped_knowledge, intent, manual_exists, manual_hit, history)
    provider_chain = get_route_provider_chain(state, route_label)
    logger.info('Router selected route=%s reason=%s intent=%s providers=%s', route_label, route_reason, intent, provider_chain)

    # 每個 provider 失敗就往下 fallback，整條鏈失敗才整體重試。
    for attempt in range(3):
        logger.debug('Route attempt %d/3 route=%s', attempt + 1, route_label)
        for provider_name in provider_chain:
            logger.debug('Attempting provider=%s route=%s', provider_name, route_label)
            result = None
            if provider_name == 'groq':
                result = providers.ask_groq(prompt)
            elif provider_name == 'xai':
                result = providers.ask_xai(prompt)
            elif provider_name == 'github':
                result = providers.ask_github_models(prompt)
            elif provider_name == 'gemini':
                result = providers.ask_gemini(prompt)
            elif provider_name == 'ollama':
                result = providers.ask_ollama(prompt)

            if result:
                logger.info('Success with provider=%s route=%s intent=%s', provider_name, route_label, intent)
                return result

            logger.warning('Provider failed provider=%s route=%s, trying next fallback', provider_name, route_label)

        logger.warning('All providers failed in attempt %d for route=%s, retrying...', attempt + 1, route_label)
        time.sleep(2)

    logger.error('All providers failed after 3 attempts for route=%s chain=%s', route_label, provider_chain)
    return '小龍蝦無法連線到任何 AI 服務，請稍後再試。'
