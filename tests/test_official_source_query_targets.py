import unittest
from types import SimpleNamespace

from xlxbot.providers import ProviderService


OFFICIAL_SOURCE_QUERY_CASES = {
    'presidents_history': {
        'expected_url': 'https://tmc1974.com/presidents/',
        'questions': [
            '請查 https://tmc1974.com/presidents/ 的歷任理事長及社長資料',
            '歷任社長名單在哪裡？',
            '第一期社長是誰？',
            '創社背景是什麼？',
            '創辦人或創社相關資料有嗎？',
            '健言社沿革可以介紹嗎？',
            '社團歷史有哪些重點？',
            '草創時期誰在帶？',
            '最早那一期的社長是誰？',
            '想了解前輩一路走來的歷史',
        ],
    },
    'teachers': {
        'expected_url': 'https://tmc1974.com/teachers/',
        'questions': [
            '請查 https://tmc1974.com/teachers/ 的認證師資',
            '健言社有哪些認證講師？',
            '講師資料有哪些？',
            '誰可以教三分鐘演講？',
            '有沒有審題撰稿的老師？',
            '想找講評訓練的講師',
            '師資專長可以查嗎？',
            '哪位教練適合教主持？',
            '我想找會教上台的人',
            '有哪些老師可以請教？',
        ],
    },
    'reflection': {
        'expected_url': 'https://tmc1974.com/category/reflection/',
        'questions': [
            '請查 https://tmc1974.com/category/reflection/ 的學習心得',
            '學習心得有哪些文章？',
            '155期第十四週心得是什麼？',
            '有沒有會內會心得範例？',
            '社友上課心得可以查嗎？',
            '我想看上台後的感想',
            '有沒有社長感想文章？',
            '想參考別人怎麼寫心得',
            '有沒有反思類文章？',
            '大家學完都怎麼想？',
        ],
    },
    'join_qa': {
        'expected_url': 'https://tmc1974.com/join/',
        'questions': [
            '請查 https://tmc1974.com/join/ 的加入健言社與 Q&A',
            '怎麼加入健言社？',
            '報名方式是什麼？',
            '可以中途加入嗎？',
            '費用是多少？',
            '可以先試聽嗎？',
            '單堂多少錢？',
            '缺席需要請假嗎？',
            '我想知道怎麼參加',
            '想先去看看要多少錢',
        ],
    },
}


class OfficialSourceQueryTargetTestCase(unittest.TestCase):
    def setUp(self):
        self.provider = ProviderService(
            config=SimpleNamespace(gemini_api_key=''),
            state=object(),
            logger=object(),
        )

    def test_each_official_source_has_ten_question_cases(self):
        for category, spec in OFFICIAL_SOURCE_QUERY_CASES.items():
            with self.subTest(category=category):
                self.assertEqual(len(spec['questions']), 10)

    def test_questions_route_to_expected_official_sources_from_specific_to_vague(self):
        for category, spec in OFFICIAL_SOURCE_QUERY_CASES.items():
            expected_url = spec['expected_url']
            for index, question in enumerate(spec['questions'], 1):
                with self.subTest(category=category, index=index, question=question):
                    self.assertTrue(self.provider._is_official_site_query(question))
                    targets = self.provider._get_official_site_targets(question, 'FACT_QUERY')
                    self.assertIn(expected_url, targets)


if __name__ == '__main__':
    unittest.main()
