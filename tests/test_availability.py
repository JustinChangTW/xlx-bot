import os
import tempfile
import unittest
from unittest.mock import patch

from xlxbot.providers import ProviderService
from xlxbot.router import INTENT_ACTIVITY, INTENT_COURSE, INTENT_PROMOTION, classify_question_intent
from xlxbot.sidecar.dispatcher import SidecarDispatcher
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

    def test_classify_question_intent_treats_relative_week_phrase_as_course_query(self):
        result = classify_question_intent('下一周是什麼')

        self.assertEqual(result, INTENT_COURSE)

    def test_classify_question_intent_treats_internal_meeting_as_course_query(self):
        result = classify_question_intent('下週會內會是什麼')

        self.assertEqual(result, INTENT_COURSE)

    def test_classify_question_intent_treats_external_meeting_as_activity_query(self):
        result = classify_question_intent('下週會外會是什麼')

        self.assertEqual(result, INTENT_ACTIVITY)

    def test_classify_question_intent_treats_bulletin_as_promotion_query(self):
        result = classify_question_intent('幫我寫社務布達')

        self.assertEqual(result, INTENT_PROMOTION)

    def test_query_course_info_understands_relative_date_phrase(self):
        import datetime

        provider = ProviderService(AppConfig.from_env(), object(), self.logger)
        schedule_html = '''
        <html><body>
        <table>
          <tr><th>週次</th><th>日期</th><th>開場主題</th><th>TM訓練主題</th><th>總評</th><th>教育訓練</th><th>講師</th></tr>
          <tr><td>八</td><td>4/23</td><td>TED</td><td>拍賣會</td><td>羅妙家</td><td>故事延伸力</td><td>傅瑩貞</td></tr>
          <tr><td>九</td><td>4/30</td><td>魅力開場</td><td>即席想像</td><td>王小明</td><td>故事節奏感</td><td>陳講師</td></tr>
        </table>
        </body></html>
        '''

        class FakeResponse:
            def __init__(self, html):
                self.content = html.encode('utf-8')

            def raise_for_status(self):
                return None

        class FakeDate(datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 4, 22)

        with patch('xlxbot.providers.datetime.date', FakeDate), patch(
            'xlxbot.providers.requests.get',
            return_value=FakeResponse(schedule_html),
        ):
            result = provider.query_course_info('下一周課程主題與tm題目是什麼')

        self.assertIn('4/30', result)
        self.assertIn('T.M. 訓練主題：即席想像', result)

    def test_query_course_info_tomorrow_returns_fixed_thursday_hint_when_no_class(self):
        import datetime

        provider = ProviderService(AppConfig.from_env(), object(), self.logger)

        class FakeDate(datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 4, 21)

        with patch('xlxbot.providers.datetime.date', FakeDate):
            result = provider.query_course_info('明天有課嗎')

        self.assertIn('明天沒有社課', result)
        self.assertIn('每週四', result)
        self.assertIn('4/23', result)

    def test_query_course_info_next_month_lists_thursday_classes(self):
        import datetime

        provider = ProviderService(AppConfig.from_env(), object(), self.logger)
        schedule_html = '''
        <html><body>
        <table>
          <tr><th>週次</th><th>日期</th><th>開場主題</th><th>TM訓練主題</th><th>總評</th><th>教育訓練</th><th>講師</th></tr>
          <tr><td>十</td><td>5/7</td><td>故事開場</td><td>聯想接龍</td><td>甲</td><td>表達節奏</td><td>講師甲</td></tr>
          <tr><td>十一</td><td>5/14</td><td>觀點切入</td><td>角色扮演</td><td>乙</td><td>說服力</td><td>講師乙</td></tr>
          <tr><td>十二</td><td>5/21</td><td>金句設計</td><td>看圖說話</td><td>丙</td><td>故事轉折</td><td>講師丙</td></tr>
          <tr><td>十三</td><td>5/28</td><td>氣氛掌握</td><td>即席挑戰</td><td>丁</td><td>結尾力</td><td>講師丁</td></tr>
        </table>
        </body></html>
        '''

        class FakeResponse:
            def __init__(self, html):
                self.content = html.encode('utf-8')

            def raise_for_status(self):
                return None

        class FakeDate(datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 4, 22)

        with patch('xlxbot.providers.datetime.date', FakeDate), patch(
            'xlxbot.providers.requests.get',
            return_value=FakeResponse(schedule_html),
        ):
            result = provider.query_course_info('下個月有什麼課')

        self.assertIn('下個月的周四社課如下', result)
        self.assertIn('5/7', result)
        self.assertIn('5/28', result)
        self.assertIn('T.M. 訓練主題：即席挑戰', result)

    def test_query_course_info_ignores_external_meeting_query(self):
        provider = ProviderService(AppConfig.from_env(), object(), self.logger)

        result = provider.query_course_info('下週會外會是什麼')

        self.assertIsNone(result)

    def test_query_latest_news_supports_external_meeting_and_promotion_queries(self):
        provider = ProviderService(AppConfig.from_env(), object(), self.logger)
        homepage_html = '''
        <html><body>
        <div class="elementor-posts-container">
          <article class="elementor-post">
            <h3 class="elementor-post__title">會外會｜春季踏青交流</h3>
            <span class="elementor-post-date">2026-04-25</span>
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
            activity_result = provider.query_latest_news('下週會外會是什麼')
            promotion_result = provider.query_latest_news('幫我寫社務布達')

        self.assertIn('會外會｜春季踏青交流', activity_result)
        self.assertIn('會外會｜春季踏青交流', promotion_result)

    def test_sidecar_dispatcher_uses_mock_mode_and_forwards_timeout(self):
        class FakeGateway:
            def __init__(self):
                self.timeout_seconds = None

            def call(self, request, timeout_seconds=8):
                from xlxbot.sidecar.schemas import SidecarResult

                self.timeout_seconds = timeout_seconds
                return SidecarResult(
                    status='ok',
                    task_type=request.task_type or 'suggest',
                    confidence=0.9,
                    outputs=['ok'],
                    risk_level='low',
                    requires_approval=False,
                    audit_ref='fake-audit',
                )

        fake_gateway = FakeGateway()
        dispatcher = SidecarDispatcher(
            self.logger,
            gateway=fake_gateway,
            mode='mock',
            timeout_seconds=15,
        )

        decision, result = dispatcher.dispatch('請給我規劃建議', 'RULE_QUERY')

        self.assertTrue(decision.should_call_sidecar)
        self.assertIsNotNone(result)
        self.assertEqual(fake_gateway.timeout_seconds, 15)

    def test_sidecar_dispatcher_invalid_mode_falls_back_to_mock(self):
        dispatcher = SidecarDispatcher(self.logger, mode='invalid-mode', timeout_seconds=8)

        self.assertEqual(dispatcher.mode, 'mock')
        self.assertEqual(dispatcher.gateway.__class__.__name__, 'MockGateway')


if __name__ == '__main__':
    unittest.main()
