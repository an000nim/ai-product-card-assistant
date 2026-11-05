#!/usr/bin/env python3
"""Check saved example invariants; does not replace a subject-matter review."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from render_result import render_markdown

def check(name):
    source=json.loads((ROOT/'examples'/f'{name}.json').read_text(encoding='utf-8'))
    result=json.loads((ROOT/'examples'/'results'/f'{name}.json').read_text(encoding='utf-8'))
    assert len(result['title'])<=70,(name,'title length')
    assert 800<=len(result['description'])<=1200,(name,'description length')
    assert 3<=len(result['queries'])<=5,(name,'query count')
    assert result['review']['status']=='требуется проверка человеком'
    assert not result['review']['automated_issues'],(name,result['review']['automated_issues'])
    assert not result['review']['context_warnings'],(name,result['review']['context_warnings'])
    assert 'raw_generation' in result
    presentation=(ROOT/'examples'/'results'/f'{name}.md').read_text(encoding='utf-8')
    assert presentation == render_markdown(result),(name,'Markdown differs from JSON')
    for k,v in source['specs'].items():
        assert result['characteristics'][k] == (v or 'данных нет'),(name,k)
    assert all(c['статус']=='нужна проверка человеком' for c in result['claim_trace'])
    for m in result['review']['local_request_metrics']:
        assert m['prompt_tokens']+(m['generated_tokens'] or 0)<m['context_limit'],(name,'context overflow')
    print(name, len(result['title']),len(result['description']),len(result['queries']))

if __name__=='__main__':
    try:
        for n in ('trm151','dts014'):check(n)
    except (AssertionError,KeyError,ValueError,OSError) as exc:
        print('Проверка примеров не пройдена:',exc,file=sys.stderr)
        sys.exit(1)
