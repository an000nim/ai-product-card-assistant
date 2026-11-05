#!/usr/bin/env python3
"""Probe LLM self-review; outputs observations, not a measure of real-world reliability."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app

cases=json.loads((ROOT/'evaluation/cases.json').read_text(encoding='utf-8'))
results=[]
for case in cases:
    product=app.validate_input(json.loads((ROOT/'evaluation'/'fixtures'/f"{case['product']}.json").read_text(encoding='utf-8')))
    draft={'title':product['name'],'description':case['claim'],'queries':[product['name'],product['name']+' характеристики',product['name']+' купить'],'commercial':'Назначение прибора требует уточнения.'}
    try:
        issues=app.audit_model(product,draft)
        results.append({**case,'model_issues':issues,'flagged':bool(issues)})
    except app.ModelError as exc:
        results.append({**case,'error':str(exc),'flagged':None})
print(json.dumps(results,ensure_ascii=False,indent=2))
