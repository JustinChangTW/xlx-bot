import hashlib

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
        if task_type == 'debug':
            outputs = [
                '先重現問題並收集錯誤日誌。',
                '隔離影響範圍，優先檢查最近變更。',
                '提出修復草案與回歸測試清單。',
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


class RealGateway:
    """Reserved for real sidecar gateway integration."""

    def call(self, request: SidecarRequest, timeout_seconds: int = 8) -> SidecarResult:
        raise NotImplementedError(
            f'real sidecar gateway is not implemented yet (timeout_seconds={timeout_seconds})'
        )
