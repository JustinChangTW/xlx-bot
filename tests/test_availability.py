import os
import tempfile
import unittest
from unittest.mock import patch

from xlxbot.providers import ProviderService
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

    def test_query_course_info_uses_schedule_page_for_specific_date(self):
        provider = ProviderService(AppConfig.from_env(), object(), self.logger)
        schedule_html = '''
        <html><body>
        <table>
          <tr><th>週次</th><th>日期</th><th>開場主題</th><th>TM訓練主題</th><th>總評</th><th>教育訓練</th><th>講師</th></tr>
          <tr><td>八</td><td>4/23</td><td>TED</td><td>拍賣會</td><td>羅妙家</td><td>故事延伸力</td><td>傅瑩貞</td></tr>
        </table>
        </body></html>
        '''

        class FakeResponse:
            def __init__(self, html):
                self.content = html.encode('utf-8')

            def raise_for_status(self):
                return None

        with patch('xlxbot.providers.requests.get', return_value=FakeResponse(schedule_html)) as get_mock:
            result = provider.query_course_info('請問 4/23 的課程主題和 T.M. 題目是什麼？')

        self.assertIn('4/23', result)
        self.assertIn('T.M. 訓練主題：拍賣會', result)
        self.assertIn('教育訓練：故事延伸力', result)
        get_mock.assert_called_once_with(
            'https://tmc1974.com/schedule/',
            timeout=10,
            headers=provider._build_browser_headers(),
        )

    def test_query_course_info_falls_back_to_homepage_summary(self):
        provider = ProviderService(AppConfig.from_env(), object(), self.logger)
        homepage_html = '''
        <html><body>
        <div class="elementor-posts-container">
          <article class="elementor-post">
            <h3 class="elementor-post__title">第159期第八週－故事延伸力</h3>
            <span class="elementor-post-date">2026-04-17</span>
          </article>
        </div>
        </body></html>
        '''

        class FakeResponse:
            def __init__(self, html):
                self.content = html.encode('utf-8')

            def raise_for_status(self):
                return None

        with patch('xlxbot.providers.requests.get', return_value=FakeResponse(homepage_html)):
            result = provider.query_course_info('最近有什麼課程？')

        self.assertIn('根據台北市健言社官網最新公告', result)
        self.assertIn('2026-04-17', result)
        self.assertIn('第159期第八週－故事延伸力', result)


if __name__ == '__main__':
    unittest.main()
