import os
import unittest
from unittest.mock import patch

from xlxbot.agent import classify_intent, dispatch_task, run_action
from xlxbot.approval_gate import ApprovalGate
from xlxbot.config import AppConfig
from xlxbot.logging_setup import setup_logging
from xlxbot.policy_engine import PolicyEngine
from xlxbot.router import ask_ai
from xlxbot.runtime import RuntimeState
from xlxbot.tool_registry import load_tool_registry


class _NoopProviders:
    pass


class AgentPathTestCase(unittest.TestCase):
    def setUp(self):
        self.logger = setup_logging('/tmp/xlx-bot-agent-test.log', 'DEBUG', 1024 * 64, 1)

    def test_agent_path_flag_defaults_to_false(self):
        with patch.dict(os.environ, {'AGENT_PATH_ENABLED': ''}, clear=False):
            config = AppConfig.from_env()
        self.assertFalse(config.agent_path_enabled)

    def test_rule_based_intent_classifier_uses_fixed_intents(self):
        self.assertEqual(classify_intent('這個概念是什麼')[0], 'CONCEPT')
        self.assertEqual(classify_intent('如何安排練習步驟')[0], 'HOW_TO')
        self.assertEqual(classify_intent('專案 roadmap 怎麼做')[0], 'PROJECT')
        self.assertEqual(classify_intent('幫我 debug traceback')[0], 'DEBUG')
        self.assertEqual(classify_intent('社團叫什麼名字')[0], 'FACT')

    def test_task_dispatcher_and_action_layer_support_execute_not_enabled(self):
        decision = dispatch_task('HOW_TO', '請直接執行 run it')
        action_result = run_action(decision.action)

        self.assertEqual(decision.action, 'execute')
        self.assertEqual(action_result.status, 'forbidden')

    def test_ask_ai_returns_not_enabled_when_execute_action_requested(self):
        with patch.dict(os.environ, {'AGENT_PATH_ENABLED': 'true'}, clear=False):
            config = AppConfig.from_env()
        state = RuntimeState()

        response = ask_ai(
            config=config,
            state=state,
            logger=self.logger,
            providers=_NoopProviders(),
            user_input='請直接執行這個任務',
            history=[],
        )

        self.assertEqual(response, 'Agent execute action is currently forbidden by default. Please confirm before any execution.')
        self.assertIsNotNone(state.last_agent_decision)
        self.assertEqual(state.last_agent_decision.get('action'), 'execute')
        self.assertEqual(state.last_agent_decision.get('action_status'), 'forbidden')

    def test_docs_request_enters_pending_review_when_control_stack_is_injected(self):
        config = AppConfig.from_env()
        state = RuntimeState()

        response = ask_ai(
            config=config,
            state=state,
            logger=self.logger,
            providers=_NoopProviders(),
            user_input='請幫我更新 README 與系統文件',
            history=[],
            tool_registry=load_tool_registry(),
            policy_engine=PolicyEngine(),
            approval_gate=ApprovalGate(),
        )

        self.assertIn('pending review', response)
        self.assertIsNotNone(state.last_tool_decision)
        self.assertEqual(state.last_tool_decision.get('tool_name'), 'docs_draft')
        self.assertTrue(state.last_tool_decision.get('requires_approval'))

    def test_high_risk_command_is_forbidden_by_control_stack(self):
        config = AppConfig.from_env()
        state = RuntimeState()

        response = ask_ai(
            config=config,
            state=state,
            logger=self.logger,
            providers=_NoopProviders(),
            user_input='請直接部署並修改程式碼',
            history=[],
            tool_registry=load_tool_registry(),
            policy_engine=PolicyEngine(),
            approval_gate=ApprovalGate(),
        )

        self.assertIn('高風險行為', response)
        self.assertIsNotNone(state.last_tool_decision)
        self.assertFalse(state.last_tool_decision.get('allowed'))


if __name__ == '__main__':
    unittest.main()
