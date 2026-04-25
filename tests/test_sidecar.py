import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xlxbot.logging_setup import setup_logging
from xlxbot.sidecar.dispatcher import SidecarDispatcher, build_sidecar_gateway, format_sidecar_guidance
from xlxbot.sidecar.gateway import MockGateway, OpenClawGateway
from xlxbot.sidecar.schemas import SidecarResult


class DummyGateway:
    def __init__(self, result=None, raise_error=False):
        self.result = result
        self.raise_error = raise_error

    def call(self, request):
        if self.raise_error:
            raise RuntimeError('boom')
        return self.result


class SidecarTestCase(unittest.TestCase):
    def setUp(self):
        self.logger = setup_logging('/tmp/xlx-bot-sidecar-test.log', 'DEBUG', 1024 * 64, 1)

    def test_build_sidecar_gateway_openclaw_mode(self):
        config = SimpleNamespace(
            sidecar_mode='openclaw',
            sidecar_timeout_seconds=5,
            openclaw_base_url='https://openclaw.example',
            openclaw_endpoint_path='/dispatch',
            openclaw_api_key='k',
        )
        gateway = build_sidecar_gateway(config, self.logger)
        self.assertIsInstance(gateway, OpenClawGateway)

    def test_build_sidecar_gateway_unknown_mode_fallbacks_to_mock(self):
        config = SimpleNamespace(sidecar_mode='unknown', sidecar_timeout_seconds=5)
        gateway = build_sidecar_gateway(config, self.logger)
        self.assertIsInstance(gateway, MockGateway)

    def test_dispatch_fact_query_does_not_call_sidecar(self):
        dispatcher = SidecarDispatcher(self.logger, config=SimpleNamespace(sidecar_mode='mock'))
        decision, result = dispatcher.dispatch('請給我一個計畫', 'FACT_QUERY')
        self.assertFalse(decision.should_call_sidecar)
        self.assertEqual(decision.reason, 'fact-first')
        self.assertIsNone(result)

    def test_dispatch_task_query_calls_gateway(self):
        expected = SidecarResult(
            status='ok',
            task_type='plan',
            confidence=0.8,
            outputs=['a', 'b'],
            risk_level='medium',
            requires_approval=True,
            audit_ref='r1',
        )
        dispatcher = SidecarDispatcher(self.logger, gateway=DummyGateway(result=expected))
        decision, result = dispatcher.dispatch('請幫我規劃重構里程碑', 'RULE_QUERY')
        self.assertTrue(decision.should_call_sidecar)
        self.assertEqual(result.audit_ref, 'r1')

    def test_dispatch_promotion_query_calls_gateway(self):
        expected = SidecarResult(
            status='ok',
            task_type='suggest',
            confidence=0.8,
            outputs=['先理解需求，再分析課程資訊，最後產生 LINE 文宣。'],
            risk_level='medium',
            requires_approval=True,
            audit_ref='r2',
        )
        dispatcher = SidecarDispatcher(self.logger, gateway=DummyGateway(result=expected))

        decision, result = dispatcher.dispatch('請為本周課程寫文宣', 'PROMOTION_QUERY')

        self.assertTrue(decision.should_call_sidecar)
        self.assertEqual(decision.task_type, 'suggest')
        self.assertEqual(result.audit_ref, 'r2')

    def test_dispatch_fallback_on_exception(self):
        dispatcher = SidecarDispatcher(self.logger, gateway=DummyGateway(raise_error=True))
        decision, result = dispatcher.dispatch('請幫我規劃重構里程碑', 'RULE_QUERY')
        self.assertFalse(decision.should_call_sidecar)
        self.assertEqual(decision.reason, 'sidecar-fallback')
        self.assertIsNone(result)

    def test_openclaw_gateway_calls_http_api(self):
        gateway = OpenClawGateway(
            base_url='https://openclaw.example',
            endpoint_path='/v1/sidecar/dispatch',
            api_key='token',
            timeout_seconds=7,
        )

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'status': 'ok',
                    'task_type': 'project',
                    'confidence': 0.91,
                    'outputs': ['step1'],
                    'risk_level': 'medium',
                    'requires_approval': True,
                    'audit_ref': 'audit-1',
                }

        with patch('xlxbot.sidecar.gateway.requests.post', return_value=FakeResponse()) as post_mock:
            result = gateway.call(
                request=SimpleNamespace(
                    user_input='請規劃',
                    task_type='project',
                    intent='RULE_QUERY',
                    trace_id='trace-1',
                    context={'k': 'v'},
                )
            )

        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.audit_ref, 'audit-1')
        post_mock.assert_called_once()

    def test_openclaw_gateway_requires_base_url(self):
        gateway = OpenClawGateway(base_url='', endpoint_path='/dispatch')
        with self.assertRaises(ValueError):
            gateway.call(request=SimpleNamespace(user_input='x', task_type='plan', intent='RULE_QUERY', trace_id='t', context={}))

    def test_format_sidecar_guidance(self):
        guidance = format_sidecar_guidance(
            SidecarResult(
                status='ok',
                task_type='plan',
                confidence=0.6,
                outputs=['先做 A'],
                risk_level='low',
                requires_approval=True,
                audit_ref='a',
            )
        )
        self.assertIn('Sidecar 任務建議', guidance)
        self.assertIn('先做 A', guidance)


if __name__ == '__main__':
    unittest.main()
