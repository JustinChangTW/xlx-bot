import uuid

from .gateway import MockGateway, RealGateway
from .schemas import DispatchDecision, SidecarRequest, SidecarResult


TASK_KEYWORDS = {
    'plan': ['計畫', '規劃', 'roadmap', '里程碑'],
    'suggest': ['建議', '方案', '草稿', '怎麼做'],
    'debug': ['debug', '除錯', '修復', '錯誤', '故障'],
    'project': ['專案', '任務', '重構', '整合'],
}


class SidecarDispatcher:
    def __init__(self, logger, gateway=None, mode='mock', timeout_seconds=8):
        self.logger = logger
        self.mode = (mode or 'mock').strip().lower()
        self.timeout_seconds = int(timeout_seconds)
        self.gateway = gateway or self._build_gateway()

    def _build_gateway(self):
        if self.mode == 'mock':
            return MockGateway()
        if self.mode == 'real':
            return RealGateway()

        self.logger.warning('Invalid SIDECAR_MODE=%s, fallback to mock gateway', self.mode)
        self.mode = 'mock'
        return MockGateway()

    def _infer_task_type(self, user_input: str) -> str:
        text = (user_input or '').lower()
        for task_type, keywords in TASK_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return task_type
        return ''

    def decide(self, user_input: str, intent: str) -> DispatchDecision:
        task_type = self._infer_task_type(user_input)
        if not task_type:
            return DispatchDecision(False, 'non-task-query', '')

        # 事實型與公告查詢預設不需要走 sidecar。
        if intent in {'FACT_QUERY', 'MEMBER_QUERY', 'ACTIVITY_QUERY', 'ANNOUNCEMENT_QUERY', 'HISTORY_INTRO', 'GENERAL_OVERVIEW'}:
            return DispatchDecision(False, 'fact-first', task_type)

        return DispatchDecision(True, 'task-query', task_type)

    def dispatch(self, user_input: str, intent: str, context=None) -> tuple[DispatchDecision, SidecarResult | None]:
        decision = self.decide(user_input, intent)
        if not decision.should_call_sidecar:
            return decision, None

        trace_id = uuid.uuid4().hex
        request = SidecarRequest(
            user_input=user_input,
            task_type=decision.task_type,
            intent=intent,
            trace_id=trace_id,
            context=context or {},
        )

        try:
            result = self.gateway.call(request, timeout_seconds=self.timeout_seconds)
            self.logger.info(
                'Sidecar success mode=%s task_type=%s status=%s approval=%s audit_ref=%s',
                self.mode,
                result.task_type,
                result.status,
                result.requires_approval,
                result.audit_ref,
            )
            return decision, result
        except Exception as exc:  # defensive fallback
            self.logger.warning('Sidecar failed trace_id=%s reason=%s', trace_id, str(exc)[:200])
            return DispatchDecision(False, 'sidecar-fallback', decision.task_type), None


def format_sidecar_guidance(result: SidecarResult | None) -> str:
    if not result or not result.outputs:
        return ''

    lines = [
        '',
        '【Sidecar 任務建議（草稿）】',
        f'- 任務類型：{result.task_type}',
        f'- 風險等級：{result.risk_level}',
        f'- 需要人工核准：{"是" if result.requires_approval else "否"}',
    ]
    for idx, item in enumerate(result.outputs, 1):
        lines.append(f'- 建議 {idx}：{item}')
    lines.append('- 說明：目前僅提供建議，不會自動執行。')
    return '\n'.join(lines)
