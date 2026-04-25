import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from flask import Flask
from xlxbot.application import BotApplication
from xlxbot.config import AppConfig
from xlxbot.logging_setup import setup_logging
from xlxbot.providers import ProviderService
from xlxbot.router import openclaw_outputs_have_grounding
from xlxbot.sidecar import SidecarDispatcher
from xlxbot.sidecar.gateway import MockGateway
from xlxbot.sidecar.schemas import SidecarResult


class ApplicationTestCase(unittest.TestCase):
    def setUp(self):
        self.logger = setup_logging('/tmp/xlx-bot-app-test.log', 'DEBUG', 1024 * 64, 1)

    @patch('xlxbot.application.load_dotenv')
    @patch('xlxbot.application.validate_environment')
    @patch('xlxbot.application.ProviderService')
    @patch('xlxbot.application.load_tool_registry')
    @patch('xlxbot.application.PolicyEngine')
    @patch('xlxbot.application.ApprovalGate')
    @patch('xlxbot.application.RuntimeState')
    @patch('xlxbot.application.Flask')
    def test_bot_application_initialization(self, mock_flask, mock_runtime, mock_approval, mock_policy, mock_tool_reg, mock_provider, mock_validate, mock_load_dotenv):
        # Mock the config
        mock_config = MagicMock()
        mock_config.env_file = '/tmp/.env'
        with patch('xlxbot.config.AppConfig.from_env', return_value=mock_config):
            app = BotApplication(self.logger)
            self.assertIsNotNone(app.app)
            self.assertEqual(app.logger, self.logger)
            self.assertEqual(app.config, mock_config)
            mock_load_dotenv.assert_called_once_with(mock_config.env_file, self.logger)
            mock_validate.assert_called_once_with(mock_config, self.logger)
            mock_provider.assert_called_once()
            mock_tool_reg.assert_called_once()
            mock_policy.assert_called_once()
            mock_approval.assert_called_once()

    @patch('xlxbot.application.BotApplication.__init__', return_value=None)
    def test_run_method(self, mock_init):
        with patch('xlxbot.application.Flask') as mock_flask:
            mock_app_instance = MagicMock()
            mock_flask.return_value = mock_app_instance
            app = BotApplication(self.logger)
            app.app = mock_app_instance
            app.logger = self.logger  # Set logger since __init__ is mocked
            app.state = MagicMock()  # Set state since __init__ is mocked
            app.run_startup_checks = MagicMock()
            app.config = SimpleNamespace(
                flask_host='0.0.0.0',
                flask_port=8080,
                line_integration_enabled=False,
                line_webhook_auto_update=False,
            )
            app.run()
            mock_app_instance.run.assert_called_once_with(host='0.0.0.0', port=8080)

    def test_sidecar_lookup_for_fact_query_when_local_knowledge_is_insufficient(self):
        config = SimpleNamespace(sidecar_enabled=True, sidecar_mode='mock', sidecar_timeout_seconds=8, openclaw_phase='suggest')
        dispatcher = SidecarDispatcher(self.logger, config=config, gateway=MockGateway())

        decision, result = dispatcher.dispatch(
            '現在社長是誰？',
            'MEMBER_QUERY',
            context={'needs_official_lookup': True},
        )

        self.assertTrue(decision.should_call_sidecar)
        self.assertEqual(decision.task_type, 'lookup')
        self.assertEqual(decision.reason, 'official-lookup')
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, 'low')
        self.assertFalse(result.requires_approval)

    def test_openclaw_grounding_requires_more_than_generic_process_advice(self):
        generic = SidecarResult(
            status='ok',
            task_type='lookup',
            confidence=0.66,
            outputs=['先比對本地知識缺口。', '再查核已核可官方來源。'],
            risk_level='low',
            requires_approval=False,
            audit_ref='mock',
        )
        grounded = SidecarResult(
            status='ok',
            task_type='lookup',
            confidence=0.9,
            outputs=['根據 https://tmc1974.com/leaders/，第159期社長是楊朝富。'],
            risk_level='low',
            requires_approval=False,
            audit_ref='openclaw',
        )

        self.assertFalse(openclaw_outputs_have_grounding(generic))
        self.assertTrue(openclaw_outputs_have_grounding(grounded))

    def test_official_source_targets_include_social_promotion_channels(self):
        providers = ProviderService(SimpleNamespace(gemini_api_key=''), SimpleNamespace(), self.logger)

        photo_targets = providers._get_official_site_targets('請找活動照片與相簿', 'ACTIVITY_QUERY')
        video_targets = providers._get_official_site_targets('請找官方影片影音', 'ACTIVITY_QUERY')
        announcement_targets = providers._get_official_site_targets('最新公告文宣', 'ANNOUNCEMENT_QUERY')

        self.assertIn('https://www.flickr.com/photos/133676498@N06/albums/', photo_targets)
        self.assertIn('https://www.youtube.com/user/1974toastmaster', video_targets)
        self.assertIn('https://www.instagram.com/taipeitoastmasters/', announcement_targets)

    def test_local_openclaw_gateway_health_exposes_runtime_parameters(self):
        app = BotApplication.__new__(BotApplication)
        app.app = Flask(__name__)
        app.config = SimpleNamespace(
            openclaw_phase='suggest',
            openclaw_endpoint_path='/v1/sidecar/dispatch',
            openclaw_health_path='/v1/openclaw/health',
            sidecar_timeout_seconds=8,
            openclaw_max_outputs=3,
            openclaw_confidence_ok=0.9,
            openclaw_confidence_degraded=0.1,
            openclaw_audit_enabled=True,
            openclaw_learning_enabled=True,
            openclaw_official_sources=['https://tmc1974.com/'],
        )
        app.sidecar_dispatcher = SimpleNamespace(mode='openclaw', is_ready=lambda: (True, []))
        app._register_routes()

        response = app.app.test_client().get('/v1/openclaw/health')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['gateway'], 'local-openclaw')
        self.assertEqual(response.json['mode'], 'openclaw')
        self.assertEqual(response.json['max_outputs'], 3)
        self.assertIn('https://tmc1974.com/', response.json['official_sources'])

    def test_local_openclaw_lookup_respects_max_outputs_parameter(self):
        app = BotApplication.__new__(BotApplication)
        app.config = SimpleNamespace(openclaw_max_outputs=1)
        app.logger = self.logger
        app.providers = SimpleNamespace(
            query_course_info=lambda user_input: 'course',
            query_latest_news=lambda user_input: 'news',
            query_official_site_map=lambda user_input, intent: 'site',
        )

        outputs = app._build_local_openclaw_outputs('最新課程', 'lookup', 'COURSE_QUERY')

        self.assertEqual(len(outputs), 1)
        self.assertIn('官方課表/課程查核', outputs[0])


if __name__ == '__main__':
    unittest.main()
