import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
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


if __name__ == '__main__':
    unittest.main()
