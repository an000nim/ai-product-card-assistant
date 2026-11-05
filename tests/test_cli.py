"""CLI rejection checks never call a live model."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class CliTests(unittest.TestCase):
    def run_bad_input(self, content, expected):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.json'
            source.write_bytes(content)
            run = subprocess.run([sys.executable, str(ROOT/'app.py'), str(source)],
                                 capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(run.stdout, '')
        self.assertIn(expected, run.stderr)
        self.assertNotIn('Traceback', run.stderr)

    def test_invalid_json(self):
        self.run_bad_input(b'{', 'Ошибка:')

    def test_blank_name(self):
        self.run_bad_input(b'{"name":" "}', 'name')

    def test_invalid_encoding(self):
        self.run_bad_input(b'\xff', 'Ошибка:')

    def test_duplicate_source_values(self):
        self.run_bad_input(b'{"name":"test","specs":{"s":"24 V","s":"48 V"}}',
                           'Повторяющееся поле JSON')

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            run = subprocess.run([sys.executable, str(ROOT/'app.py'), str(Path(folder)/'absent.json')],
                                 capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(run.stdout, '')
        self.assertNotIn('Traceback', run.stderr)
        self.assertIn('Ошибка:', run.stderr)
