import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from flask import Flask
from xlxbot.application import BotApplication, sanitize_user_visible_response
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

    def test_sanitize_user_visible_response_removes_internal_citations(self):
        text = '四不原則包含不談商業。 \"\"\" [cite: 90_club_manual.md] \"\"\"\\n請準時上課。[cite: knowledge/50_programs_and_events.md]'

        sanitized = sanitize_user_visible_response(text)

        self.assertIn('四不原則包含不談商業。', sanitized)
        self.assertIn('請準時上課。', sanitized)
        self.assertNotIn('[cite:', sanitized)
        self.assertNotIn('90_club_manual.md', sanitized)

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
        presidents_targets = providers._get_official_site_targets('理事長在健言社的資歷 https://tmc1974.com/presidents/', 'ORG_QUERY')
        social_urls = providers._extract_official_urls_from_input(
            '官方來源 https://www.instagram.com/taipeitoastmasters/ '
            'https://www.youtube.com/@1974toastmaster/videos '
            'https://www.facebook.com/tmc1974 '
            'https://www.flickr.com/photos/133676498@N06/albums/ '
            'https://example.com/not-official'
        )

        self.assertIn('https://www.flickr.com/photos/133676498@N06/albums/', photo_targets)
        self.assertIn('https://www.youtube.com/@1974toastmaster/videos', video_targets)
        self.assertIn('https://www.instagram.com/taipeitoastmasters/', announcement_targets)
        self.assertIn('https://www.facebook.com/tmc1974', announcement_targets)
        self.assertEqual(presidents_targets[0], 'https://tmc1974.com/presidents/')
        self.assertIn('https://www.instagram.com/taipeitoastmasters/', social_urls)
        self.assertIn('https://www.youtube.com/@1974toastmaster/videos', social_urls)
        self.assertIn('https://www.facebook.com/tmc1974', social_urls)
        self.assertIn('https://www.flickr.com/photos/133676498@N06/albums/', social_urls)
        self.assertNotIn('https://example.com/not-official', social_urls)

    def test_presidents_page_summary_extracts_requested_chairperson_row(self):
        providers = ProviderService(SimpleNamespace(gemini_api_key=''), SimpleNamespace(), self.logger)
        soup = BeautifulSoup(
            '''
            <html><head><title>歷任理事長及社長 - 台北市健言社</title></head><body><main>
              <h1>歷任理事長及社長</h1>
              <table>
                <tr><th>屆別</th><th>理事長</th></tr>
                <tr><td>第十六屆</td><td>梁慈珊</td></tr>
                <tr><td>第十五屆</td><td>丘建賢</td></tr>
              </table>
              <table>
                <tr><th>期別</th><th>社長</th><th>社務發展簡介</th></tr>
                <tr><td>第十六期</td><td>王世南</td><td>社刊發起人</td></tr>
                <tr><td>第一五八期</td><td>吳耿豪</td><td></td></tr>
              </table>
            </main></body></html>
            ''',
            'lxml',
        )

        summary = providers._extract_presidents_page_summary(
            soup,
            'https://tmc1974.com/presidents/',
            user_input='第十六屆理事長是誰？',
        )

        self.assertIn('歷任理事長表', summary)
        self.assertIn('符合問題的官網表格列', summary)
        self.assertIn('屆別：第十六屆；理事長：梁慈珊', summary)
        self.assertNotIn('理事長：丘建賢', summary)
        self.assertNotIn('社長：王世南', summary)

    def test_presidents_page_summary_extracts_requested_president_term_row(self):
        providers = ProviderService(SimpleNamespace(gemini_api_key=''), SimpleNamespace(), self.logger)
        soup = BeautifulSoup(
            '''
            <html><head><title>歷任理事長及社長 - 台北市健言社</title></head><body><main>
              <h1>歷任社長</h1>
              <table>
                <tr><th>期別</th><th>社長</th><th>社務發展簡介</th></tr>
                <tr><td>第一五八期</td><td>吳耿豪</td><td></td></tr>
                <tr><td>第一五七期</td><td>高力翔</td><td>產業升級社長</td></tr>
              </table>
            </main></body></html>
            ''',
            'lxml',
        )

        summary = providers._extract_presidents_page_summary(
            soup,
            'https://tmc1974.com/presidents/',
            user_input='第158期社長是誰？',
        )

        self.assertIn('歷任社長表', summary)
        self.assertIn('期別：第一五八期；社長：吳耿豪', summary)
        self.assertNotIn('社長：高力翔', summary)

    @patch('xlxbot.providers.requests.get')
    def test_generic_official_page_summary_extracts_richer_page_signals(self, mock_get):
        providers = ProviderService(SimpleNamespace(gemini_api_key=''), SimpleNamespace(), self.logger)

        class FakeResponse:
            content = '''
            <html>
              <head>
                <title>最新公告 - 台北市健言社</title>
                <meta name="description" content="官方公告與活動資訊">
              </head>
              <body><main>
                <h1>最新公告</h1>
                <article class="elementor-post">
                  <h3 class="elementor-post__title"><a href="/events/speech-night/">第159期演講之夜</a></h3>
                  <span class="elementor-post-date">2026-04-25</span>
                  <div class="elementor-post__excerpt">歡迎關注本期活動安排。</div>
                </article>
                <table>
                  <tr><th>日期</th><th>活動</th></tr>
                  <tr><td>4/25</td><td>演講之夜</td></tr>
                </table>
                <figure>
                  <img src="/wp-content/uploads/poster.jpg" alt="第159期演講之夜海報">
                  <figcaption>官方海報</figcaption>
                </figure>
                <a href="/category/events/">更多活動</a>
                <a href="https://example.com/not-official">外部連結</a>
              </main></body>
            </html>
            '''.encode('utf-8')

            def raise_for_status(self):
                return None

        mock_get.return_value = FakeResponse()

        summary = providers._extract_page_summary('https://tmc1974.com/category/events/')

        self.assertIn('頁面描述：官方公告與活動資訊', summary)
        self.assertIn('第159期演講之夜；日期：2026-04-25；摘要：歡迎關注本期活動安排。；連結：https://tmc1974.com/events/speech-night/', summary)
        self.assertIn('日期：4/25；活動：演講之夜', summary)
        self.assertIn('第159期演講之夜海報: https://tmc1974.com/wp-content/uploads/poster.jpg', summary)
        self.assertIn('更多活動: https://tmc1974.com/category/events/', summary)
        self.assertNotIn('example.com', summary)

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
