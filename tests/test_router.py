import unittest
from unittest.mock import patch, MagicMock
from xlxbot.router import (
    INTENT_FACT,
    INTENT_COURSE,
    INTENT_RULE,
    build_controlled_action_response,
    build_openclaw_prompt_guidance,
    classify_openclaw_task_type,
    classify_question_intent,
    select_controlled_tool,
    RequestStateTracker,
    should_retrieve_official_course_schedule,
)
from xlxbot.sidecar.schemas import SidecarResult
from xlxbot.tool_registry import load_tool_registry


class RouterTestCase(unittest.TestCase):
    def test_classify_question_intent_fact(self):
        self.assertEqual(classify_question_intent('這是什麼'), INTENT_FACT)

    def test_classify_question_intent_course(self):
        self.assertEqual(classify_question_intent('課程是什麼'), INTENT_COURSE)
        self.assertEqual(classify_question_intent('今天有什麼課'), INTENT_COURSE)

    def test_classify_question_intent_rule(self):
        self.assertEqual(classify_question_intent('規則是什麼'), INTENT_RULE)

    def test_classify_openclaw_task_type_knowledge_qa(self):
        self.assertEqual(classify_openclaw_task_type('請給我社團介紹', INTENT_FACT), 'knowledge_qa')

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
        self.assertFalse(
            should_retrieve_official_course_schedule(
                Config(),
                '請介紹社團文化',
                'GENERAL_OVERVIEW',
            )
        )


if __name__ == '__main__':
    unittest.main()
