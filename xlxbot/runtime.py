from dataclasses import dataclass, field
import json
import os
import time
from typing import Optional, Dict, List, Any


@dataclass
class RuntimeState:
    # 這裡集中保存執行期間的暫存狀態，不寫回設定檔。
    conversation_history: Dict[str, List] = field(default_factory=dict)
    working_gemini_model: Optional[str] = None
    last_synced_webhook_url: Optional[str] = None
    last_detected_ngrok_url: Optional[str] = None
    max_history_length: int = 10
    route_general: str = 'GENERAL'
    route_expert: str = 'EXPERT'
    route_local: str = 'LOCAL'
    last_agent_decision: Optional[Dict] = None
    last_sidecar_decision: Optional[Dict] = None
    last_tool_decision: Optional[Dict] = None
    startup_checks_completed: bool = False
    startup_checks_passed: bool = False
    last_startup_error: Optional[str] = None
    last_message_received_at: Optional[str] = None
    last_message_replied_at: Optional[str] = None
    last_message_failed_at: Optional[str] = None
    last_message_error: Optional[str] = None
    last_message_user_id: Optional[str] = None
    last_message_preview: Optional[str] = None

    # 新增：狀態記錄和恢復
    last_request_tracker: Optional[Any] = None  # Request state tracker
    provider_health_status: Dict[str, Dict] = field(default_factory=dict)  # Provider health tracking
    recent_errors: List[Dict] = field(default_factory=list)  # Recent error history
    recovery_state: Dict[str, Dict] = field(default_factory=dict)  # Recovery state for failed operations

    def update_provider_health(self, provider_name: str, status: str, error: str = None, response_time: float = None):
        """Update provider health status"""
        self.provider_health_status[provider_name] = {
            'status': status,
            'last_check': time.time(),
            'error': error,
            'response_time': response_time
        }

    def add_recent_error(self, error_type: str, message: str, details: dict = None):
        """Add recent error to history"""
        self.recent_errors.append({
            'type': error_type,
            'message': message,
            'timestamp': time.time(),
            'details': details or {}
        })
        # Keep only last 100 errors
        if len(self.recent_errors) > 100:
            self.recent_errors = self.recent_errors[-100:]

    def set_recovery_state(self, operation: str, state: dict):
        """Set recovery state for an operation"""
        self.recovery_state[operation] = {
            'state': state,
            'timestamp': time.time()
        }

    def get_recovery_state(self, operation: str):
        """Get recovery state for an operation"""
        return self.recovery_state.get(operation, {})

    def get_health_summary(self):
        """Get overall health summary"""
        return {
            'startup_checks_passed': self.startup_checks_passed,
            'last_startup_error': self.last_startup_error,
            'provider_health': self.provider_health_status,
            'recent_errors_count': len(self.recent_errors),
            'last_message_status': {
                'received_at': self.last_message_received_at,
                'replied_at': self.last_message_replied_at,
                'failed_at': self.last_message_failed_at,
                'error': self.last_message_error
            }
        }
