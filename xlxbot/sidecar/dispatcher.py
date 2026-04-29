import re
import uuid

from .gateway import MockGateway, OpenClawGateway
from .schemas import DispatchDecision, SidecarRequest, SidecarResult
from ..tool_executor import ToolExecutor


TASK_KEYWORDS = {
    'plan': ['計畫', '規劃', 'roadmap', '里程碑'],
    'suggest': ['建議', '方案', '草稿', '怎麼做', '宣傳', '文宣', '社務布達', '作文宣', '寫文宣'],
    'debug': ['debug', '除錯', '修復', '錯誤', '故障'],
    'project': ['專案', '任務', '重構', '整合'],
    'analyze': ['分析', '拆解', '判斷', '比對', '確認'],
    'lookup': ['查詢', '查核', '官網', '來源', '最新', '現任', '本週', '本周', '下週', '下周', '課表', '幹部名單', '歷任', '資歷', 'presidents', 'tmc1974.com'],
}

OFFICIAL_URL_RE = re.compile(
    r'https?://(?:'
    r'(?:www\.)?tmc1974\.com/'
    r'|www\.instagram\.com/taipeitoastmasters/?'
    r'|www\.youtube\.com/@1974toastmaster(?:/videos)?'
    r'|www\.youtube\.com/user/1974toastmaster'
    r'|www\.facebook\.com/tmc1974/?'
    r'|www\.flickr\.com/photos/133676498@N06/albums/?'
    r')',
    re.IGNORECASE,
)

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
        logger.info(
            'Building OpenClaw gateway base_url=%s endpoint=%s timeout=%s（建立真實 OpenClaw gateway）',
            getattr(config, 'openclaw_base_url', ''),
            getattr(config, 'openclaw_endpoint_path', '/v1/sidecar/dispatch'),
            timeout,
        )
        return OpenClawGateway(
            base_url=getattr(config, 'openclaw_base_url', ''),
            endpoint_path=getattr(config, 'openclaw_endpoint_path', '/v1/sidecar/dispatch'),
            api_key=getattr(config, 'openclaw_api_key', ''),
            timeout_seconds=timeout,
        )

    if mode != 'mock':
        logger.warning('Unknown SIDECAR_MODE=%s, fallback to mock（未知 sidecar 模式，改用 mock 保守執行）', mode)
    else:
        logger.info('Building mock sidecar gateway（使用 mock sidecar，不會呼叫外部 OpenClaw）')
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
            self.logger.warning('Unknown sidecar mode=%s, fallback to mock（未知 sidecar 模式，改用 mock）', requested_mode)
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
            self.logger.debug('Sidecar not ready: SIDECAR_ENABLED is false（sidecar 未啟用）')
            return False, ['SIDECAR_ENABLED']
        if self.mode == 'openclaw':
            missing = []
            if not getattr(self.config, 'openclaw_base_url', ''):
                missing.append('OPENCLAW_BASE_URL')
            if missing:
                self.logger.debug('Sidecar not ready missing=%s（OpenClaw 設定不足）', missing)
            return not missing, missing
        return True, []

    def _infer_task_type(self, user_input: str) -> str:
        text = (user_input or '').lower()
        for task_type, keywords in TASK_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return task_type
        return ''

    def decide(self, user_input: str, intent: str, context=None) -> DispatchDecision:
        context = context or {}
        task_type = self._infer_task_type(user_input)
        text = (user_input or '').lower()
        has_official_url = bool(OFFICIAL_URL_RE.search(text))
        if not task_type and context.get('needs_official_lookup'):
            task_type = 'lookup'
        if not task_type and has_official_url:
            task_type = 'lookup'
        if not task_type:
            self.logger.debug('Sidecar decision skipped intent=%s reason=non-task-query（不是需要 sidecar 的任務型問題）', intent)
            return DispatchDecision(False, 'non-task-query', '')

        # observe phase 只做觀測，不實際向 OpenClaw 取建議或查核結果。
        openclaw_phase = getattr(self.config, 'openclaw_phase', 'suggest') if self.config else 'suggest'
        if openclaw_phase == 'observe':
            self.logger.info('Sidecar decision skipped task_type=%s phase=observe（OpenClaw observe 階段只記錄不呼叫）', task_type)
            return DispatchDecision(False, 'phase-observe', task_type)

        if intent in FACT_FIRST_INTENTS and task_type in {'lookup', 'analyze'}:
            self.logger.info('Sidecar decision official lookup intent=%s task_type=%s（事實/現況問題，先做官方查核）', intent, task_type)
            return DispatchDecision(True, 'official-lookup', task_type)

        if task_type in {'lookup', 'analyze'} and (context.get('needs_official_lookup') or has_official_url):
            self.logger.info(
                'Sidecar decision official lookup task_type=%s needs_lookup=%s has_official_url=%s（本地不足或使用者提供官方連結）',
                task_type,
                context.get('needs_official_lookup'),
                has_official_url,
            )
            return DispatchDecision(True, 'official-lookup', task_type)

        if intent in {'RULE_QUERY', 'COURSE_QUERY', 'ORG_QUERY'}:
            project_like_keywords = ['重構', '整合', '專案', 'project', 'debug', '除錯', '錯誤', '故障']
            if any(keyword in text for keyword in project_like_keywords):
                return DispatchDecision(True, 'task-query', task_type)
            self.logger.debug('Sidecar decision skipped intent=%s reason=non-task-intent（規則/課程/組織問題先走知識回答）', intent)
            return DispatchDecision(False, 'non-task-intent', task_type)

        return DispatchDecision(True, 'task-query', task_type)

    def dispatch(self, user_input: str, intent: str, context=None) -> tuple[DispatchDecision, SidecarResult | None]:
        context = context or {}
        decision = self.decide(user_input, intent, context=context)
        if not decision.should_call_sidecar:
            self.logger.info(
                'Sidecar dispatch skipped intent=%s reason=%s task_type=%s（本次不呼叫 OpenClaw/sidecar）',
                intent,
                decision.reason,
                decision.task_type,
            )
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
            self.logger.info(
                'Sidecar dispatch start trace_id=%s intent=%s task_type=%s mode=%s phase=%s（準備呼叫 sidecar/OpenClaw）',
                trace_id,
                intent,
                decision.task_type,
                self.mode,
                self.phase,
            )
            result = self.gateway.call(request)
            if result.status not in {'ok', 'degraded'}:
                self.logger.warning('Sidecar non-ok status=%s trace_id=%s（sidecar 回傳非預期狀態，改走保守 fallback）', result.status, trace_id)
                return DispatchDecision(False, 'sidecar-non-ok', decision.task_type), None

            # assist phase 才可能交給受控工具層；仍會經 risk 與 approval gate 判斷。
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
                    self.logger.info('Sidecar execution completed success=%s audit_ref=%s（受控工具執行完成）',
                                   exec_result.success, result.audit_ref)

            self.logger.info(
                'Sidecar success task_type=%s status=%s approval=%s execution_allowed=%s audit_ref=%s（sidecar/OpenClaw 呼叫成功）',
                result.task_type,
                result.status,
                result.requires_approval,
                result.execution_allowed,
                result.audit_ref,
            )
            return decision, result
        except Exception as exc:  # defensive fallback
            self.logger.warning('Sidecar failed trace_id=%s reason=%s（sidecar/OpenClaw 失敗，回答流程需保守降級）', trace_id, str(exc)[:200])
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
