import time

from .knowledge import load_knowledge_base


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


def get_route_provider_chain(state, route_label):
    # 不同類型問題走不同 provider 順序，兼顧成本、速度與保密需求。
    route_map = {
        state.route_general: ['groq', 'xai', 'github', 'gemini', 'ollama'],
        state.route_expert: ['github', 'xai', 'gemini', 'ollama', 'groq'],
        state.route_local: ['ollama']
    }
    return route_map.get(route_label, ['ollama', 'gemini'])


def build_prompt(state, user_input, knowledge_content, history=None):
    # 統一在這裡組 prompt，把知識庫、規則、歷史與本次問題串起來。
    prompt_parts = [
        '你現在是「健言小龍蝦」，請參考以下社團知識回答問題。\n'
        '【重要規則】\n'
        '1. 絕對不要捏造不存在的資訊（不可有幻覺）。如果你上網搜尋後還是找不到相關資料，請明確且老實地回答：「我目前查不到相關資訊」。\n'
        '2. 若遇到不知道的問題，請善用搜尋工具上網查詢，並優先搜尋與「台北市健言社」相關的官方網站及網路社群媒體資料。\n'
        '3. 如果你從用戶的對話中，或是上網搜尋後，獲得了未來可能會用到的「台北市健言社」新知識，請在你的回答最後加上：\n'
        '<LEARNED>這裡寫下你想記住的具體事實（一句話或條列式）</LEARNED>\n'
        '這會被系統自動記錄下來，成為你未來的知識。\n\n'
        f'知識內容：\n{knowledge_content}\n\n'
    ]
    if history:
        prompt_parts.append('對話歷史：\n')
        for i, (user_msg, ai_msg) in enumerate(history[-state.max_history_length:], 1):
            prompt_parts.append(f'{i}. 用戶：{user_msg}\n   小龍蝦：{ai_msg}\n')
        prompt_parts.append('\n')
    prompt_parts.append(f'當前用戶問題：{user_input}\n\n')
    prompt_parts.append('請用熱情且專業的繁體中文回答：')
    return ''.join(prompt_parts)


def build_route_prompt(state, route_label, user_input, knowledge_content, history=None):
    route_note_map = {
        state.route_general: '本題屬於一般訓練或技巧型需求，請優先提供快速、實用、多樣的建議。',
        state.route_expert: '本題屬於深度分析或複雜邏輯需求，請優先提供嚴謹、條理清楚、可推演的回答。',
        state.route_local: '本題涉及私密或內部資料，請以保密、謹慎、不外送敏感資訊為最高原則。'
    }
    routed_knowledge = (
        f"--- 請求路由判定 ---\n"
        f"分類：{route_label}\n"
        f"原則：{route_note_map.get(route_label, '')}\n\n"
        f"{knowledge_content}"
    )
    return build_prompt(state, user_input, routed_knowledge, history)


def ask_ai(config, state, logger, providers, user_input, history=None):
    kb_content = load_knowledge_base(config, logger)
    if not kb_content:
        logger.error('Cannot load knowledge base')
        return '小龍蝦找不到知識庫，請稍後再試。'

    course_info = providers.query_course_info(user_input)
    if course_info:
        kb_content += f'\n\n--- 來自 台北市健言社官網 ---\n{course_info}'

    route_label, route_reason = classify_request(config, state, providers, user_input)
    prompt = build_route_prompt(state, route_label, user_input, kb_content, history)
    provider_chain = get_route_provider_chain(state, route_label)
    logger.info('Router selected route=%s reason=%s providers=%s', route_label, route_reason, provider_chain)

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
                logger.info('Success with provider=%s route=%s', provider_name, route_label)
                return result

            logger.warning('Provider failed provider=%s route=%s, trying next fallback', provider_name, route_label)

        logger.warning('All providers failed in attempt %d for route=%s, retrying...', attempt + 1, route_label)
        time.sleep(2)

    logger.error('All providers failed after 3 attempts for route=%s chain=%s', route_label, provider_chain)
    return '小龍蝦無法連線到任何 AI 服務，請稍後再試。'
