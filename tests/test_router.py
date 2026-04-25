import unittest
from unittest.mock import patch, MagicMock
from xlxbot.router import classify_question_intent, INTENT_FACT, INTENT_COURSE, INTENT_RULE, classify_openclaw_task_type, select_controlled_tool


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


if __name__ == '__main__':
    unittest.main()