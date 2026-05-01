import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from xlxbot.router import (
    INTENT_FACT,
    INTENT_COURSE,
    INTENT_HOW_TO,
    INTENT_RULE,
    build_knowledge_context,
    build_openclaw_reference_log_summary,
    build_controlled_action_response,
    build_openclaw_prompt_guidance,
    build_prompt,
    build_post_response_official_lookup,
    build_skill_training_fallback,
    ask_ai,
    classify_openclaw_task_type,
    classify_question_intent,
    get_openclaw_lookup_reasons,
    is_problem_analysis_query,
    openclaw_outputs_answer_member_query,
    response_asks_user_to_lookup,
    select_controlled_tool,
    RequestStateTracker,
    should_answer_official_course_info_directly,
    should_retrieve_official_course_schedule,
    should_use_openclaw_lookup,
)
from xlxbot.knowledge import KnowledgeSection
from xlxbot.response_strategy import build_insufficient_knowledge_response
from xlxbot.sidecar.schemas import SidecarResult
from xlxbot.tool_registry import load_tool_registry


class RouterTestCase(unittest.TestCase):
    def test_classify_question_intent_fact(self):
        self.assertEqual(classify_question_intent('這是什麼'), INTENT_FACT)

    def test_classify_question_intent_course(self):
        self.assertEqual(classify_question_intent('課程是什麼'), INTENT_COURSE)
        self.assertEqual(classify_question_intent('今天有什麼課'), INTENT_COURSE)
        self.assertEqual(classify_question_intent('請問開課時間表在哪裡'), INTENT_COURSE)

    def test_skill_request_with_time_word_is_not_course_query(self):
        self.assertEqual(
            classify_question_intent('我是擔任本周的講評，題目是瑕疵品，開塲要解題，我可以如何說'),
            INTENT_HOW_TO,
        )
        self.assertEqual(
            classify_question_intent('我是擔任本周的總評，題目是瑕疵品'),
            INTENT_HOW_TO,
        )
        self.assertEqual(
            classify_question_intent('稿我不會寫，可以給我範例嗎？'),
            INTENT_HOW_TO,
        )

    def test_classify_question_intent_rule(self):
        self.assertEqual(classify_question_intent('規則是什麼'), INTENT_RULE)

    def test_classify_openclaw_task_type_knowledge_qa(self):
        self.assertEqual(classify_openclaw_task_type('請給我社團介紹', INTENT_FACT), 'knowledge_qa')

    def test_skill_request_is_not_openclaw_command(self):
        self.assertEqual(
            classify_openclaw_task_type(
                '我是擔任本周的講評，題目是瑕疵品，開塲要解題，我可以如何說',
                INTENT_HOW_TO,
            ),
            'knowledge_qa',
        )
        self.assertEqual(
            classify_openclaw_task_type(
                '我是擔任本周的總評，題目是瑕疵品',
                INTENT_HOW_TO,
            ),
            'knowledge_qa',
        )

    def test_classify_openclaw_task_type_command(self):
        self.assertEqual(classify_openclaw_task_type('改程式', INTENT_FACT), 'command')

    def test_classify_openclaw_task_type_user_correction(self):
        self.assertEqual(classify_openclaw_task_type('你錯了，應該是這樣', INTENT_FACT), 'user_correction')

    def test_classify_openclaw_task_type_error_report(self):
        self.assertEqual(classify_openclaw_task_type('系統出錯了', INTENT_FACT), 'error_report')

    def test_classify_openclaw_task_type_docs_request(self):
        self.assertEqual(classify_openclaw_task_type('請寫README', INTENT_FACT), 'docs_request')

    def test_select_controlled_tool_low_risk(self):
        tool_name, action, risk = select_controlled_tool('knowledge_qa', '請給我介紹')
        self.assertEqual(tool_name, 'knowledge_lookup')
        self.assertEqual(action, 'knowledge_lookup')
        self.assertEqual(risk, 'low')

    def test_select_controlled_tool_medium_risk(self):
        tool_name, action, risk = select_controlled_tool('docs_request', '請寫文件')
        self.assertEqual(tool_name, 'docs_draft')
        self.assertEqual(action, 'docs_draft')
        self.assertEqual(risk, 'medium')

    def test_select_controlled_tool_high_risk(self):
        tool_name, action, risk = select_controlled_tool('command', '改程式')
        self.assertEqual(tool_name, 'code_change')
        self.assertEqual(action, 'code_change')
        self.assertEqual(risk, 'high')

    def test_missing_sidecar_does_not_block_line_reply(self):
        response = build_controlled_action_response(
            'command',
            {
                'tool_name': 'sidecar_dispatch',
                'missing_constraints': ['SIDECAR_ENABLED'],
                'requires_approval': True,
            },
        )

        self.assertEqual(response, '')

    def test_sidecar_tool_requires_openclaw_base_url(self):
        registry = load_tool_registry()
        tool = registry.get('sidecar_dispatch')
        config = MagicMock()
        config.sidecar_enabled = True
        config.openclaw_base_url = ''

        missing = registry.get_missing_env_constraints(tool, config)

        self.assertIn('OPENCLAW_BASE_URL', missing)

    def test_openclaw_guidance_directs_reply_without_becoming_fact_source(self):
        guidance = build_openclaw_prompt_guidance(
            SidecarResult(
                status='ok',
                task_type='suggest',
                confidence=0.8,
                outputs=['先理解課程資料，再寫成 LINE 文宣。'],
                risk_level='medium',
                requires_approval=True,
                audit_ref='audit-1',
            )
        )

        self.assertIn('拆解使用者真正要解決的問題', guidance)
        self.assertIn('本地知識確認事實', guidance)
        self.assertIn('OpenClaw 查核結果補足', guidance)
        self.assertIn('若只是建議草稿，僅可作為分析策略', guidance)

    def test_openclaw_reference_log_summary_includes_sources_and_truncated_outputs(self):
        summary = build_openclaw_reference_log_summary(
            SidecarResult(
                status='ok',
                task_type='lookup',
                confidence=0.84,
                outputs=[
                    '根據 https://tmc1974.com/leaders/ 整理：楊朝富 第159期社長。' + '補充' * 500,
                    '根據 https://tmc1974.com/board-members/ 整理：梁慈珊 第十六屆理事長。',
                ],
                risk_level='low',
                requires_approval=False,
                audit_ref='audit-1',
            ),
            max_output_chars=80,
        )

        self.assertEqual(summary['audit_ref'], 'audit-1')
        self.assertEqual(summary['task_type'], 'lookup')
        self.assertIn('https://tmc1974.com/leaders/', summary['sources'])
        self.assertIn('https://tmc1974.com/board-members/', summary['sources'])
        self.assertTrue(summary['outputs'][0].endswith('...'))

    def test_member_query_grounding_must_match_founder_question(self):
        mismatched_result = SidecarResult(
            status='ok',
            task_type='lookup',
            confidence=0.84,
            outputs=['根據 https://tmc1974.com/leaders/ 整理：吳耿豪 第158期社長。'],
            risk_level='low',
            requires_approval=False,
            audit_ref='audit-1',
        )
        matched_result = SidecarResult(
            status='ok',
            task_type='lookup',
            confidence=0.84,
            outputs=[
                '根據 https://tmc1974.com/presidents/ 整理：\n'
                '- 創社：民國六十三年春，對外定名為健言社。\n'
                '- 歷任社長表：期別：第一期；社長：林毓彬；社務發展簡介：擔負起篳路藍縷的艱辛旅程。'
            ],
            risk_level='low',
            requires_approval=False,
            audit_ref='audit-2',
        )

        self.assertFalse(openclaw_outputs_answer_member_query('創社社長是誰？', mismatched_result))
        self.assertTrue(openclaw_outputs_answer_member_query('第158期社長是誰？', mismatched_result))
        self.assertTrue(openclaw_outputs_answer_member_query('創社社長是誰？', matched_result))

    def test_openclaw_lookup_reasons_include_empty_local_knowledge(self):
        class Config:
            sidecar_enabled = True
            openclaw_phase = 'suggest'

        reasons = get_openclaw_lookup_reasons(
            Config(),
            '現任幹部是誰？',
            'MEMBER_QUERY',
            '[無可用知識片段]',
        )

        self.assertIn('local_knowledge_empty_or_unusable', reasons)
        self.assertIn('current_or_time_sensitive_query', reasons)
        self.assertTrue(
            should_use_openclaw_lookup(
                Config(),
                '現任幹部是誰？',
                'MEMBER_QUERY',
                '[無可用知識片段]',
            )
        )

    def test_insufficient_response_points_to_official_sources_first(self):
        response = build_insufficient_knowledge_response('請提供可核對來源後再詢問。')

        self.assertIn('已核可官方來源', response)
        self.assertIn('官網', response)
        self.assertIn('課表', response)
        self.assertIn('官方社群', response)
        self.assertNotIn('請提供', response)

    def test_response_asks_user_to_lookup_detects_deflection(self):
        self.assertTrue(
            response_asks_user_to_lookup('社團的課程安排通常會在官網或社團公告頁面公佈，請你可以參考這些來源獲得最新的資訊。')
        )
        self.assertTrue(
            response_asks_user_to_lookup('請自行查詢官網課表取得最新資訊。')
        )
        self.assertTrue(
            response_asks_user_to_lookup('若您需要最新的課程資訊，建議您查閱台北市健言社的官網或官方社群。')
        )
        self.assertTrue(
            response_asks_user_to_lookup(
                '首先，我們需要拆解使用者真正要解決的問題。以下是我的回答：目前本地知識庫與可查核官方來源都沒有提供本期課程的資訊。若您需要最新的課程資訊，建議您查閱台北市健言社的官網或官方社群。'
            )
        )
        self.assertFalse(
            response_asks_user_to_lookup('根據台北市健言社官網課表，4/23 的 T.M. 訓練主題是拍賣會。')
        )

    def test_post_response_official_lookup_returns_external_source_result(self):
        providers = MagicMock()
        providers.query_course_info.return_value = '根據台北市健言社官網課表（https://tmc1974.com/schedule/），4/23 的課程資料如下：\n- T.M. 訓練主題：拍賣會'
        providers.query_latest_news.return_value = None
        providers.query_official_site_map.return_value = None

        response = build_post_response_official_lookup(providers, '請問 4/23 課程是什麼', INTENT_COURSE, None)

        self.assertIn('官方課表/課程查核', response)
        self.assertIn('T.M. 訓練主題：拍賣會', response)

    def test_skill_training_fallback_returns_general_tips_without_topic(self):
        response = build_post_response_official_lookup(
            MagicMock(),
            '我是擔任本周的總評，可以怎麼準備',
            INTENT_HOW_TO,
            None,
        )

        self.assertIn('通用技巧', response)
        self.assertIn('總評', response)
        self.assertIn('流程、角色、氣氛', response)
        self.assertNotIn('本地知識庫與可查核官方來源都沒有這項資訊', response)

    def test_skill_training_fallback_helper_covers_evaluation_role(self):
        response = build_skill_training_fallback('我是擔任本周的講評，但還沒有題目')

        self.assertIn('講評', response)
        self.assertIn('講員特色', response)
        self.assertIn('可先這樣說', response)

    def test_skill_training_fallback_helper_covers_generic_three_minute_draft(self):
        response = build_skill_training_fallback('稿我不會寫，可以給我範例嗎？')

        self.assertIn('三分鐘演講稿', response)
        self.assertIn('一句核心主旨', response)
        self.assertIn('三段結構', response)
        self.assertIn('可先這樣說', response)

    def test_prompt_forbids_exposing_internal_reasoning(self):
        class State:
            max_history_length = 5

        prompt = build_prompt(
            State(),
            '本期課程是什麼？',
            '[無可用知識片段]',
            INTENT_COURSE,
            manual_exists=True,
            manual_hit=False,
        )

        self.assertIn('不要把內部判斷流程寫給使用者', prompt)
        self.assertIn('禁止輸出內部流程或草稿語句', prompt)
        self.assertIn('以下是我的回答', prompt)

    def test_problem_analysis_query_reason_is_logged_for_openclaw_context(self):
        class Config:
            sidecar_enabled = True
            openclaw_phase = 'suggest'

        self.assertTrue(is_problem_analysis_query('這樣合理嗎？'))
        reasons = get_openclaw_lookup_reasons(
            Config(),
            '這樣合理嗎？',
            'FACT_QUERY',
            '## FAQ\n- [目前知識庫沒有這項資訊]',
        )

        self.assertIn('problem_analysis_requested', reasons)

    def test_request_tracker_allows_nested_step_transition(self):
        tracker = RequestStateTracker()

        tracker.start_step('provider_attempt_1')
        tracker.start_step('provider_gemini_call')
        tracker.end_step(success=True, result='success_with_gemini')

        summary = tracker.get_summary()
        self.assertEqual(summary['steps_count'], 2)
        self.assertEqual(summary['steps'][0]['name'], 'provider_attempt_1')
        self.assertEqual(summary['steps'][1]['name'], 'provider_gemini_call')

    def test_schedule_queries_force_official_course_retrieval(self):
        class Config:
            official_site_retrieval_enabled = False

        self.assertTrue(
            should_retrieve_official_course_schedule(
                Config(),
                '請為本周課程主題與 TM 題目作文宣',
                'PROMOTION_QUERY',
            )
        )
        self.assertTrue(
            should_retrieve_official_course_schedule(
                Config(),
                '我們的開課時間或時間表是什麼',
                'COURSE_QUERY',
            )
        )
        self.assertFalse(
            should_retrieve_official_course_schedule(
                Config(),
                '請介紹社團文化',
                'GENERAL_OVERVIEW',
            )
        )
        self.assertFalse(
            should_retrieve_official_course_schedule(
                Config(),
                '我是擔任本周的講評，題目是瑕疵品，開塲要解題，我可以如何說',
                INTENT_HOW_TO,
            )
        )
        self.assertFalse(
            should_retrieve_official_course_schedule(
                Config(),
                '我是擔任本周的總評，題目是瑕疵品',
                INTENT_HOW_TO,
            )
        )

    def test_skill_request_does_not_need_openclaw_lookup(self):
        class Config:
            sidecar_enabled = True
            openclaw_phase = 'suggest'

        reasons = get_openclaw_lookup_reasons(
            Config(),
            '我是擔任本周的講評，題目是瑕疵品，開塲要解題，我可以如何說',
            INTENT_HOW_TO,
            '## FAQ\n- [目前知識庫沒有這項資訊]',
        )

        self.assertEqual(reasons, [])
        reasons = get_openclaw_lookup_reasons(
            Config(),
            '我是擔任本周的總評，題目是瑕疵品',
            INTENT_HOW_TO,
            '## FAQ\n- [目前知識庫沒有這項資訊]',
        )

        self.assertEqual(reasons, [])

    def test_skill_coaching_prompt_requires_direct_topic_opening(self):
        class State:
            max_history_length = 5

        prompt = build_prompt(
            State(),
            '我是擔任本周的總評，題目是瑕疵品',
            '## 講評流程\n- 總評可整理流程、角色、氣氛與下次建議。',
            INTENT_HOW_TO,
            manual_exists=True,
            manual_hit=True,
        )

        self.assertIn('使用者是在要你教他怎麼說', prompt)
        self.assertIn('可立即練習的版本', prompt)
        self.assertIn('不要只回資料不足', prompt)
        self.assertIn('可直接使用的開場稿', prompt)
        self.assertIn('不要回答課表資訊', prompt)

    def test_course_context_includes_programs_and_events(self):
        sections = [
            KnowledgeSection(
                path='knowledge/90_club_manual.md',
                content='# club_manual\n\n## 訓練重點\n- 每週四 19:00 開課',
            ),
            KnowledgeSection(
                path='knowledge/50_programs_and_events.md',
                content='# 課程與活動\n\n## 近期活動（Recent）\n- 2026-04-17：第八週－故事延伸力',
            ),
            KnowledgeSection(
                path='knowledge/80_faq.md',
                content='# FAQ\n\n## Q6. 上課內容是什麼？\n- A：包含演講技巧、講評訓練、辯論與議事規則等訓練內容。',
            ),
        ]

        context, manual_exists, manual_hit = build_knowledge_context(sections, INTENT_COURSE)

        self.assertTrue(manual_exists)
        self.assertTrue(manual_hit)
        self.assertIn('每週四 19:00 開課', context)
        self.assertIn('第八週－故事延伸力', context)
        self.assertIn('演講技巧、講評訓練', context)

    def test_prompt_forbids_generic_official_source_advice_when_course_data_exists(self):
        class State:
            max_history_length = 5

        prompt = build_prompt(
            State(),
            '目前培訓班有什麼課程？',
            '--- 來自 台北市健言社官網課表 ---\n根據台北市健言社官網最新公告：\n- 2026-04-17: 第八週－故事延伸力',
            INTENT_COURSE,
            manual_exists=True,
            manual_hit=True,
        )

        self.assertIn('必須直接摘要日期、主題、訓練項目、講師或公告標題', prompt)
        self.assertIn('禁止只說「可參考官網或公告頁取得最新資訊」', prompt)

    def test_official_course_info_can_be_returned_directly(self):
        course_info = '根據台北市健言社官網最新公告：\n- 2026-04-17: 第八週－故事延伸力\n\n更多詳情請訪問官網：https://tmc1974.com/'

        self.assertTrue(
            should_answer_official_course_info_directly(
                '目前培訓班有什麼課程？',
                INTENT_COURSE,
                course_info,
            )
        )
        self.assertFalse(
            should_answer_official_course_info_directly(
                '請為本周課程主題作文宣',
                'PROMOTION_QUERY',
                course_info,
            )
        )
        self.assertFalse(
            should_answer_official_course_info_directly(
                '我是擔任本周的講評，題目是瑕疵品，開塲要解題，我可以如何說',
                INTENT_COURSE,
                course_info,
            )
        )

    @patch('xlxbot.router.load_knowledge_sections')
    def test_course_question_returns_official_schedule_content_without_provider_reasoning(self, mock_load_knowledge_sections):
        mock_load_knowledge_sections.return_value = [
            KnowledgeSection(
                path='knowledge/90_club_manual.md',
                content='# club_manual\n\n## 訓練重點\n- 每週四 19:00 開課',
            ),
        ]
        official_schedule = (
            '根據台北市健言社官網課表（https://tmc1974.com/schedule/），4/30 的課程資料如下：\n'
            '- TM 主題：瑕疵品\n'
            '  說明：本段會以「瑕疵品」作為 T.M. 訓練主軸，協助學員練習臨場表達、畫面描述與說服力。\n'
            '- 教育訓練題目：三分鐘講評\n'
            '  講師：王寶慶\n'
            '  說明：本段由王寶慶帶領，聚焦「三分鐘講評」，協助學員把技巧整理成可上台使用的表達方法。'
        )
        providers = MagicMock()
        providers.query_course_info.return_value = official_schedule
        config = SimpleNamespace(
            agent_path_enabled=False,
            teaching_planner_enabled=False,
            official_site_retrieval_enabled=True,
            sidecar_enabled=True,
            sidecar_mode='openclaw',
            sidecar_timeout_seconds=8,
            openclaw_phase='suggest',
        )
        state = SimpleNamespace(last_request_tracker=None)
        logger = MagicMock()

        response = ask_ai(
            config,
            state,
            logger,
            providers,
            '本期的課程有什麼？',
            history=[],
        )

        self.assertEqual(response, official_schedule)
        self.assertIn('https://tmc1974.com/schedule/', response)
        self.assertIn('TM 主題：瑕疵品', response)
        self.assertIn('說明：本段會以「瑕疵品」作為 T.M. 訓練主軸', response)
        self.assertIn('教育訓練題目：三分鐘講評', response)
        self.assertIn('講師：王寶慶', response)
        self.assertIn('說明：本段由王寶慶帶領，聚焦「三分鐘講評」', response)
        self.assertNotIn('首先，我們需要拆解', response)
        self.assertNotIn('以下是我的回答', response)
        self.assertNotIn('請自行查詢', response)
        providers.ask_gemini.assert_not_called()
        providers.ask_groq.assert_not_called()
        providers.ask_ollama.assert_not_called()

    @patch('xlxbot.router.load_knowledge_sections')
    def test_openclaw_schedule_lookup_returns_official_content_without_provider_reasoning(self, mock_load_knowledge_sections):
        mock_load_knowledge_sections.return_value = [
            KnowledgeSection(
                path='knowledge/90_club_manual.md',
                content='# club_manual\n\n## 訓練重點\n- 每週四 19:00 開課',
            ),
        ]
        official_schedule = (
            '官方課表/課程查核：\n'
            '根據台北市健言社官網課表（https://tmc1974.com/schedule/），4/30 的課程資料如下：\n'
            '- TM 主題：瑕疵品\n'
            '  說明：本段會以「瑕疵品」作為 T.M. 訓練主軸，協助學員練習臨場表達、畫面描述與說服力。\n'
            '- 教育訓練題目：三分鐘講評\n'
            '  講師：王寶慶\n'
            '  說明：本段由王寶慶帶領，聚焦「三分鐘講評」，協助學員把技巧整理成可上台使用的表達方法。'
        )

        class OpenClawScheduleDispatcher:
            def dispatch(self, user_input, intent, context):
                decision = SimpleNamespace(
                    should_call_sidecar=True,
                    reason='official-lookup',
                    task_type='lookup',
                )
                result = SidecarResult(
                    status='ok',
                    task_type='lookup',
                    confidence=0.9,
                    outputs=[official_schedule],
                    risk_level='low',
                    requires_approval=False,
                    audit_ref='openclaw-schedule',
                )
                return decision, result

        providers = MagicMock()
        config = SimpleNamespace(
            agent_path_enabled=False,
            teaching_planner_enabled=False,
            official_site_retrieval_enabled=False,
            sidecar_enabled=True,
            sidecar_mode='openclaw',
            sidecar_timeout_seconds=8,
            openclaw_phase='suggest',
        )
        state = SimpleNamespace(last_request_tracker=None)
        logger = MagicMock()

        response = ask_ai(
            config,
            state,
            logger,
            providers,
            '本期的課程有什麼？',
            history=[],
            dispatcher=OpenClawScheduleDispatcher(),
        )

        self.assertEqual(response, official_schedule)
        self.assertIn('https://tmc1974.com/schedule/', response)
        self.assertIn('TM 主題：瑕疵品', response)
        self.assertIn('說明：本段會以「瑕疵品」作為 T.M. 訓練主軸', response)
        self.assertIn('教育訓練題目：三分鐘講評', response)
        self.assertIn('講師：王寶慶', response)
        self.assertIn('說明：本段由王寶慶帶領，聚焦「三分鐘講評」', response)
        self.assertNotIn('首先，我們需要拆解', response)
        self.assertNotIn('以下是我的回答', response)
        self.assertNotIn('請自行查詢', response)
        providers.query_course_info.assert_not_called()
        providers.ask_gemini.assert_not_called()
        providers.ask_groq.assert_not_called()
        providers.ask_ollama.assert_not_called()

    @patch('xlxbot.router.load_knowledge_sections')
    def test_skill_coaching_request_uses_llm_without_official_lookup(self, mock_load_knowledge_sections):
        mock_load_knowledge_sections.return_value = [
            KnowledgeSection(
                path='knowledge/90_club_manual.md',
                content='# club_manual\n\n## 講評流程\n1. 先描述特色\n2. 再指出優點與建議',
            ),
        ]
        providers = MagicMock()
        providers.is_provider_available.side_effect = lambda name: name == 'groq'
        providers.ask_groq.return_value = (
            '你可以這樣開場：\n'
            '「瑕疵品不是失敗品，而是還沒被修好的作品。今天我的講評也會從這個角度出發。」'
        )
        dispatcher = MagicMock()
        config = SimpleNamespace(
            agent_path_enabled=False,
            teaching_planner_enabled=False,
            official_site_retrieval_enabled=True,
            sidecar_enabled=True,
            sidecar_mode='openclaw',
            sidecar_timeout_seconds=8,
            openclaw_phase='suggest',
            router_enabled=False,
            provider_timeout_seconds=5,
        )
        state = SimpleNamespace(
            last_request_tracker=None,
            route_general='GENERAL',
            route_expert='EXPERT',
            route_local='LOCAL',
            max_history_length=5,
        )
        logger = MagicMock()

        response = ask_ai(
            config,
            state,
            logger,
            providers,
            '我是擔任本周的講評，題目是瑕疵品，開塲要解題，我可以如何說',
            history=[],
            dispatcher=dispatcher,
        )

        self.assertIn('你可以這樣開場', response)
        self.assertIn('瑕疵品不是失敗品', response)
        dispatcher.dispatch.assert_not_called()
        providers.query_course_info.assert_not_called()
        providers.query_latest_news.assert_not_called()
        providers.query_official_site_map.assert_not_called()
        providers.ask_groq.assert_called_once()

    @patch('xlxbot.router.load_knowledge_sections')
    def test_general_evaluator_topic_request_uses_llm_without_official_lookup(self, mock_load_knowledge_sections):
        mock_load_knowledge_sections.return_value = [
            KnowledgeSection(
                path='knowledge/90_club_manual.md',
                content='# club_manual\n\n## 總評\n- 總評可整理流程、角色、氣氛與下次建議。',
            ),
        ]
        providers = MagicMock()
        providers.is_provider_available.side_effect = lambda name: name == 'groq'
        providers.ask_groq.return_value = (
            '可直接使用的開場稿：\n'
            '「瑕疵品不是沒有價值，而是提醒我們還有一個地方可以修得更好。'
            '今天我擔任總評，也會用這個角度來看整場流程。」'
        )
        dispatcher = MagicMock()
        config = SimpleNamespace(
            agent_path_enabled=False,
            teaching_planner_enabled=False,
            official_site_retrieval_enabled=True,
            sidecar_enabled=True,
            sidecar_mode='openclaw',
            sidecar_timeout_seconds=8,
            openclaw_phase='suggest',
            router_enabled=False,
            provider_timeout_seconds=5,
        )
        state = SimpleNamespace(
            last_request_tracker=None,
            route_general='GENERAL',
            route_expert='EXPERT',
            route_local='LOCAL',
            max_history_length=5,
        )
        logger = MagicMock()

        response = ask_ai(
            config,
            state,
            logger,
            providers,
            '我是擔任本周的總評，題目是瑕疵品',
            history=[],
            dispatcher=dispatcher,
        )

        self.assertIn('可直接使用的開場稿', response)
        self.assertIn('瑕疵品不是沒有價值', response)
        dispatcher.dispatch.assert_not_called()
        providers.query_course_info.assert_not_called()
        providers.query_latest_news.assert_not_called()
        providers.query_official_site_map.assert_not_called()
        providers.ask_groq.assert_called_once()

    @patch('xlxbot.router.load_knowledge_sections')
    def test_founder_president_question_returns_insufficient_when_official_result_does_not_match(self, mock_load_knowledge_sections):
        mock_load_knowledge_sections.return_value = [
            KnowledgeSection(
                path='knowledge/90_club_manual.md',
                content='# club_manual\n\n## 組織職責模板\n### 社長\n- 統籌社務與教育訓練方向',
            ),
        ]

        class MismatchedFounderDispatcher:
            def dispatch(self, user_input, intent, context):
                decision = SimpleNamespace(
                    should_call_sidecar=True,
                    reason='official-lookup',
                    task_type='lookup',
                )
                result = SidecarResult(
                    status='ok',
                    task_type='lookup',
                    confidence=0.84,
                    outputs=['根據 https://tmc1974.com/leaders/ 整理：吳耿豪 第158期社長。'],
                    risk_level='low',
                    requires_approval=False,
                    audit_ref='member-mismatch',
                )
                return decision, result

        providers = MagicMock()
        providers.is_provider_available.return_value = True
        config = SimpleNamespace(
            agent_path_enabled=False,
            teaching_planner_enabled=False,
            official_site_retrieval_enabled=False,
            sidecar_enabled=True,
            sidecar_mode='openclaw',
            sidecar_timeout_seconds=8,
            openclaw_phase='suggest',
            router_enabled=False,
            provider_timeout_seconds=5,
        )
        state = SimpleNamespace(
            last_request_tracker=None,
            route_general='GENERAL',
            route_expert='EXPERT',
            route_local='LOCAL',
            max_history_length=5,
        )
        logger = MagicMock()

        response = ask_ai(
            config,
            state,
            logger,
            providers,
            '創社社長是誰？',
            history=[],
            dispatcher=MismatchedFounderDispatcher(),
        )

        self.assertIn('沒有取得足夠明確的資料', response)
        self.assertIn('人物或職位問題', response)
        self.assertNotIn('吳耿豪', response)
        providers.ask_gemini.assert_not_called()
        providers.ask_groq.assert_not_called()
        providers.ask_ollama.assert_not_called()

    @patch('xlxbot.router.load_knowledge_sections')
    def test_founder_president_question_can_use_first_president_from_official_history(self, mock_load_knowledge_sections):
        mock_load_knowledge_sections.return_value = [
            KnowledgeSection(
                path='knowledge/20_history.md',
                content='# 社團沿革\n\n- [需要社團管理員補充]',
            ),
        ]

        class FounderHistoryDispatcher:
            def dispatch(self, user_input, intent, context):
                decision = SimpleNamespace(
                    should_call_sidecar=True,
                    reason='official-lookup',
                    task_type='lookup',
                )
                result = SidecarResult(
                    status='ok',
                    task_type='lookup',
                    confidence=0.84,
                    outputs=[
                        '根據 https://tmc1974.com/presidents/ 整理：\n'
                        '- 創社：民國六十三年春，對外定名為健言社。\n'
                        '- 歷任社長表：期別：第一期；社長：林毓彬；社務發展簡介：擔負起篳路藍縷的艱辛旅程。'
                    ],
                    risk_level='low',
                    requires_approval=False,
                    audit_ref='founder-history',
                )
                return decision, result

        providers = MagicMock()
        providers.is_provider_available.side_effect = lambda name: name == 'groq'
        providers.ask_groq.return_value = '官方頁沒有直接寫「創社社長」，但歷任社長表第一期社長是林毓彬。'
        config = SimpleNamespace(
            agent_path_enabled=False,
            teaching_planner_enabled=False,
            official_site_retrieval_enabled=False,
            sidecar_enabled=True,
            sidecar_mode='openclaw',
            sidecar_timeout_seconds=8,
            openclaw_phase='suggest',
            router_enabled=False,
            provider_timeout_seconds=5,
        )
        state = SimpleNamespace(
            last_request_tracker=None,
            route_general='GENERAL',
            route_expert='EXPERT',
            route_local='LOCAL',
            max_history_length=5,
        )
        logger = MagicMock()

        response = ask_ai(
            config,
            state,
            logger,
            providers,
            '創社社長是誰？',
            history=[],
            dispatcher=FounderHistoryDispatcher(),
        )

        self.assertIn('第一期社長是林毓彬', response)
        self.assertNotIn('沒有取得足夠明確的資料', response)
        providers.ask_groq.assert_called_once()

    @patch('xlxbot.router.load_knowledge_sections')
    def test_generic_draft_request_uses_three_minute_speech_guidance_without_official_lookup(self, mock_load_knowledge_sections):
        mock_load_knowledge_sections.return_value = [
            KnowledgeSection(
                path='knowledge/90_club_manual.md',
                content='# club_manual\n\n## 講員訓練重點\n- 準備：審題、收集資料、建立結構',
            ),
        ]
        providers = MagicMock()
        providers.is_provider_available.side_effect = lambda name: name == 'groq'
        providers.ask_groq.return_value = (
            '可以，三分鐘講稿先用「開場畫面、故事轉折、結尾回扣」。\n'
            '範例：第一次上台時，我以為要講得完美，後來才發現講清楚一件事更重要。'
        )
        dispatcher = MagicMock()
        config = SimpleNamespace(
            agent_path_enabled=False,
            teaching_planner_enabled=False,
            official_site_retrieval_enabled=True,
            sidecar_enabled=True,
            sidecar_mode='openclaw',
            sidecar_timeout_seconds=8,
            openclaw_phase='suggest',
            router_enabled=False,
            provider_timeout_seconds=5,
        )
        state = SimpleNamespace(
            last_request_tracker=None,
            route_general='GENERAL',
            route_expert='EXPERT',
            route_local='LOCAL',
            max_history_length=5,
        )
        logger = MagicMock()

        response = ask_ai(
            config,
            state,
            logger,
            providers,
            '稿我不會寫，可以給我範例嗎？',
            history=[],
            dispatcher=dispatcher,
        )

        self.assertIn('三分鐘講稿', response)
        self.assertIn('開場畫面、故事轉折、結尾回扣', response)
        dispatcher.dispatch.assert_not_called()
        providers.query_course_info.assert_not_called()
        providers.query_latest_news.assert_not_called()
        providers.query_official_site_map.assert_not_called()
        providers.ask_groq.assert_called_once()


if __name__ == '__main__':
    unittest.main()
