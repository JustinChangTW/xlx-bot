import uuid

from .gateway import MockGateway, OpenClawGateway
from .schemas import DispatchDecision, SidecarRequest, SidecarResult
from ..tool_executor import ToolExecutor


TASK_KEYWORDS = {
    'plan': ['計畫', '規劃', 'roadmap', '里程碑'],
    'suggest': ['建議', '方案', '草稿', '怎麼做', '宣傳', '文宣', '社務布達', '作文宣', '寫文宣'],
    'debug': ['debug', '除錯', '修復', '錯誤', '故障'],
    'project': ['專案', '任務', '重構', '整合'],
}

FACT_FIRST_INTENTS = {
    'FACT_QUERY',
    'MEMBER_QUERY',
    'ACTIVITY_QUERY',
    'ANNOUNCEMENT_QUERY',
    'HISTORY_INTRO',
    'GENERAL_OVERVIEW',
}


def build_sidecar_gateway(config, logger):
    mode = (getattr(config, 'sidecar_mode', 'mock') or 'mock').strip().lower()
    timeout = getattr(config, 'sidecar_timeout_seconds', 8)

    if mode == 'openclaw':
        return OpenClawGateway(
            base_url=getattr(config, 'openclaw_base_url', ''),
            endpoint_path=getattr(config, 'openclaw_endpoint_path', '/v1/sidecar/dispatch'),
            api_key=getattr(config, 'openclaw_api_key', ''),
            timeout_seconds=timeout,
        )

    if mode != 'mock':
        logger.warning('Unknown SIDECAR_MODE=%s, fallback to mock', mode)
    return MockGateway()


class SidecarDispatcher:
    def __init__(self, logger, config=None, gateway=None, mode=None, timeout_seconds=None, tool_executor=None):
        self.logger = logger
        self.config = config
        requested_mode = (mode or getattr(config, 'sidecar_mode', 'mock') or 'mock').strip().lower()
        self.mode = requested_mode if requested_mode in {'mock', 'openclaw'} else 'mock'
        self.timeout_seconds = int(timeout_seconds or getattr(config, 'sidecar_timeout_seconds', 8) or 8)
        self.phase = getattr(config, 'openclaw_phase', 'suggest')  # Phase: observe, suggest, assist
        if requested_mode not in {'mock', 'openclaw'}:
            self.logger.warning('Unknown sidecar mode=%s, fallback to mock', requested_mode)
        if gateway is not None:
            self.gateway = gateway
        elif config is not None:
            self.gateway = build_sidecar_gateway(config, logger)
        else:
            self.gateway = MockGateway()
        self.tool_executor = tool_executor

    def is_ready(self):
        if not self.config:
            return True, []
        if not getattr(self.config, 'sidecar_enabled', False):
            return False, ['SIDECAR_ENABLED']
        if self.mode == 'openclaw':
            missing = []
            if not getattr(self.config, 'openclaw_base_url', ''):
                missing.append('OPENCLAW_BASE_URL')
            return not missing, missing
        return True, []

    def _infer_task_type(self, user_input: str) -> str:
        text = (user_input or '').lower()
        for task_type, keywords in TASK_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return task_type
        return ''

    def decide(self, user_input: str, intent: str) -> DispatchDecision:
        task_type = self._infer_task_type(user_input)
        text = (user_input or '').lower()
        if not task_type:
            return DispatchDecision(False, 'non-task-query', '')

        # Check OpenClaw phase
        openclaw_phase = getattr(self.config, 'openclaw_phase', 'suggest') if self.config else 'suggest'
        if openclaw_phase == 'observe':
            return DispatchDecision(False, 'phase-observe', task_type)

        # 事實型與公告查詢預設不觸發 sidecar。
        if intent in FACT_FIRST_INTENTS:
            return DispatchDecision(False, 'fact-first', task_type)

        if intent in {'RULE_QUERY', 'COURSE_QUERY', 'ORG_QUERY'}:
            project_like_keywords = ['重構', '整合', '專案', 'project', 'debug', '除錯', '錯誤', '故障']
            if any(keyword in text for keyword in project_like_keywords):
                return DispatchDecision(True, 'task-query', task_type)
            return DispatchDecision(False, 'non-task-intent', task_type)

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
            result = self.gateway.call(request)
            if result.status not in {'ok', 'degraded'}:
                self.logger.warning('Sidecar non-ok status=%s trace_id=%s', result.status, trace_id)
                return DispatchDecision(False, 'sidecar-non-ok', decision.task_type), None

            # Phase C: Controlled automation - execute if allowed
            if self.phase == 'assist' and self.tool_executor:
                result.execution_allowed = self.tool_executor.can_execute(
                    tool_name='sidecar_dispatch',
                    risk=result.risk_level,
                    requires_approval=result.requires_approval
                )
                if result.execution_allowed:
                    exec_result = self.tool_executor.execute(
                        tool_name='sidecar_dispatch',
                        action='sidecar_dispatch',
                        risk=result.risk_level,
                        requires_approval=result.requires_approval,
                        context={'audit_ref': result.audit_ref, 'sidecar_result': result},
                        audit_ref=result.audit_ref
                    )
                    result.execution_result = exec_result
                    self.logger.info('Sidecar execution completed success=%s audit_ref=%s',
                                   exec_result.success, result.audit_ref)

            self.logger.info(
                'Sidecar success task_type=%s status=%s approval=%s execution_allowed=%s audit_ref=%s',
                result.task_type,
                result.status,
                result.requires_approval,
                result.execution_allowed,
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
    if hasattr(result, 'execution_allowed') and result.execution_allowed:
        lines.append('- 執行狀態：已自動執行')
        if result.execution_result and result.execution_result.success:
            lines.append(f'- 執行結果：{result.execution_result.output}')
        elif result.execution_result:
            lines.append(f'- 執行錯誤：{result.execution_result.error}')
    else:
        lines.append('- 說明：目前僅提供建議，不會自動執行。')
    return '\n'.join(lines)
