import re
import time
import threading
from contextlib import contextmanager

from .agent import classify_intent as classify_agent_intent
from .agent import dispatch_task, run_action
from .knowledge import load_knowledge_sections
from .response_strategy import build_insufficient_knowledge_response, format_teaching_plan_for_prompt
from .sidecar import SidecarDispatcher, format_sidecar_guidance
from .teaching_planner import build_teaching_plan


INTENT_FACT = 'FACT_QUERY'
INTENT_MEMBER = 'MEMBER_QUERY'
INTENT_ACTIVITY = 'ACTIVITY_QUERY'
INTENT_ANNOUNCEMENT = 'ANNOUNCEMENT_QUERY'
INTENT_HISTORY = 'HISTORY_INTRO'
INTENT_OVERVIEW = 'GENERAL_OVERVIEW'
INTENT_RULE = 'RULE_QUERY'
INTENT_COURSE = 'COURSE_QUERY'
INTENT_ORG = 'ORG_QUERY'
INTENT_PROMOTION = 'PROMOTION_QUERY'
INTENT_HOW_TO = 'HOW_TO'
MANUAL_PRIORITY_INTENTS = {INTENT_RULE, INTENT_COURSE, INTENT_ORG}
COURSE_TIME_KEYWORDS = ['今天', '明天', '後天', '這週', '這周', '本週', '本周', '下週', '下周', '下一週', '下一周', '下個月', '下个月', '下月']
COURSE_SCHEDULE_RETRIEVAL_KEYWORDS = COURSE_TIME_KEYWORDS + [
    'tm',
    't.m',
    't.m.',
    '題目',
    '課程主題',
    '課表',
    '時間表',
    '開課時間',
    '上課時間',
    '課程時間',
    '時間',
    '日期',
    '幾點',
    '何時',
    '什麼時候',
    '會內會',
]
SKILL_TRAINING_KEYWORDS = [
    '講評',
    '總評',
    '開場',
    '開塲',
    '破題',
    '解題',
    '講稿',
    '演講稿',
    '三分鐘',
    '即席',
    '主持',
    '主席',
    '串場',
    '上台',
    '台風',
    '手勢',
    '聲音',
    '結尾',
    '審題',
]
SKILL_HELP_KEYWORDS = [
    '如何',
    '怎麼',
    '怎樣',
    '可以如何',
    '幫我',
    '教我',
    '給我',
    '建議',
    '寫',
    '改',
    '準備',
]
SKILL_CONTEXT_KEYWORDS = [
    '擔任',
    '我是',
    '我當',
    '輪到我',
    '題目',
    '主題',
]
SKILL_FACT_LOOKUP_KEYWORDS = [
    '是誰',
    '誰是',
    '哪位',
    '名單',
    '安排',
]
FACT_REQUIRED_INTENTS = {
    INTENT_FACT,
    INTENT_MEMBER,
    INTENT_ACTIVITY,
    INTENT_ANNOUNCEMENT,
    INTENT_HISTORY,
    INTENT_OVERVIEW,
    INTENT_HOW_TO,
}
SIDECAR_TASK_INTENTS = {INTENT_PROMOTION, INTENT_HOW_TO}
MISSING_INFO_MARKERS = [
    '[目前知識庫沒有這項資訊]',
    '[目前知識庫缺少',
    '[尚未提供]',
    '[尚未整理',
    '[需要',
    '[待補資料]',
    '待補資料',
    '資料不足',
]
USER_LOOKUP_DEFLECTION_PATTERNS = [
    r'請(你|您)?(自行|自己|直接)?(到|至|上)?(官網|官方網站|公告頁|公告頁面|社團公告頁面|官方社群).{0,24}(查詢|查閱|查看|參考|確認|取得|獲得)',
    r'(可|可以|建議|請).{0,12}(參考|查詢|查閱|查看|確認).{0,16}(官網|官方網站|公告頁|公告頁面|社團公告頁面|官方社群)',
    r'(官網|官方網站|公告頁|公告頁面|社團公告頁面|官方社群).{0,24}(取得|獲得|查詢|查閱|查看|確認).{0,12}(最新|即時|詳細)?(資訊|資料|消息)',
    r'(最新|即時|詳細)(資訊|資料|消息).{0,16}(請|可|可以|建議).{0,16}(參考|查詢|查閱|查看|確認)',
    r'(請|可|可以|建議).{0,16}(參考|查詢|查閱|查看|確認).{0,16}(這些來源|相關來源).{0,16}(取得|獲得)?(最新|即時|詳細)?(資訊|資料|消息)',
]
NON_FACT_SECTION_MARKERS = [
    '待補資料',
    'gap',
    '欄位模板',
    '回答規則提醒',
    '使用限制提醒',
    '維護提醒',
    '更新資訊',
]
HIGH_RISK_COMMAND_KEYWORDS = [
    '改程式',
    '修改程式',
    '改 code',
    '改code',
    '寫入 knowledge',
    '寫入knowledge',
    '更新知識庫',
    '部署',
    'deploy',
    '上線',
    'push',
    'commit',
]
DOC_REQUEST_KEYWORDS = ['README', 'readme', '文件', 'docs', '文件說明', '系統說明', '架構文件']
ERROR_REPORT_KEYWORDS = ['錯誤', '出錯', '壞掉', '故障', '失敗', 'exception', 'traceback', 'bug', 'debug', '除錯']
CORRECTION_KEYWORDS = ['你錯了', '你剛剛', '應該是', '更正', '修正', '請改成']


class RequestStateTracker:
    def __init__(self, request_id=None):
        self.request_id = request_id or f"req_{int(time.time() * 1000)}"
        self.start_time = time.time()
        self.steps = []
        self.errors = []
        self.retries = []
        self.current_step = None
        self.lock = threading.RLock()

    def start_step(self, step_name, details=None):
        with self.lock:
            if self.current_step:
                self.end_step(success=True)
            self.current_step = {
                'name': step_name,
                'start_time': time.time(),
                'details': details or {},
                'errors': []
            }

    def add_error(self, error_type, message, details=None):
        with self.lock:
            error = {
                'type': error_type,
                'message': str(message),
                'timestamp': time.time(),
                'details': details or {}
            }
            self.errors.append(error)
            if self.current_step:
                self.current_step['errors'].append(error)

    def end_step(self, success=True, result=None):
        with self.lock:
            if self.current_step:
                self.current_step.update({
                    'end_time': time.time(),
                    'duration': time.time() - self.current_step['start_time'],
                    'success': success,
                    'result': result
                })
                self.steps.append(self.current_step)
                self.current_step = None

    def record_retry(self, attempt, reason, backoff_seconds):
        with self.lock:
            self.retries.append({
                'attempt': attempt,
                'reason': reason,
                'backoff_seconds': backoff_seconds,
                'timestamp': time.time()
            })

    def get_summary(self):
        with self.lock:
            total_duration = time.time() - self.start_time
            return {
                'request_id': self.request_id,
                'total_duration': total_duration,
                'steps_count': len(self.steps),
                'errors_count': len(self.errors),
                'retries_count': len(self.retries),
                'steps': self.steps,
                'errors': self.errors,
                'retries': self.retries
            }


@contextmanager
def timeout_context(seconds):
    """Context manager for timeout handling"""
    timer = threading.Timer(seconds, lambda: (_ for _ in ()).throw(TimeoutError()))
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def classify_openclaw_task_type(user_input, intent):
    text = (user_input or '').strip().lower()
    if intent == INTENT_HOW_TO and is_skill_training_request(user_input):
        return 'knowledge_qa'
    if any(keyword.lower() in text for keyword in CORRECTION_KEYWORDS):
        return 'user_correction'
    if any(keyword.lower() in text for keyword in ERROR_REPORT_KEYWORDS):
        return 'error_report'
    if any(keyword.lower() in text for keyword in DOC_REQUEST_KEYWORDS):
        return 'docs_request'
    if any(keyword.lower() in text for keyword in HIGH_RISK_COMMAND_KEYWORDS):
        return 'command'
    task_keywords = ['計畫', '規劃', 'roadmap', '里程碑', '建議', '方案', '草稿', '怎麼做', '宣傳', '文宣', '社務布達', 'debug', '除錯', '修復', '故障', '專案', '任務', '重構', '整合']
    if any(keyword.lower() in text for keyword in task_keywords):
        return 'command'
    if intent in {INTENT_PROMOTION, INTENT_HOW_TO}:
        return 'command'
    return 'knowledge_qa'


def select_controlled_tool(task_type, user_input):
    text = (user_input or '').lower()
    if task_type == 'user_correction':
        return 'learning_capture', 'capture_correction', 'low'
    if task_type == 'error_report':
        return 'troubleshooting_capture', 'record_error', 'low'
    if task_type == 'docs_request':
        return 'docs_draft', 'docs_draft', 'medium'
    if task_type == 'command':
        if any(keyword in text for keyword in HIGH_RISK_COMMAND_KEYWORDS):
            if any(keyword in text for keyword in ['部署', 'deploy', '上線']):
                return 'deploy', 'deploy', 'high'
            if any(keyword in text for keyword in ['知識庫', 'knowledge']):
                return 'formal_knowledge_write', 'write_formal_knowledge', 'high'
            return 'code_change', 'code_change', 'high'
        return 'sidecar_dispatch', 'sidecar_dispatch', 'medium'
    return 'knowledge_lookup', 'knowledge_lookup', 'low'


def evaluate_controlled_tool_use(state, config, tool_registry, policy_engine, approval_gate, task_type, user_input):
    tool_name, action, risk = select_controlled_tool(task_type, user_input)
    if not tool_registry or not policy_engine or not approval_gate:
        state.last_tool_decision = {
            'task_type': task_type,
            'tool_name': tool_name,
            'action': action,
            'risk': risk,
            'allowed': True,
            'requires_approval': False,
            'fallback': 'none',
            'reason': 'control_stack_not_injected',
        }
        return state.last_tool_decision
    tool_definition = tool_registry.get(tool_name) if tool_registry else None
    if tool_definition is None:
        state.last_tool_decision = {
            'task_type': task_type,
            'tool_name': tool_name,
            'action': action,
            'risk': risk,
            'allowed': False,
            'requires_approval': False,
            'fallback': 'forbidden',
            'reason': f'unregistered_tool:{tool_name}',
        }
        return state.last_tool_decision

    missing_constraints = tool_registry.get_missing_env_constraints(tool_definition, config) if config and tool_registry else []
    if missing_constraints:
        requires_approval = task_type in {'command', 'docs_request'}
        state.last_tool_decision = {
            'task_type': task_type,
            'tool_name': tool_definition.name,
            'action': action,
            'risk': tool_definition.risk or risk,
            'allowed': True,
            'requires_approval': requires_approval,
            'fallback': 'pending_review' if requires_approval else 'tool_unavailable',
            'reason': f'missing_env_constraints:{",".join(missing_constraints)}',
            'missing_constraints': missing_constraints,
            'env_ready': False,
        }
        return state.last_tool_decision

    policy_decision = policy_engine.evaluate(
        intent=task_type,
        action=action,
        risk=tool_definition.risk or risk,
        metadata={'tool_name': tool_definition.name},
    ) if policy_engine and approval_gate else None
    approval_result = approval_gate.decide(policy_decision) if policy_decision and approval_gate else None

    state.last_tool_decision = {
        'task_type': task_type,
        'tool_name': tool_definition.name,
        'action': action,
        'risk': tool_definition.risk or risk,
        'allowed': bool(policy_decision.allowed) if policy_decision else True,
        'requires_approval': bool(approval_result.requires_approval) if approval_result else False,
        'fallback': approval_result.fallback if approval_result else 'none',
        'reason': approval_result.reason if approval_result else 'no_policy',
        'missing_constraints': [],
        'env_ready': True,
    }
    return state.last_tool_decision


def build_controlled_action_response(task_type, tool_decision):
    if tool_decision.get('missing_constraints'):
        if tool_decision.get('tool_name') == 'sidecar_dispatch':
            return ''
        if task_type == 'command':
            missing = ', '.join(tool_decision.get('missing_constraints', []))
            return f'目前受控執行鏈尚未就緒，已改為 pending review。缺少條件：{missing}'
        return '這個請求目前缺少必要設定，暫時無法進入受控流程。'
    if not tool_decision.get('allowed', True):
        if task_type == 'command':
            return '這類操作屬於高風險行為，目前系統禁止直接執行，例如改程式、部署或寫入正式知識庫。'
        return '這個請求目前不在允許的受控工具範圍內。'
    if tool_decision.get('requires_approval'):
        if tool_decision.get('tool_name') == 'sidecar_dispatch':
            return ''
        if task_type == 'docs_request':
            return '文件草稿需求已判定為 pending review。系統可以先提出草稿建議，但不會自動宣告文件已完成或自動套用正式變更。'
        return '這個請求需要 pending review。系統目前不會直接執行，而是保留為建議或待人工確認。'
    return ''


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
    if not hasattr(providers, 'ask_ollama_with_model'):
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


def should_force_general_route(user_input, intent):
    text = (user_input or '').lower()
    if any(keyword in text for keyword in ['私密', '隱私', '保密', '機密', '內部', '個資', 'private', 'sensitive']):
        return False
    return intent in FACT_REQUIRED_INTENTS or intent in {INTENT_RULE, INTENT_COURSE, INTENT_ORG, INTENT_PROMOTION}


def classify_question_intent(user_input):
    text = (user_input or '').lower()
    if text.strip() in {'這是什麼', '這是什麼?', '這是什麼？'}:
        return INTENT_FACT

    if any(keyword in text for keyword in ['理事會成員', '理事會有哪些人', '理監事成員', '理監事有哪些人']):
        return INTENT_MEMBER
    if re.search(r'\d+\s*期.*(社長|副社長|組長|理事長|幹部)', text):
        return INTENT_MEMBER
    if any(keyword in text for keyword in ['理事長是誰', '本期社長', '現任社長', '社長是誰', '副社長是誰', '幹部是誰', '誰是社長', '誰是副社長']):
        return INTENT_MEMBER
    if any(keyword in text for keyword in ['宣傳', '社務布達', '文宣', '宣傳文案', '邀請大家', '邀請來上課']):
        return INTENT_PROMOTION
    if any(keyword in text for keyword in ['會外會', '戶外活動']):
        return INTENT_ACTIVITY
    if any(keyword in text for keyword in ['會內會', '社課']):
        return INTENT_COURSE
    if is_skill_training_request(user_input):
        return INTENT_HOW_TO
    if any(keyword in text for keyword in COURSE_TIME_KEYWORDS):
        return INTENT_COURSE
    if any(keyword in text for keyword in ['規則', '章程', '制度', '請假規定', '出席規則', 'rule', 'policy']):
        return INTENT_RULE
    if any(keyword in text for keyword in ['如何', '怎麼', '怎么样', '怎樣', '步驟', '教我', '教學步驟', 'how to']):
        return INTENT_HOW_TO
    if any(keyword in text for keyword in ['課程', '課表', '時間表', '開課時間', '上課時間', '課程時間', '上課', '教學', 'workshop', 'curriculum']):
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


def is_skill_training_request(user_input):
    text = (user_input or '').lower()
    if not text:
        return False
    if any(keyword.lower() in text for keyword in SKILL_FACT_LOOKUP_KEYWORDS):
        return False
    has_skill_keyword = any(keyword.lower() in text for keyword in SKILL_TRAINING_KEYWORDS)
    if not has_skill_keyword:
        return False
    has_help_keyword = any(keyword.lower() in text for keyword in SKILL_HELP_KEYWORDS)
    has_context_keyword = any(keyword.lower() in text for keyword in SKILL_CONTEXT_KEYWORDS)
    return has_help_keyword or has_context_keyword


def get_route_provider_chain(state, route_label, providers):
    # 不同類型問題走不同 provider 順序，兼顧成本、速度與保密需求。
    route_map = {
        state.route_general: ['gemini', 'groq', 'github', 'xai', 'ollama'],
        state.route_expert: ['gemini', 'github', 'xai', 'ollama', 'groq'],
        state.route_local: ['ollama']
    }
    default_chain = ['gemini', 'ollama', 'groq']
    raw_chain = route_map.get(route_label, default_chain)
    available_chain = [name for name in raw_chain if providers.is_provider_available(name)]
    if available_chain:
        return available_chain
    return [name for name in default_chain if providers.is_provider_available(name)]


def is_club_manual(path):
    return path.lower().endswith('knowledge/90_club_manual.md')


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
    if intent == INTENT_PROMOTION:
        return any(tag in path for tag in ['50_programs_and_events', '60_announcements', '70_culture', '80_faq', 'club_manual'])
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


def is_missing_info_line(line):
    normalized = (line or '').strip()
    if not normalized:
        return True
    if normalized.startswith('--- 來自 '):
        return True
    if normalized in {'[無可用知識片段]'}:
        return True
    lowered = normalized.lower()
    return any(marker.lower() in lowered for marker in MISSING_INFO_MARKERS)


def section_has_meaningful_fact(title, body):
    normalized_title = (title or '').strip().lower()
    if any(marker in normalized_title for marker in NON_FACT_SECTION_MARKERS):
        return False

    for raw_line in (body or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        if is_missing_info_line(line):
            continue
        if line in {'[IMPORTANT]', '[TYPE: RULES]', '[TYPE: ANSWERING_RULES]'}:
            continue
        return True
    return False


def has_grounded_facts(knowledge_content):
    if not knowledge_content or knowledge_content.strip() == '[無可用知識片段]':
        return False

    sections = split_markdown_sections(knowledge_content)
    if not sections:
        return False

    for title, body in sections:
        if section_has_meaningful_fact(title, body):
            return True
    return False


def has_missing_markers(knowledge_content):
    lowered = (knowledge_content or '').lower()
    return any(marker.lower() in lowered for marker in MISSING_INFO_MARKERS)


def is_current_sensitive_query(user_input, intent):
    text = (user_input or '').lower()
    if intent == INTENT_HOW_TO and is_skill_training_request(user_input):
        return False
    current_keywords = COURSE_TIME_KEYWORDS + [
        '目前',
        '現在',
        '現任',
        '最新',
        '最近',
        '本期',
        '這期',
        '當期',
        '本週',
        '本周',
        '下一週',
        '下一周',
    ]
    if any(keyword.lower() in text for keyword in current_keywords):
        return True
    return intent in {INTENT_MEMBER, INTENT_ACTIVITY, INTENT_ANNOUNCEMENT, INTENT_COURSE, INTENT_PROMOTION}


def is_problem_analysis_query(user_input):
    text = (user_input or '').strip().lower()
    if not text:
        return False
    analysis_keywords = [
        '不理解',
        '看不懂',
        '不清楚',
        '合理',
        '可能',
        '可行',
        '判斷',
        '分析',
        '為什麼',
        '爲什麼',
        '怎麼會',
        '問題在哪',
        '哪裡怪',
        '這樣對嗎',
        '是不是',
    ]
    if any(keyword in text for keyword in analysis_keywords):
        return True
    compact = re.sub(r'\s+', '', text)
    return compact in {'這是什麼', '這什麼', '有點短', '不懂', '看不懂'}


def get_openclaw_lookup_reasons(config, user_input, intent, knowledge_content, manual_exists=True, manual_hit=True):
    if not getattr(config, 'sidecar_enabled', False):
        return []
    if getattr(config, 'openclaw_phase', 'suggest') == 'observe':
        return []
    if intent == INTENT_HOW_TO and is_skill_training_request(user_input):
        return []

    reasons = []
    if intent in MANUAL_PRIORITY_INTENTS and (not manual_exists or not manual_hit):
        reasons.append('manual_missing_or_no_hit')
    if is_current_sensitive_query(user_input, intent):
        reasons.append('current_or_time_sensitive_query')
    if not has_grounded_facts(knowledge_content):
        reasons.append('local_knowledge_empty_or_unusable')
    if has_missing_markers(knowledge_content):
        reasons.append('local_knowledge_has_missing_markers')
    if is_problem_analysis_query(user_input):
        reasons.append('problem_analysis_requested')
    return list(dict.fromkeys(reasons))


def should_use_openclaw_lookup(config, user_input, intent, knowledge_content, manual_exists=True, manual_hit=True):
    return bool(get_openclaw_lookup_reasons(
        config,
        user_input,
        intent,
        knowledge_content,
        manual_exists=manual_exists,
        manual_hit=manual_hit,
    ))


def openclaw_outputs_have_grounding(result):
    if not result or not result.outputs:
        return False
    if result.task_type not in {'lookup', 'analyze'}:
        return False
    joined = '\n'.join(str(item) for item in result.outputs)
    source_signals = ['http://', 'https://', '來源', '根據', '官網', '課表', '當期幹部', '理事會', '公告']
    if not any(signal in joined for signal in source_signals):
        return False
    generic_starters = ('先', '再', '回答時', '列出', '提出')
    meaningful_lines = [
        line.strip() for line in joined.splitlines()
        if line.strip() and not line.strip().startswith(generic_starters)
    ]
    return bool(meaningful_lines)


def compact_log_text(value, max_chars=900):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if len(text) <= max_chars:
        return text
    return f'{text[:max_chars]}...'


def build_openclaw_reference_log_summary(result, max_outputs=3, max_output_chars=900):
    if not result or not result.outputs:
        return {
            'audit_ref': '',
            'task_type': '',
            'confidence': 0.0,
            'sources': [],
            'outputs': [],
        }

    joined = '\n'.join(str(item) for item in result.outputs)
    sources = sorted(set(
        raw_url.rstrip('.,，。;；')
        for raw_url in re.findall(r'https?://[^\s)）,，。;；]+', joined)
    ))
    outputs = [
        compact_log_text(item, max_output_chars)
        for item in result.outputs[:max_outputs]
        if str(item).strip()
    ]
    return {
        'audit_ref': result.audit_ref,
        'task_type': result.task_type,
        'confidence': result.confidence,
        'sources': sources,
        'outputs': outputs,
    }


def compact_knowledge_content(knowledge_content, max_sections=4, max_chars=3200):
    if not knowledge_content:
        return knowledge_content

    sections = split_markdown_sections(knowledge_content)
    if not sections:
        return knowledge_content[:max_chars]

    compact_blocks = []
    total_chars = 0
    for title, body in sections:
        block = f'## {title}\n{body}'.strip()
        if not block:
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining].rstrip()
        compact_blocks.append(block)
        total_chars += len(block)
        if len(compact_blocks) >= max_sections or total_chars >= max_chars:
            break

    return '\n\n'.join(compact_blocks).strip() or knowledge_content[:max_chars]


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
        if intent == INTENT_COURSE:
            course_sections = [
                s for s in sections
                if any(tag in s.path.lower() for tag in ['50_programs_and_events', '80_faq'])
            ]
            for section in course_sections:
                useful.append(f"--- 來自 {section.path} ---\n{section.content}")
        return '\n\n'.join(useful), manual_exists, manual_hit

    for section in matched:
        if section.path.startswith('memory/'):
            continue
        useful.append(f"--- 來自 {section.path} ---\n{section.content}")

    return '\n\n'.join(useful), manual_exists, manual_hit


def build_openclaw_prompt_guidance(sidecar_result):
    if not sidecar_result or not sidecar_result.outputs:
        return ''

    outputs = '\n'.join(f'- {item}' for item in sidecar_result.outputs if str(item).strip())
    if not outputs:
        return ''

    return (
        'OpenClaw 回覆指揮：\n'
        f'- 任務類型：{sidecar_result.task_type}\n'
        f'- 風險等級：{sidecar_result.risk_level}\n'
        f'- 需要人工核准：{"是" if sidecar_result.requires_approval else "否"}\n'
        '請依序完成：\n'
        '1. 像成熟的台北市健言社前輩與老師一樣，先拆解使用者真正要解決的問題。\n'
        '2. 先用本地知識確認事實；本地不足時，用 OpenClaw 查核結果補足。\n'
        '3. 若 OpenClaw 輸出包含明確來源，可作為本次回答依據；若只是建議草稿，僅可作為分析策略。\n'
        '4. 回答要短答優先、條理清楚、可直接貼到 LINE，並提醒仍需人工審核的新知識不可視為正式寫入。\n'
        'OpenClaw 輸出：\n'
        f'{outputs}\n'
        '限制：不可宣稱已部署、已正式更新 knowledge，或把無來源草稿當成已核准事實。\n'
    )


def should_retrieve_official_course_schedule(config, user_input, intent):
    if intent == INTENT_HOW_TO and is_skill_training_request(user_input):
        return False
    if getattr(config, 'official_site_retrieval_enabled', False):
        return True
    if intent not in {INTENT_COURSE, INTENT_PROMOTION}:
        return False

    text = (user_input or '').lower()
    return any(keyword.lower() in text for keyword in COURSE_SCHEDULE_RETRIEVAL_KEYWORDS)


def should_answer_official_course_info_directly(user_input, intent, course_info):
    if intent != INTENT_COURSE or not course_info:
        return False
    if is_skill_training_request(user_input):
        return False

    text = (user_input or '').lower()
    direct_keywords = COURSE_SCHEDULE_RETRIEVAL_KEYWORDS + [
        '課程',
        '課程安排',
        '目前培訓班',
        '培訓班',
        '最近有什麼課',
        '有什麼課',
    ]
    if not any(keyword.lower() in text for keyword in direct_keywords):
        return False

    source_signals = ['根據台北市健言社官網', '官網課表', '官網最新公告', 'https://tmc1974.com/']
    return any(signal in course_info for signal in source_signals)


def response_asks_user_to_lookup(response):
    text = re.sub(r'\s+', '', response or '')
    if not text:
        return False
    return any(re.search(pattern, text) for pattern in USER_LOOKUP_DEFLECTION_PATTERNS)


def build_post_response_official_lookup(providers, user_input, intent, logger):
    outputs = []

    lookup_steps = [
        ('官方課表/課程查核', getattr(providers, 'query_course_info', None), (user_input,)),
        ('官方公告/文宣查核', getattr(providers, 'query_latest_news', None), (user_input,)),
        ('官方網站查核', getattr(providers, 'query_official_site_map', None), (user_input, intent)),
    ]
    for label, func, args in lookup_steps:
        if not callable(func):
            continue
        try:
            result = func(*args)
        except Exception as exc:
            if logger:
                logger.warning('Post-response official lookup failed label=%s error=%s', label, exc)
            continue
        if result:
            outputs.append(f'{label}：\n{result}')

    if outputs:
        return '\n\n'.join(outputs)

    return (
        '我已查核目前可用的已核可官方來源，但沒有取得足夠明確的資料可以回答這題。'
        '目前本地知識庫與可查核官方來源都沒有這項資訊。'
    )


def build_prompt(state, user_input, knowledge_content, intent, manual_exists, manual_hit, history=None, lessons_guidance='', teaching_plan_guidance='', openclaw_guidance=''):
    # 統一在這裡組 prompt，把知識庫、規則、歷史與本次問題串起來。
    prompt_parts = [
        '你現在是「健言小龍蝦」，也是成熟、資深、可靠的台北市健言社前輩與老師。\n'
        '你的任務是在內部先判斷問題，再根據本地知識與 OpenClaw 官方查核結果回答；不要把內部判斷流程寫給使用者。\n'
        '【回答硬性規則】\n'
        '1. 優先使用「知識內容」中已明確出現的資訊；若有 OpenClaw 官方查核結果且含來源，也可用於本次回答。\n'
        '2. 若本地知識與 OpenClaw 查核都沒有明確答案，必須回答「目前本地知識庫與可查核官方來源都沒有這項資訊」或「目前提供的社團資料不足以確認」。\n'
        '3. 對任何社團事實問題，只要本地知識庫找不到明確答案，下一步一定是查核已核可官方來源（官網、課表、當期幹部、理事會、公告/活動頁、官方社群）；官方也沒有才說資料不足。\n'
        '4. 禁止自行補人物、時間、活動、職位、經歷；禁止把推測當成事實。\n'
        '5. 先回答使用者真正問的核心問題，再補充最多 2 點相關資訊。\n'
        '6. 若問題含有「目前、最近、現任、最新、本週、下週」等時間語意，優先使用本地現況資料；不足時使用 OpenClaw 查核結果。\n'
        '7. 回答要像前輩老師：先幫對方釐清問題，再給穩健答案、提醒風險與下一步；不要空泛長篇。\n'
        '8. 若問題意圖是 RULE_QUERY / COURSE_QUERY / ORG_QUERY，必須優先使用 90_club_manual.md；若 club_manual 不足，改用 OpenClaw 查核結果，仍不足才回覆資料不足。\n'
        '9. 若問題意圖是 PROMOTION_QUERY，請根據已知課程/公告內容寫成吸引人、邀請式的宣傳或社務布達，不可虛構未提供的細節。\n'
        '10. 若使用者提供已核可官方連結或要求看官網 / 官方社群，必須使用本次 OpenClaw / 官方查核結果；禁止回答「我無法主動瀏覽、無法解讀連結、只能依本地知識」這類與系統能力相反的說法。\n'
        '11. 若使用者詢問課表、時間表、開課時間、上課時間、課程時間、日期、幾點或何時，必須優先使用官網課表 / OpenClaw 官方查核結果；禁止只回答「本地知識庫沒有明確時間，請自行查詢官網」。\n'
        '11a. 若「知識內容」已包含台北市健言社官網課表、官網最新公告或 OpenClaw 官方查核的具體課程資料，必須直接摘要日期、主題、訓練項目、講師或公告標題；禁止只說「可參考官網或公告頁取得最新資訊」。\n'
        '12. 若問題不清楚、上下文不足或可能有多種解讀，先說明「我目前能合理判斷的是...」，列出 1-3 個合理可能性，再指出需要補充的資訊；不可把其中一種可能性當成事實。\n'
        '13. 不要把內部檔名、來源片段標記或 citation token 顯示給使用者；禁止輸出像 [cite: 90_club_manual.md] 這類標記。\n'
        '14. 禁止輸出內部流程或草稿語句，例如「首先，我們需要拆解使用者真正要解決的問題」、「我們先用本地知識確認事實」、「根據 OpenClaw 的回覆」、「以下是我的回答」。請直接給使用者可讀的最終答案。\n'
        '15. 若回答中得到本地沒有的新事實，可在回覆末尾用 <LEARNED>新事實；來源；確認日期</LEARNED> 標記，系統會寫入 pending review；不要告訴使用者這個標記。\n\n'
        f'問題意圖分類：{intent}\n'
        f'club_manual 是否存在：{manual_exists}\n'
        f'club_manual 是否命中可用段落：{manual_hit}\n\n'
        f'知識內容：\n{knowledge_content or "[無可用知識片段]"}\n\n'
    ]
    if lessons_guidance:
        prompt_parts.append(f'回答前套用 Lessons Learned：\n{lessons_guidance}\n\n')
    if teaching_plan_guidance:
        prompt_parts.append(f'回答前規劃（feature flag）：\n{teaching_plan_guidance}\n\n')
    if openclaw_guidance:
        prompt_parts.append(f'{openclaw_guidance}\n')
    if intent == INTENT_HOW_TO and is_skill_training_request(user_input):
        prompt_parts.append(
            '技能教練回答規則：\n'
            '- 使用者是在要你教他怎麼說，不是在問本週課表或官方資料。\n'
            '- 若使用者提到「總評、講評、主席、開場、題目、主題」，先直接點題，給一段可上台照念的版本。\n'
            '- 回答順序固定為：1) 可直接使用的開場稿；2) 這樣點題的邏輯；3) 可替換句。\n'
            '- 不要先解釋很多理論，不要回答課表資訊，不要請使用者去查官網。\n\n'
        )
    if history:
        prompt_parts.append('對話歷史（僅供語氣連貫，不可覆蓋知識事實）：\n')
        for i, (user_msg, ai_msg) in enumerate(history[-state.max_history_length:], 1):
            prompt_parts.append(f'{i}. 用戶：{user_msg}\n   小龍蝦：{ai_msg}\n')
        prompt_parts.append('\n')
    prompt_parts.append(f'當前用戶問題：{user_input}\n\n')
    prompt_parts.append('請用繁體中文作答。')
    return ''.join(prompt_parts)


def build_route_prompt(state, route_label, user_input, knowledge_content, intent, manual_exists, manual_hit, history=None, lessons_guidance='', teaching_plan_guidance='', openclaw_guidance=''):
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
    return build_prompt(
        state,
        user_input,
        routed_knowledge,
        intent,
        manual_exists,
        manual_hit,
        history,
        lessons_guidance=lessons_guidance,
        teaching_plan_guidance=teaching_plan_guidance,
        openclaw_guidance=openclaw_guidance
    )


def build_provider_prompt(state, route_label, provider_name, user_input, knowledge_content, intent, manual_exists, manual_hit, history=None, lessons_guidance='', teaching_plan_guidance='', openclaw_guidance=''):
    compact_history = history
    compact_lessons = lessons_guidance
    compact_knowledge = knowledge_content

    if provider_name == 'groq':
        compact_knowledge = compact_knowledge_content(knowledge_content, max_sections=4, max_chars=3200)
        compact_history = history[-2:] if history else None
        compact_lessons = (lessons_guidance or '')[:600]

    return build_route_prompt(
        state,
        route_label,
        user_input,
        compact_knowledge,
        intent,
        manual_exists,
        manual_hit,
        history=compact_history,
        lessons_guidance=compact_lessons,
        teaching_plan_guidance=teaching_plan_guidance,
        openclaw_guidance=openclaw_guidance
    )


def ask_ai(
    config,
    state,
    logger,
    providers,
    user_input,
    history=None,
    lessons_guidance='',
    dispatcher=None,
    tool_registry=None,
    policy_engine=None,
    approval_gate=None,
):
    tracker = RequestStateTracker()
    state.last_request_tracker = tracker.get_summary  # Store getter for current summary

    try:
        tracker.start_step('initialization')
        state.last_agent_decision = None
        state.last_sidecar_decision = None
        state.last_tool_decision = None
        sections = load_knowledge_sections(config, logger)
        if not sections:
            tracker.add_error('knowledge_load', 'Cannot load knowledge base sections')
            logger.error('Cannot load knowledge base sections')
            tracker.end_step(success=False, result='knowledge_load_failed')
            return '小龍蝦找不到知識庫，請稍後再試。'
        tracker.end_step(success=True, result='knowledge_loaded')

        tracker.start_step('intent_classification')
        intent = classify_question_intent(user_input)
        task_type = classify_openclaw_task_type(user_input, intent)
        tracker.end_step(success=True, result={'intent': intent, 'task_type': task_type})

        tracker.start_step('tool_evaluation')
        tool_decision = evaluate_controlled_tool_use(state, config, tool_registry, policy_engine, approval_gate, task_type, user_input)
        logger.info(
            'AUDIT controlled tool task_type=%s tool=%s allowed=%s approval=%s reason=%s',
            task_type,
            tool_decision.get('tool_name'),
            tool_decision.get('allowed'),
            tool_decision.get('requires_approval'),
            tool_decision.get('reason'),
        )
        controlled_response = build_controlled_action_response(task_type, tool_decision)
        if controlled_response:
            tracker.end_step(success=True, result='controlled_response')
            return controlled_response
        tracker.end_step(success=True, result='tool_evaluation_passed')

        if config.agent_path_enabled:
            tracker.start_step('agent_processing')
            agent_intent, agent_intent_reason = classify_agent_intent(user_input)
            task_decision = dispatch_task(agent_intent, user_input)
            action_result = run_action(task_decision.action)
            state.last_agent_decision = {
                'enabled': True,
                'intent': agent_intent,
                'intent_reason': agent_intent_reason,
                'action': action_result.action,
                'action_status': action_result.status,
                'dispatch_reason': task_decision.reason,
            }
            logger.info(
                'AUDIT agent decision intent=%s action=%s status=%s reason=%s',
                agent_intent,
                action_result.action,
                action_result.status,
                task_decision.reason,
            )
            if action_result.action == 'execute' or action_result.status == 'forbidden':
                tracker.end_step(success=True, result='agent_forbidden')
                return 'Agent execute action is currently forbidden by default. Please confirm before any execution.'
            tracker.end_step(success=True, result='agent_processed')

        tracker.start_step('knowledge_context_building')
        scoped_knowledge, manual_exists, manual_hit = build_knowledge_context(sections, intent)
        teaching_plan = build_teaching_plan(intent, user_input) if config.teaching_planner_enabled else None
        teaching_plan_guidance = format_teaching_plan_for_prompt(teaching_plan, intent) if teaching_plan else ''
        tracker.end_step(success=True, result='context_built')

        course_info_retrieved = False
        if should_retrieve_official_course_schedule(config, user_input, intent):
            tracker.start_step('official_course_schedule_retrieval')
            try:
                course_info = providers.query_course_info(user_input)
                if course_info and intent in {INTENT_COURSE, INTENT_PROMOTION}:
                    scoped_knowledge += f'\n\n--- 來自 台北市健言社官網課表 ---\n{course_info}'
                    course_info_retrieved = True
                    logger.info('Official course schedule retrieval added context intent=%s', intent)
                    if should_answer_official_course_info_directly(user_input, intent, course_info):
                        tracker.end_step(success=True, result='course_schedule_direct_answer')
                        return course_info
                tracker.end_step(success=True, result='course_schedule_retrieved' if course_info_retrieved else 'no_course_schedule_match')
            except Exception as e:
                tracker.add_error('course_schedule_retrieval', str(e))
                logger.warning('Official course schedule retrieval failed: %s', e)
                tracker.end_step(success=False, result='course_schedule_retrieval_failed')

        openclaw_guidance = ''
        sidecar_result = None
        openclaw_lookup_reasons = get_openclaw_lookup_reasons(
            config,
            user_input,
            intent,
            scoped_knowledge,
            manual_exists=manual_exists,
            manual_hit=manual_hit,
        )
        needs_openclaw_lookup = bool(openclaw_lookup_reasons)
        logger.info(
            'OPENCLAW_USAGE_CHECK intent=%s task_type=%s needs_lookup=%s reasons=%s manual_exists=%s manual_hit=%s grounded=%s missing_markers=%s（判斷是否需要官方查核）',
            intent,
            task_type,
            needs_openclaw_lookup,
            openclaw_lookup_reasons,
            manual_exists,
            manual_hit,
            has_grounded_facts(scoped_knowledge),
            has_missing_markers(scoped_knowledge),
        )
        should_dispatch_sidecar = config.sidecar_enabled and (task_type == 'command' or needs_openclaw_lookup)
        if should_dispatch_sidecar:
            logger.info(
                'OPENCLAW_DISPATCH_PLANNED intent=%s phase=%s reasons=%s（本地知識不足或任務需要，準備走 sidecar/OpenClaw）',
                intent,
                config.openclaw_phase,
                openclaw_lookup_reasons,
            )
            tracker.start_step('sidecar_processing')
            openclaw_phase = config.openclaw_phase if config.openclaw_phase in {'observe', 'suggest', 'assist'} else 'suggest'
            if openclaw_phase == 'observe' and task_type == 'command':
                state.last_sidecar_decision = {
                    'enabled': True,
                    'should_call': False,
                    'reason': 'phase-observe',
                    'task_type': 'observe',
                    'requires_approval': True,
                    'fallback': 'pending_review',
                    'phase': openclaw_phase,
                }
                tracker.end_step(success=True, result='sidecar_observe_phase')
                return '這個請求需要 pending review。OpenClaw 目前位於 observe phase，只記錄與審核，不提供自動建議。'
            if openclaw_phase == 'observe':
                state.last_sidecar_decision = {
                    'enabled': True,
                    'should_call': False,
                    'reason': 'phase-observe',
                    'task_type': 'lookup',
                    'requires_approval': False,
                    'fallback': 'local_only',
                    'phase': openclaw_phase,
                }
                tracker.end_step(success=True, result='sidecar_observe_phase_lookup_skipped')
            else:
                active_dispatcher = dispatcher or SidecarDispatcher(
                    logger,
                    config=config,
                    mode=config.sidecar_mode,
                    timeout_seconds=config.sidecar_timeout_seconds,
                )
                decision, sidecar_result = active_dispatcher.dispatch(
                    user_input,
                    intent,
                    context={
                        'route_intent': intent,
                        'official_course_schedule_retrieved': course_info_retrieved,
                        'grounding_context': scoped_knowledge[:4000],
                        'needs_official_lookup': needs_openclaw_lookup,
                        'lookup_reasons': openclaw_lookup_reasons,
                        'approved_sources': [
                            'https://tmc1974.com/',
                            'https://tmc1974.com/schedule/',
                            'https://tmc1974.com/presidents/',
                            'https://tmc1974.com/leaders/',
                            'https://tmc1974.com/board-members/',
                            'https://www.instagram.com/taipeitoastmasters/',
                            'https://www.youtube.com/@1974toastmaster/videos',
                            'https://www.facebook.com/tmc1974',
                            'https://www.flickr.com/photos/133676498@N06/albums/',
                            'official announcements and course categories',
                        ],
                        'problem_decomposition': [
                            '判斷使用者是在問事實、現況、宣傳、教學還是問題分析。',
                            '列出本地知識已知、未知與需要官方查核的欄位。',
                            '用前輩老師口吻給短答、依據、風險提醒與下一步。',
                        ],
                    }
                )
                state.last_sidecar_decision = {
                    'enabled': True,
                    'should_call': decision.should_call_sidecar,
                    'reason': decision.reason,
                    'task_type': decision.task_type,
                    'requires_approval': bool(sidecar_result.requires_approval) if sidecar_result else False,
                    'fallback': decision.reason if not decision.should_call_sidecar else 'none',
                    'phase': openclaw_phase,
                    'status': sidecar_result.status if sidecar_result else None,
                    'risk_level': sidecar_result.risk_level if sidecar_result else None,
                    'audit_ref': sidecar_result.audit_ref if sidecar_result else None,
                    'outputs': sidecar_result.outputs[:5] if sidecar_result else [],
                    'learnable': bool(sidecar_result and sidecar_result.task_type in {'lookup', 'analyze'} and sidecar_result.outputs),
                }
                logger.info(
                    'OPENCLAW_USAGE_DECISION timing=before_provider_call should_call=%s decision_reason=%s task_type=%s lookup_reasons=%s audit_ref=%s status=%s（OpenClaw 呼叫決策完成）',
                    decision.should_call_sidecar,
                    decision.reason,
                    decision.task_type,
                    openclaw_lookup_reasons,
                    sidecar_result.audit_ref if sidecar_result else None,
                    sidecar_result.status if sidecar_result else None,
                )
                openclaw_guidance = build_openclaw_prompt_guidance(sidecar_result)
                if openclaw_outputs_have_grounding(sidecar_result):
                    reference_summary = build_openclaw_reference_log_summary(sidecar_result)
                    logger.info(
                        'OPENCLAW_REFERENCE_USED timing=before_provider_prompt audit_ref=%s task_type=%s confidence=%s trigger_reasons=%s sources=%s outputs=%s（官方查核結果會放入本次回答上下文）',
                        reference_summary['audit_ref'],
                        reference_summary['task_type'],
                        reference_summary['confidence'],
                        openclaw_lookup_reasons,
                        reference_summary['sources'],
                        reference_summary['outputs'],
                    )
                    scoped_knowledge += (
                        '\n\n--- 來自 OpenClaw 官方查核（pending review） ---\n'
                        + '\n'.join(f'- {item}' for item in sidecar_result.outputs)
                    )
                    openclaw_direct_answer = '\n'.join(str(item).strip() for item in sidecar_result.outputs if str(item).strip())
                    if should_answer_official_course_info_directly(user_input, intent, openclaw_direct_answer):
                        tracker.end_step(success=True, result='openclaw_course_schedule_direct_answer')
                        return openclaw_direct_answer
                tracker.end_step(success=True, result='sidecar_processed')

        # 規則/課程/組織類問題若 club_manual 無命中，需先嘗試 OpenClaw；仍無依據才保守拒答。
        if intent in MANUAL_PRIORITY_INTENTS and (not manual_exists or not manual_hit) and not openclaw_outputs_have_grounding(sidecar_result):
            logger.info(
                'INSUFFICIENT_MANUAL_KNOWLEDGE intent=%s manual_exists=%s manual_hit=%s（規則/課程/組織資料不足，保守回答）',
                intent,
                manual_exists,
                manual_hit,
            )
            tracker.end_step(success=True, result='insufficient_manual_knowledge')
            return build_insufficient_knowledge_response(
                teaching_plan.next_action if teaching_plan else '請提供對應課程規則來源後再詢問。'
            )

        if config.official_site_retrieval_enabled and not is_skill_training_request(user_input):
            tracker.start_step('official_site_retrieval')
            try:
                course_info = None if course_info_retrieved else providers.query_course_info(user_input)
                if course_info and intent in {INTENT_COURSE, INTENT_PROMOTION}:
                    scoped_knowledge += f'\n\n--- 來自 台北市健言社官網 ---\n{course_info}'

                news_info = providers.query_latest_news(user_input)
                if news_info and intent in {INTENT_ACTIVITY, INTENT_ANNOUNCEMENT, INTENT_PROMOTION}:
                    scoped_knowledge += f'\n\n--- 來自 台北市健言社最新消息 ---\n{news_info}'

                official_site_info = providers.query_official_site_map(user_input, intent)
                if official_site_info:
                    scoped_knowledge += f'\n\n--- 來自 台北市健言社官網 site map ---\n{official_site_info}'
                tracker.end_step(success=True, result='site_retrieval_completed')
            except Exception as e:
                tracker.add_error('site_retrieval', str(e))
                logger.warning('Official site retrieval failed: %s', e)
                tracker.end_step(success=False, result='site_retrieval_failed')

        if intent in FACT_REQUIRED_INTENTS and not has_grounded_facts(scoped_knowledge):
            logger.info(
                'OPENCLAW_NO_GROUNDED_ANSWER timing=before_provider_call intent=%s lookup_attempted=%s lookup_reasons=%s sidecar_status=%s audit_ref=%s（找不到可依據事實，避免幻覺改回資料不足）',
                intent,
                should_dispatch_sidecar,
                openclaw_lookup_reasons,
                sidecar_result.status if sidecar_result else None,
                sidecar_result.audit_ref if sidecar_result else None,
            )
            tracker.end_step(success=True, result='insufficient_facts')
            return build_insufficient_knowledge_response(
                teaching_plan.next_action if teaching_plan else '請提供可核對的社團資料來源後再詢問。'
            )

        tracker.start_step('routing')
        route_label, route_reason = classify_request(config, state, providers, user_input)
        if route_label == state.route_local and should_force_general_route(user_input, intent):
            logger.info('Overriding LOCAL route to GENERAL for non-sensitive club query intent=%s original_reason=%s', intent, route_reason)
            route_label = state.route_general
            route_reason = f'{route_reason}->override:general'

        provider_chain = get_route_provider_chain(state, route_label, providers)
        logger.info('Router selected route=%s reason=%s intent=%s providers=%s', route_label, route_reason, intent, provider_chain)
        tracker.end_step(success=True, result={'route': route_label, 'providers': provider_chain})
        if not provider_chain and sidecar_result:
            guidance = format_sidecar_guidance(sidecar_result).strip()
            if guidance:
                return guidance

        # 改進的 retry 邏輯：exponential backoff，最多 3 次，整條鏈失敗才重試
        max_attempts = 3
        base_backoff = 1.0
        max_backoff = 10.0

        for attempt in range(max_attempts):
            tracker.start_step(f'provider_attempt_{attempt + 1}')
            attempt_success = False

            for provider_name in provider_chain:
                tracker.start_step(f'provider_{provider_name}_call')
                logger.debug('Attempting provider=%s route=%s attempt=%d', provider_name, route_label, attempt + 1)

                prompt = build_provider_prompt(
                    state,
                    route_label,
                    provider_name,
                    user_input,
                    scoped_knowledge,
                    intent,
                    manual_exists,
                    manual_hit,
                    history=history,
                    lessons_guidance=lessons_guidance,
                    teaching_plan_guidance=teaching_plan_guidance,
                    openclaw_guidance=openclaw_guidance
                )

                result = None
                provider_timeout = getattr(config, 'provider_timeout_seconds', 30)  # Default 30s timeout

                try:
                    with timeout_context(provider_timeout):
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
                except TimeoutError:
                    tracker.add_error('provider_timeout', f'Provider {provider_name} timed out after {provider_timeout}s')
                    logger.warning('Provider timeout provider=%s route=%s timeout=%ds', provider_name, route_label, provider_timeout)
                except Exception as e:
                    error_type = type(e).__name__
                    tracker.add_error('provider_error', f'Provider {provider_name} failed: {error_type}', {'exception': str(e)})
                    logger.warning('Provider error provider=%s route=%s error=%s', provider_name, route_label, e)

                if result:
                    logger.info('Success with provider=%s route=%s intent=%s attempt=%d', provider_name, route_label, intent, attempt + 1)
                    tracker.end_step(success=True, result=f'success_with_{provider_name}')
                    attempt_success = True
                    tracker.end_step(success=True, result=f'attempt_{attempt + 1}_success')
                    if response_asks_user_to_lookup(result):
                        logger.info(
                            'Provider response asked user to lookup official sources; running post-response official lookup intent=%s provider=%s',
                            intent,
                            provider_name,
                        )
                        tracker.start_step('post_response_official_lookup')
                        official_lookup_response = build_post_response_official_lookup(providers, user_input, intent, logger)
                        tracker.end_step(success=True, result='post_response_official_lookup_completed')
                        return official_lookup_response
                    return result

                tracker.end_step(success=False, result=f'{provider_name}_failed')
                logger.warning('Provider failed provider=%s route=%s, trying next fallback', provider_name, route_label)

            tracker.end_step(success=attempt_success, result=f'attempt_{attempt + 1}_completed')

            if attempt_success:
                break

            if attempt < max_attempts - 1:
                backoff_seconds = min(base_backoff * (2 ** attempt), max_backoff)
                tracker.record_retry(attempt + 1, 'chain_failed', backoff_seconds)
                logger.warning('All providers failed in attempt %d for route=%s, retrying in %.1fs...', attempt + 1, route_label, backoff_seconds)
                time.sleep(backoff_seconds)

        tracker.add_error('all_attempts_failed', f'All {max_attempts} attempts failed for route {route_label}')
        logger.error('All providers failed after %d attempts for route=%s chain=%s', max_attempts, route_label, provider_chain)
        tracker.end_step(success=False, result='all_attempts_failed')
        return '小龍蝦無法連線到任何 AI 服務，請稍後再試。'

    except Exception as e:
        tracker.add_error('unexpected_error', str(e), {'traceback': str(e.__traceback__)})
        logger.exception('Unexpected error in ask_ai')
        tracker.end_step(success=False, result='unexpected_error')
        return '小龍蝦發生意外錯誤，請稍後再試。'
