from dataclasses import dataclass, field


@dataclass
class RuntimeState:
    # 這裡集中保存執行期間的暫存狀態，不寫回設定檔。
    conversation_history: dict = field(default_factory=dict)
    working_gemini_model: str | None = None
    last_synced_webhook_url: str | None = None
    last_detected_ngrok_url: str | None = None
    max_history_length: int = 10
    route_general: str = 'GENERAL'
    route_expert: str = 'EXPERT'
    route_local: str = 'LOCAL'
