import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from xlxbot.knowledge import read_text_file, list_markdown_files, dedupe_existing_files, KnowledgeSection


class KnowledgeTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_read_text_file_existing(self):
        test_file = os.path.join(self.temp_dir, 'test.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('test content')
        logger = MagicMock()
        content = read_text_file(test_file, logger)
        self.assertEqual(content, 'test content')

    def test_read_text_file_nonexistent(self):
        logger = MagicMock()
        content = read_text_file('/nonexistent/file.txt', logger)
        self.assertIsNone(content)

    def test_read_text_file_empty(self):
        test_file = os.path.join(self.temp_dir, 'empty.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('')
        logger = MagicMock()
        content = read_text_file(test_file, logger)
        self.assertIsNone(content)

    def test_list_markdown_files(self):
        # Create test files
        md_file = os.path.join(self.temp_dir, 'test.md')
        txt_file = os.path.join(self.temp_dir, 'test.txt')
        with open(md_file, 'w') as f:
            f.write('# Test')
        with open(txt_file, 'w') as f:
            f.write('test')

        files = list_markdown_files(self.temp_dir)
        self.assertIn(md_file, files)
        self.assertNotIn(txt_file, files)

    def test_dedupe_existing_files(self):
        test_file = os.path.join(self.temp_dir, 'test.md')
        with open(test_file, 'w') as f:
            f.write('content')

        files = dedupe_existing_files([test_file, test_file, '/nonexistent.md'])
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0], test_file)


if __name__ == '__main__':
    unittest.main()