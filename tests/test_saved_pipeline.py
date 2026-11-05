"""Replay recorded model responses through current processing; not a new LLM run."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app

class SavedPipelineTests(unittest.TestCase):
    def check_example(self, name):
        product = app.validate_input(json.loads((ROOT/'examples'/f'{name}.json').read_text()))
        saved = json.loads((ROOT/'examples/results'/f'{name}.json').read_text())
        with patch.object(app, 'call_model', return_value=copy.deepcopy(saved['raw_generation'])), \
             patch.object(app, 'audit_model', return_value=saved['review']['model_audit']):
            result = app.generate(product)
        for key in ('title','description','commercial','queries','characteristics','missing_fields',
                    'raw_generation','source_facts','claim_trace'):
            self.assertEqual(result[key], saved[key], key)
        self.assertEqual(result['review']['automated_issues'], [])
        self.assertEqual(result['review']['series_qualifications'], saved['review']['series_qualifications'])

    def test_trm151_recording(self): self.check_example('trm151')
    def test_dts014_recording(self): self.check_example('dts014')
