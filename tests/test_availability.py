import os
import tempfile
import unittest
from unittest.mock import patch

from linebot.v3.exceptions import InvalidSignatureError

from xlxbot.application import BotApplication
from xlxbot.config import AppConfig, load_dotenv
from xlxbot.logging_setup import setup_logging


class AvailabilityTestCase(unittest.TestCase):
    def setUp(self):
        self.logger = setup_logging('/tmp/xlx-bot-test.log', 'DEBUG', 1024 * 64, 1)
        self._env_patcher = patch.dict(
            os.environ,
            {
                'ENV_FILE': '/tmp/xlx-bot-test.env',
                'LINE_ACCESS_TOKEN': '',
                'LINE_CHANNEL_SECRET': '',
                'LINE_WEBHOOK_AUTO_UPDATE': 'false',
            },
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self):
        self._env_patcher.stop()

    def build_app(self, extra_env=None):
        extra_env = extra_env or {}
        with patch.dict(os.environ, extra_env, clear=False):
            return BotApplication(self.logger)

    def test_app_config_defaults_limit_log_growth(self):
        config = AppConfig.from_env()
        self.assertEqual(config.log_max_bytes, 256 * 1024)
        self.assertEqual(config.log_backup_count, 2)
        self.assertFalse(config.line_integration_enabled)

    def test_load_dotenv_loads_missing_vars_without_overwriting_existing(self):
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as tmp:
            tmp.write('NEW_VALUE=from-file\n')
            tmp.write('LINE_ACCESS_TOKEN=from-dotenv\n')
            dotenv_path = tmp.name

        try:
            with patch.dict(os.environ, {'LINE_ACCESS_TOKEN': 'from-env'}, clear=False):
                loaded = load_dotenv(dotenv_path, self.logger)
                self.assertEqual(loaded['NEW_VALUE'], 'from-file')
                self.assertNotIn('LINE_ACCESS_TOKEN', loaded)
                self.assertEqual(os.environ['LINE_ACCESS_TOKEN'], 'from-env')
                self.assertEqual(os.environ['NEW_VALUE'], 'from-file')
        finally:
            os.unlink(dotenv_path)
            os.environ.pop('NEW_VALUE', None)

    def test_health_endpoint_stays_available_without_line_credentials(self):
        app = self.build_app()
        client = app.app.test_client()

        response = client.get('/health')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'status': 'ok'})

    def test_callback_returns_503_when_line_integration_disabled(self):
        app = self.build_app()
        client = app.app.test_client()

        response = client.post('/callback', data='{}')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {'error': 'line integration disabled'})

    def test_callback_returns_400_for_invalid_signature_when_line_enabled(self):
        app = self.build_app(
            {
                'LINE_ACCESS_TOKEN': 'token',
                'LINE_CHANNEL_SECRET': 'secret',
            }
        )
        client = app.app.test_client()

        with patch.object(app.handler, 'handle', side_effect=InvalidSignatureError('bad sig')):
            response = client.post('/callback', data='{}', headers={'X-Line-Signature': 'bad'})

        self.assertEqual(response.status_code, 400)

    def test_sync_webhook_requires_token(self):
        app = self.build_app({'WEBHOOK_SYNC_TOKEN': 'secret-token'})
        client = app.app.test_client()

        response = client.post('/sync-webhook')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json, {'error': 'forbidden'})

    def test_sync_webhook_returns_sync_result_with_valid_token(self):
        app = self.build_app({'WEBHOOK_SYNC_TOKEN': 'secret-token'})
        client = app.app.test_client()

        with patch('xlxbot.application.sync_line_webhook', return_value=True) as sync_mock, patch(
            'xlxbot.application.get_desired_webhook_url',
            return_value='https://example.test/callback',
        ):
            response = client.post(
                '/sync-webhook',
                headers={'X-Webhook-Sync-Token': 'secret-token'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {'updated': True, 'webhook_url': 'https://example.test/callback'},
        )
        sync_mock.assert_called_once()

    def test_startup_checks_allow_ollama_failure_when_knowledge_is_ready(self):
        app = self.build_app()

        with patch('xlxbot.application.check_ollama_service', return_value=False), patch(
            'xlxbot.application.check_knowledge_file',
            return_value=True,
        ):
            app.run_startup_checks()

    def test_startup_checks_exit_when_knowledge_is_missing(self):
        app = self.build_app()

        with patch('xlxbot.application.check_ollama_service', return_value=True), patch(
            'xlxbot.application.check_ollama_model',
            return_value=True,
        ), patch('xlxbot.application.check_knowledge_file', return_value=False):
            with self.assertRaises(SystemExit):
                app.run_startup_checks()


if __name__ == '__main__':
    unittest.main()
