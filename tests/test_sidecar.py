import unittest
from unittest.mock import Mock, patch

from xlxbot.router import ask_ai
from xlxbot.runtime import RuntimeState
from xlxbot.sidecar.dispatcher import SidecarDispatcher, format_sidecar_guidance
from xlxbot.sidecar.gateway import MockGateway
from xlxbot.sidecar.schemas import SidecarRequest
from xlxbot.sidecar.schemas import SidecarResult


class _DummyProviders:
    def is_provider_available(self, name):
        return name == 'ollama'

    def ask_ollama(self, prompt):
        return '主流程回覆'

    def ask_ollama_with_model(self, prompt, model_name):
        return None

    def ask_groq(self, prompt):
        return None

    def ask_xai(self, prompt):
        return None

    def ask_github_models(self, prompt):
        return None

    def ask_gemini(self, prompt):
        return None

    def query_course_info(self, user_input):
        return ''

    def query_latest_news(self, user_input):
        return ''

    def query_official_site_map(self, user_input, intent):
        return ''


class SidecarDispatcherTestCase(unittest.TestCase):
    def setUp(self):
        self.logger = Mock()
        self.dispatcher = SidecarDispatcher(self.logger)

    def test_decide_returns_non_task_intent_for_fact_intent(self):
        decision = self.dispatcher.decide('請幫我規劃最近活動', 'FACT_QUERY')

        self.assertFalse(decision.should_call_sidecar)
        self.assertEqual(decision.reason, 'non-task-intent')
        self.assertEqual(decision.task_type, '')

    def test_decide_returns_task_query_for_non_fact_task_request(self):
        decision = self.dispatcher.decide('請給我一份重構方案', 'PROMOTION_QUERY')

        self.assertTrue(decision.should_call_sidecar)
        self.assertEqual(decision.reason, 'task-query')
        self.assertEqual(decision.task_type, 'suggest')

    def test_dispatch_fallback_when_gateway_raises_exception(self):
        failing_gateway = Mock()
        failing_gateway.call.side_effect = RuntimeError('mock failure')
        dispatcher = SidecarDispatcher(self.logger, gateway=failing_gateway)

        decision, result = dispatcher.dispatch('幫我 debug 這個錯誤', 'PROMOTION_QUERY')

        self.assertFalse(decision.should_call_sidecar)
        self.assertEqual(decision.reason, 'sidecar-fallback')
        self.assertEqual(decision.task_type, 'debug')
        self.assertIsNone(result)
        self.logger.warning.assert_called_once()

    def test_format_sidecar_guidance_structure(self):
        result = SidecarResult(
            status='ok',
            task_type='debug',
            confidence=0.8,
            outputs=['先重現問題', '再確認回歸測試'],
            risk_level='high',
            requires_approval=True,
            audit_ref='mock-123',
        )

        guidance = format_sidecar_guidance(result)

        self.assertTrue(guidance.startswith('\n【Sidecar 任務建議（草稿）】'))
        self.assertIn('- 任務類型：debug', guidance)
        self.assertIn('- 風險等級：high', guidance)
        self.assertIn('- 需要人工核准：是', guidance)
        self.assertIn('- 建議 1：先重現問題', guidance)
        self.assertIn('- 建議 2：再確認回歸測試', guidance)
        self.assertIn('- 說明：目前僅提供建議，不會自動執行。', guidance)

    def test_mock_gateway_status_is_ok_or_degraded(self):
        gateway = MockGateway()
        request = SidecarRequest(
            user_input='請幫我規劃任務',
            task_type='plan',
            intent='PROMOTION_QUERY',
            trace_id='t1',
        )

        result = gateway.call(request)

        self.assertIn(result.status, {'ok', 'degraded'})


class RouterSidecarToggleTestCase(unittest.TestCase):
    def test_router_unaffected_when_sidecar_disabled(self):
        config = Mock(
            sidecar_enabled=False,
            router_enabled=False,
            router_model_name='test-router-model',
        )
        state = RuntimeState()
        logger = Mock()
        providers = _DummyProviders()
        knowledge_sections = [
            Mock(path='knowledge/10_club_basic.md', content='# 基本資料\n- 名稱：台北市健言社')
        ]

        with patch('xlxbot.router.load_knowledge_sections', return_value=knowledge_sections), patch(
            'xlxbot.router.SidecarDispatcher.dispatch',
            side_effect=AssertionError('dispatch should not be called when SIDECAR_ENABLED=false'),
        ):
            result = ask_ai(config, state, logger, providers, '社團名稱是什麼？')

        self.assertEqual(result, '主流程回覆')

    def test_router_does_not_call_dispatcher_for_general_qa(self):
        config = Mock(
            sidecar_enabled=True,
            sidecar_mode='mock',
            sidecar_timeout_seconds=8,
            router_enabled=False,
            router_model_name='test-router-model',
            teaching_planner_enabled=False,
        )
        state = RuntimeState()
        logger = Mock()
        providers = _DummyProviders()
        knowledge_sections = [
            Mock(path='knowledge/10_club_basic.md', content='# 基本資料\n- 名稱：台北市健言社')
        ]

        with patch('xlxbot.router.load_knowledge_sections', return_value=knowledge_sections), patch(
            'xlxbot.router.SidecarDispatcher.dispatch',
            side_effect=AssertionError('dispatch should not be called for general QA'),
        ):
            result = ask_ai(config, state, logger, providers, '社團名稱是什麼？')

        self.assertEqual(result, '主流程回覆')


if __name__ == '__main__':
    unittest.main()
