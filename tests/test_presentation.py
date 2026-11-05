import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from render_result import render_markdown, text

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.result = json.loads((ROOT/'examples/results/trm151.json').read_text())

    def test_preserves_content_and_missing_data(self):
        original = copy.deepcopy(self.result)
        output = render_markdown(self.result)
        self.assertIn(self.result['description'], output)
        self.assertIn(self.result['commercial'], output)
        self.assertIn('данных нет', output)
        self.assertIn('конфликт источников', output)
        self.assertEqual(self.result, original)

    def test_does_not_hide_warning_or_audit_failure(self):
        self.result['review']['automated_issues'] = ['описание слишком короткое']
        self.result['review']['context_warnings'] = ['возможное усечение']
        self.result['review']['audit_error'] = 'самопроверка не выполнена'
        output = render_markdown(self.result)
        for warning in ['описание слишком короткое','возможное усечение','самопроверка не выполнена']:
            self.assertIn(warning, output)
        self.assertNotIn('Автоматических замечаний нет', output)

    def test_escapes_markdown_table_and_html(self):
        self.assertEqual(text('A|B\n<script>'), 'A\\|B &lt;script&gt;')
        self.assertIn('\\[', text('[link](file)'))

    def test_cli_markdown_uses_generated_result(self):
        import io
        stream = io.StringIO()
        with patch.object(sys, 'argv', ['app.py', str(ROOT/'examples/trm151.json'), '--format', 'markdown']), \
             patch.object(app, 'generate', return_value=self.result), patch('sys.stdout', stream):
            self.assertEqual(app.main(), 0)
        self.assertEqual(stream.getvalue(), render_markdown(self.result))
