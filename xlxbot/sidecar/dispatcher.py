import os
import uuid

from .gateway import MockGateway, OpenClawGatewayClient, RealGateway
from .schemas import DispatchDecision, SidecarRequest, SidecarResult


TASK_KEYWORDS = {
    'plan': ['計畫', '規劃', 'roadmap', '里程碑'],
    'suggest': ['建議', '方案', '草稿', '怎麼做'],
    'report': ['report', '報告', '回報', '整理重點'],
}
TASK_INTENTS = {'PROMOTION_QUERY', 'HOW_TO'}


class SidecarDispatcher:
    def __init__(self, logger, gateway=None, mode='mock', timeout_seconds=8):
        self.logger = logger
        self.mode = (mode or 'mock').strip().lower()
        self.timeout_seconds = int(timeout_seconds)
        self.gateway = gateway or self._build_gateway()

    def _build_gateway(self):
        if self.mode == 'mock':
            return MockGateway()
        if self.mode in {'real', 'openclaw'}:
            return OpenClawGatewayClient(
                base_url=os.getenv('OPENCLAW_GATEWAY_URL', 'http://127.0.0.1:9099'),
                endpoint=os.getenv('OPENCLAW_GATEWAY_ENDPOINT', '/v1/dispatch'),
                timeout_seconds=int(os.getenv('OPENCLAW_TIMEOUT_SECONDS', str(self.timeout_seconds))),
                max_retries=int(os.getenv('OPENCLAW_MAX_RETRIES', '2')),
                circuit_fail_threshold=int(os.getenv('OPENCLAW_CIRCUIT_FAIL_THRESHOLD', '3')),
                circuit_cooldown_seconds=int(os.getenv('OPENCLAW_CIRCUIT_COOLDOWN_SECONDS', '30')),
            )
        if self.mode == 'legacy-real':
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
        if intent not in TASK_INTENTS:
            return DispatchDecision(False, 'non-task-intent', '')

        task_type = self._infer_task_type(user_input)
        if not task_type:
            return DispatchDecision(False, 'non-task-query', '')

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
                'AUDIT sidecar decision=success mode=%s task_type=%s status=%s requires_approval=%s audit_ref=%s fallback=none',
                self.mode,
                result.task_type,
                result.status,
                result.requires_approval,
                result.audit_ref,
            )
            return decision, result
        except Exception as exc:  # defensive fallback
            self.logger.warning('AUDIT sidecar decision=fallback trace_id=%s reason=%s fallback=sidecar-fallback', trace_id, str(exc)[:200])
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

    if result.requires_approval:
        lines.append('- 請先確認：若你同意這份草案，我再繼續下一步。')
        lines.append('- 說明：目前尚未執行任何動作。')
    else:
        lines.append('- 說明：目前僅提供建議，不會自動執行。')
    return '\n'.join(lines)
