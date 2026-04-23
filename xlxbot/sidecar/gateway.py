import hashlib
import time
from dataclasses import dataclass

import requests

from .schemas import SidecarRequest, SidecarResult


class MockGateway:
    """Sidecar mock implementation for safe phase-1 rollout."""

    def call(self, request: SidecarRequest, timeout_seconds: int = 8) -> SidecarResult:
        digest = hashlib.sha1(f'{request.user_input}|{request.task_type}'.encode('utf-8')).hexdigest()[:12]
        task_type = request.task_type or 'suggest'

        outputs = [
            '先確認需求範圍與交付物，再拆成 3 個最小里程碑。',
            '列出風險與驗證方式，先做不破壞主流程的草稿。',
            '完成後請求人工確認，再進入實作或執行。',
        ]

        return SidecarResult(
            status='ok',
            task_type=task_type,
            confidence=0.66,
            outputs=outputs,
            risk_level='medium',
            requires_approval=True,
            audit_ref=f'mock-{digest}',
        )


@dataclass
class _CircuitBreaker:
    failure_count: int = 0
    opened_until_ts: float = 0.0

    def is_open(self) -> bool:
        return time.time() < self.opened_until_ts


class OpenClawGatewayClient:
    """HTTP gateway with timeout, retry and simple circuit-breaker."""

    def __init__(
        self,
        base_url='http://127.0.0.1:9099',
        endpoint='/v1/dispatch',
        timeout_seconds=8,
        max_retries=2,
        circuit_fail_threshold=3,
        circuit_cooldown_seconds=30,
        session=None,
    ):
        self.base_url = (base_url or 'http://127.0.0.1:9099').rstrip('/')
        self.endpoint = endpoint if endpoint.startswith('/') else f'/{endpoint}'
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_retries = max(0, int(max_retries))
        self.circuit_fail_threshold = max(1, int(circuit_fail_threshold))
        self.circuit_cooldown_seconds = max(1, int(circuit_cooldown_seconds))
        self.session = session or requests.Session()
        self._breaker = _CircuitBreaker()

    def _payload(self, request: SidecarRequest) -> dict:
        return {
            'trace_id': request.trace_id,
            'user_input': request.user_input,
            'task_type': request.task_type,
            'intent': request.intent,
            'context': request.context,
        }

    def _validate_response(self, payload: dict) -> SidecarResult:
        required = {'status', 'task_type', 'confidence', 'outputs', 'risk_level', 'requires_approval'}
        if not required.issubset(payload):
            raise ValueError('E_SIDECAR_BAD_RESPONSE:missing-required-fields')

        outputs = payload.get('outputs')
        if not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
            raise ValueError('E_SIDECAR_BAD_RESPONSE:outputs-must-be-list[str]')

        return SidecarResult(
            status=str(payload.get('status', 'failed')),
            task_type=str(payload.get('task_type', 'suggest')),
            confidence=float(payload.get('confidence', 0.0)),
            outputs=outputs,
            risk_level=str(payload.get('risk_level', 'medium')),
            requires_approval=bool(payload.get('requires_approval', True)),
            audit_ref=str(payload.get('audit_ref') or payload.get('decision_ref') or request_fallback_audit_ref(payload)),
            error=str(payload.get('error', '')),
        )

    def call(self, request: SidecarRequest, timeout_seconds: int = 8) -> SidecarResult:
        if self._breaker.is_open():
            raise RuntimeError('E_SIDECAR_UNAVAILABLE:circuit-open')

        retries = max(0, self.max_retries)
        total_attempts = retries + 1
        timeout = max(1, int(timeout_seconds or self.timeout_seconds))

        for attempt in range(total_attempts):
            try:
                started = time.monotonic()
                response = self.session.post(
                    f'{self.base_url}{self.endpoint}',
                    json=self._payload(request),
                    timeout=timeout,
                )
                if response.status_code >= 500:
                    raise RuntimeError(f'E_SIDECAR_UNAVAILABLE:http-{response.status_code}')
                if response.status_code >= 400:
                    raise RuntimeError(f'E_SIDECAR_BAD_RESPONSE:http-{response.status_code}')
                result = self._validate_response(response.json())
                self._breaker.failure_count = 0
                self._breaker.opened_until_ts = 0.0
                _ = time.monotonic() - started
                return result
            except requests.Timeout as exc:
                self._register_failure()
                if attempt >= retries:
                    raise RuntimeError('E_SIDECAR_TIMEOUT:request-timeout') from exc
            except requests.RequestException as exc:
                self._register_failure()
                if attempt >= retries:
                    raise RuntimeError('E_SIDECAR_UNAVAILABLE:request-exception') from exc
            except Exception:
                self._register_failure()
                if attempt >= retries:
                    raise

        raise RuntimeError('E_SIDECAR_EXCEPTION:unexpected-retry-state')

    def _register_failure(self):
        self._breaker.failure_count += 1
        if self._breaker.failure_count >= self.circuit_fail_threshold:
            self._breaker.opened_until_ts = time.time() + self.circuit_cooldown_seconds


class RealGateway(OpenClawGatewayClient):
    """Backward compatible name for real sidecar gateway integration."""


def request_fallback_audit_ref(payload):
    code = str(payload.get('error') or 'no-error')
    digest = hashlib.sha1(code.encode('utf-8')).hexdigest()[:10]
    return f'openclaw-{digest}'
