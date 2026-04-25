import hashlib

import requests

from .schemas import SidecarRequest, SidecarResult


class MockGateway:
    """Sidecar mock implementation for safe phase-1 rollout."""

    def call(self, request: SidecarRequest) -> SidecarResult:
        digest = hashlib.sha1(f'{request.user_input}|{request.task_type}'.encode('utf-8')).hexdigest()[:12]
        task_type = request.task_type or 'suggest'

        outputs = [
            '先確認需求範圍與交付物，再拆成 3 個最小里程碑。',
            '列出風險與驗證方式，先做不破壞主流程的草稿。',
            '完成後請求人工確認，再進入實作或執行。',
        ]
        if task_type == 'debug':
            outputs = [
                '先重現問題並收集錯誤日誌。',
                '隔離影響範圍，優先檢查最近變更。',
                '提出修復草案與回歸測試清單。',
            ]
        elif task_type in {'lookup', 'analyze'}:
            outputs = [
                '先比對本地知識缺口，確認問題是在問現況、名單、課程、公告或規則。',
                '再查核已核可官方來源，優先使用官網首頁、課表、當期幹部、理事會、公告、課程分類頁、Instagram、YouTube 與 Flickr 相簿。',
                '回答時保留來源；若查不到可信資料，明確說明本地與官方查核都不足。',
            ]

        return SidecarResult(
            status='ok',
            task_type=task_type,
            confidence=0.66,
            outputs=outputs,
            risk_level='low' if task_type in {'lookup', 'analyze'} else 'medium',
            requires_approval=False if task_type in {'lookup', 'analyze'} else True,
            audit_ref=f'mock-{digest}',
        )


class OpenClawGateway:
    """Real sidecar gateway for phase-2 OpenClaw integration."""

    def __init__(self, base_url: str, endpoint_path: str, api_key: str = '', timeout_seconds: int = 8):
        self.base_url = (base_url or '').rstrip('/')
        self.endpoint_path = endpoint_path or '/v1/sidecar/dispatch'
        self.api_key = (api_key or '').strip()
        self.timeout_seconds = max(1, int(timeout_seconds or 8))

    def _build_url(self) -> str:
        path = self.endpoint_path if self.endpoint_path.startswith('/') else f'/{self.endpoint_path}'
        return f'{self.base_url}{path}'

    def call(self, request: SidecarRequest) -> SidecarResult:
        if not self.base_url:
            raise ValueError('OPENCLAW_BASE_URL is required when SIDECAR_MODE=openclaw')

        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        payload = {
            'user_input': request.user_input,
            'task_type': request.task_type,
            'intent': request.intent,
            'trace_id': request.trace_id,
            'context': request.context,
        }

        response = requests.post(
            self._build_url(),
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        return SidecarResult(
            status=str(data.get('status', 'ok')),
            task_type=str(data.get('task_type', request.task_type or 'suggest')),
            confidence=float(data.get('confidence', 0.0) or 0.0),
            outputs=[str(item) for item in (data.get('outputs') or []) if str(item).strip()],
            risk_level=str(data.get('risk_level', 'medium')),
            requires_approval=bool(data.get('requires_approval', True)),
            audit_ref=str(data.get('audit_ref', request.trace_id)),
            error=str(data.get('error', '')),
        )
