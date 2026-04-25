import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from xlxbot.application import BotApplication
from xlxbot.config import AppConfig
from xlxbot.logging_setup import setup_logging


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


if __name__ == '__main__':
    unittest.main()
