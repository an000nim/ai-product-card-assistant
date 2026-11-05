import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

GOOD={'title':'Прибор М1', 'description':'Модель М1. '+'А'*810,'queries':['прибор М1','прибор М1 купить','М1 характеристики'], 'commercial':'Назначение прибора: измерение давления.'}

class ProductCardTests(unittest.TestCase):
    def setUp(self):
        self.raw={'name':'Манометр М1','model':'М1','manufacturer':'Завод', 'description':'Измерение давления.', 'specs':{'класс точности':'1,5'}}
        self.product=app.validate_input(self.raw)
        audit_patcher=patch.object(app,'audit_model',return_value=[])
        audit_patcher.start()
        self.addCleanup(audit_patcher.stop)

    def test_missing_pressure_gauge_fields(self):
        profile, guessed, fields=app.missing_data(self.product)
        self.assertEqual(profile,'pressure_gauge')
        self.assertTrue(guessed)
        self.assertIn('диапазон измерений',[f['field'] for f in fields])
        self.assertIn('присоединение',[f['field'] for f in fields])
        self.assertNotIn('класс точности',[f['field'] for f in fields])

    def test_rejects_invalid_input(self):
        for bad in ({}, [], {'name':3}, {'name':'x','specs':[]}, {'name':'x','specs':{'a':None}}, {'name':'x','profile':'made_up'}):
            with self.subTest(bad=bad), self.assertRaises(app.InputError): app.validate_input(bad)

    def test_rejects_colliding_trimmed_spec_names(self):
        with self.assertRaises(app.InputError):
            app.validate_input({'name':'x','specs':{'Питание':'24 В',' Питание ':'12 В'}})

    def test_unsupported_numeric_claim_is_flagged(self):
        draft={**GOOD,'description':GOOD['description']+' Рабочее давление 999 МПа.'}
        issues,numbers=app.assess(draft,self.product)
        self.assertIn('999',numbers)
        self.assertTrue(any('неподтвержд' in x for x in issues))

    def test_grounding_does_not_claim_to_validate_meaning(self):
        with patch.object(app,'call_model',return_value=GOOD):
            r=app.generate(self.product)
        self.assertEqual(r['review']['status'],'требуется проверка человеком')
        self.assertIn('не подтверждает смысл',r['review']['limitations'])
        self.assertTrue(all(c['статус']=='нужна проверка человеком' for c in r['claim_trace']))
        self.assertEqual(r['characteristics']['класс точности'],'1,5')

    def test_retry_and_reports_length_violations(self):
        short={**GOOD,'description':'Модель М1.'}
        with patch.object(app,'call_model',side_effect=[short,GOOD]) as calls:
            r=app.generate(self.product)
        self.assertEqual(calls.call_count,2)
        self.assertIn('символов',calls.call_args.args[1][0])
        self.assertTrue(calls.call_args.args[2]['description'].startswith(short['description']))
        self.assertEqual(r['review']['attempts'],2)
        self.assertFalse(r['review']['automated_issues'])

    def test_short_draft_can_include_real_missing_field_without_inventing_value(self):
        self.raw['specs']['присоединение']=''
        product=app.validate_input(self.raw)
        draft={**GOOD,'description':'Модель М1. '+('А'*755)}
        with patch.dict(os.environ,{'LLM_MAX_ATTEMPTS':'1'}), patch.object(app,'call_model',return_value=draft):
            result=app.generate(product)
        self.assertTrue(result['review']['missing_fields_added_by_program'])
        self.assertIn('Требуется уточнить: присоединение.', result['description'])
        self.assertEqual(result['characteristics']['присоединение'],'данных нет')

    def test_retry_on_bad_model_format(self):
        with patch.object(app,'call_model',side_effect=[app.ModelFormatError('неверный ответ'),GOOD]) as calls:
            r=app.generate(self.product)
        self.assertEqual(calls.call_count,2)
        self.assertEqual(r['review']['attempts'],2)

    def test_detects_repeated_sentences(self):
        d={**GOOD,'description':'Модель М1 измеряет давление. Модель М1 измеряет давление. '+'Т'*810}
        issues,_=app.assess(d,self.product)
        self.assertTrue(any('повторяются предложения' in x for x in issues))

    def test_selects_earlier_safer_draft_if_retry_introduces_number(self):
        first={**GOOD,'description':'Модель М1. '+('А'*740)}
        second={**GOOD,'description':GOOD['description']+' Давление 999 МПа.'}
        with patch.object(app,'call_model',side_effect=[first,second]):
            r=app.generate(self.product)
        self.assertEqual(r['review']['selected_attempt'],1)
        self.assertNotIn('999',r['description'])
        self.assertTrue(any('описание содержит' in e for e in r['review']['automated_issues']))

    def test_retains_prior_draft_if_last_attempt_is_malformed(self):
        first={**GOOD,'description':'Модель М1.'}
        with patch.object(app,'call_model',side_effect=[first,app.ModelFormatError('неверный формат')]):
            r=app.generate(self.product)
        self.assertEqual(r['review']['selected_attempt'],1)
        self.assertEqual(r['review']['last_format_error'],'неверный формат')

    def test_no_spec_is_added_from_llm(self):
        draft={**GOOD,'description':GOOD['description']+' Значение 999.'}
        with patch.dict(os.environ,{'LLM_MAX_ATTEMPTS':'1'}), patch.object(app,'call_model',return_value=draft):
            r=app.generate(self.product)
        self.assertEqual(r['characteristics'],self.raw['specs'])
        self.assertIn('999',r['review']['unmatched_numbers'])

    def test_conflict_is_reported(self):
        self.raw['conflicts']=['В источниках разные значения: уточнить.']
        p=app.validate_input(self.raw)
        _,_,missing=app.missing_data(p)
        self.assertTrue(any(x['field']=='конфликт источников' for x in missing))

    def test_flags_series_value_without_qualification_and_ambient_confusion(self):
        p=app.validate_input({'name':'термопреобразователь сопротивления M1','model':'M1','description':'Датчик температуры.', 'specs':{'Температура окружающего воздуха':'−60…+85 °C (по таблице серии)'}})
        d={**GOOD,'description':'M1. Работает в диапазоне температур −60 до +85 °C.'+'А'*800}
        issues,_=app.assess(d,p)
        self.assertTrue(any('окружающего воздуха' in x for x in issues))
        self.assertTrue(any('относится к серии' in x for x in issues))

    def test_marks_unmatched_negative_and_comparison(self):
        d={**GOOD,'description':GOOD['description']+' Температура −99 °C; предел ≥ 77.'}
        issues,_=app.assess(d,self.product)
        self.assertTrue(any('отрицательные значения' in x for x in issues))
        self.assertTrue(any('знаки неравенства' in x for x in issues))

    def test_openai_compatible_valid_response(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(GOOD)}}]}).encode()
        with patch.dict(os.environ,{'LLM_BACKEND':'openai'}), patch.object(app.urllib.request,'urlopen',return_value=Resp()):
            result=app.call_model(self.product)
        self.assertEqual(result['title'],GOOD['title'])
        self.assertEqual(result['queries'],GOOD['queries'])

    def test_openai_null_choice_is_reported_cleanly(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"choices":[null]}'
        with patch.dict(os.environ,{'LLM_BACKEND':'openai'}), patch.object(app.urllib.request,'urlopen',return_value=Resp()), self.assertRaises(app.ModelFormatError):
            app.call_model(self.product)

    def test_malformed_model_response_is_error(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"choices":[{"message":{"content":"invalid JSON"}}]}'
        with patch.dict(os.environ,{'LLM_BACKEND':'openai'}), patch.object(app.urllib.request,'urlopen',return_value=Resp()), self.assertRaises(app.ModelError):
            app.call_model(self.product)

    def test_unavailable_api_is_error(self):
        with patch.object(app.urllib.request,'urlopen',side_effect=app.urllib.error.URLError('offline')), self.assertRaises(app.ModelError):
            app.call_model(self.product)

    def test_flags_unfounded_marketing_claim(self):
        d={**GOOD,'commercial':'Высокая степень защиты и надёжная работа.'}
        issues,_=app.assess(d,self.product)
        self.assertTrue(any('оценка или область применения' in x for x in issues))

    def test_flags_unsubstantiated_application(self):
        d={**GOOD,'commercial':'Подходит для энергетики и транспортировки.'}
        issues,_=app.assess(d,self.product)
        self.assertTrue(any('энергетик' in x for x in issues))
        self.assertTrue(any('транспорт' in x for x in issues))

    def test_title_and_description_boundaries(self):
        p=app.validate_input({'name':'Прибор','manufacturer':'Завод','description':'Описание','specs':{}})
        for size,should_flag in [(799,True),(800,False),(1200,False),(1201,True)]:
            d={**GOOD,'title':'T'*70,'description':'А'*size}
            issues,_=app.assess(d,p)
            self.assertEqual(any('описание содержит' in x for x in issues),should_flag)
            self.assertFalse(any('заголовок содержит' in x for x in issues))
        d={**GOOD,'title':'T'*71}
        issues,_=app.assess(d,p)
        self.assertTrue(any('заголовок содержит' in x for x in issues))

    def test_supplements_only_with_exact_input_facts(self):
        product=app.validate_input({'name':'Товар','specs':{'Класс':'1,5','Питание':'24 В','Неизвестное':'','IP':'данных нет'}})
        text,added=app.supplement_description('А'*770,product)
        self.assertTrue(added)
        for row in added:
            key=row['field'][len('specs.'):]
            self.assertIn(product['specs'][key],text)
            self.assertNotEqual(product['specs'][key],'')
        self.assertNotIn('данных нет',text)
        self.assertLessEqual(len(text),1200)

    def test_does_not_repeat_exact_fact_or_append_when_full(self):
        p=app.validate_input({'name':'Товар','specs':{'Питание':'24 В'}})
        text,added=app.supplement_description('Питание 24 В. '+('А'*770),p)
        self.assertEqual(added,[])
        text,added=app.supplement_description('А'*800,p)
        self.assertEqual(added,[])

    def test_model_audit_concerns_become_visible_and_trigger_retry(self):
        with patch.object(app,'call_model',side_effect=[GOOD,GOOD]), patch.object(app,'audit_model',side_effect=[['сомнительное утверждение'],[]]) as audit:
            r=app.generate(self.product)
        self.assertEqual(audit.call_count,2)
        self.assertEqual(r['review']['attempts'],2)
        self.assertEqual(r['review']['model_audit'],[])

    def test_failed_model_audit_does_not_disappear(self):
        with patch.dict(os.environ,{'LLM_MAX_ATTEMPTS':'1'}), patch.object(app,'call_model',return_value=GOOD), patch.object(app,'audit_model',side_effect=app.ModelError('недоступно')):
            r=app.generate(self.product)
        self.assertEqual(r['review']['audit_error'],'недоступно')
        self.assertTrue(any('не выполнена' in x for x in r['review']['automated_issues']))
        self.assertEqual(r['review']['status'],'требуется проверка человеком')

    def test_flags_number_reused_with_wrong_unit(self):
        p=app.validate_input({'name':'прибор','description':'Питание 24 В; масса 5 кг','specs':{}})
        d={**GOOD,'description':'Модель. Питание 24 кг. '+'А'*810}
        issues,_=app.assess(d,p)
        self.assertTrue(any('единицей измерения' in issue for issue in issues))

    def test_trace_marks_wrong_number_unit_on_specific_claim(self):
        p=app.validate_input({'name':'прибор','description':'Питание 24 В и масса 5 кг.'})
        d={**GOOD,'description':'Вес прибора — 24 кг.'}
        t=app.build_claim_trace(d,p)
        self.assertTrue(any('единицей' in signal for row in t for signal in row['автоматические_сигналы']))

    def test_exact_duplicate_removed_and_original_preserved(self):
        text='Модель М1 измеряет давление. Модель М1 измеряет давление.'
        out,removed=app.remove_repeated_sentences(text)
        self.assertEqual(out,'Модель М1 измеряет давление.')
        self.assertEqual(len(removed),1)
        draft={**GOOD,'description':text+' '+'А'*790}
        with patch.dict(os.environ,{'LLM_MAX_ATTEMPTS':'1'}), patch.object(app,'call_model',return_value=draft):
            result=app.generate(self.product)
        self.assertEqual(result['raw_generation']['description'],draft['description'])
        self.assertEqual(len(result['review']['duplicates_removed']),1)
        self.assertEqual(result['description'].count('Модель М1 измеряет давление.'),1)

    def test_preposition_is_not_treated_as_seconds(self):
        self.assertFalse(app.measurement_tokens('кабель 0,2 с кабельным выводом'))

    def test_audit_response_validation(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self):
                return json.dumps({'choices':[{'message':{'content':json.dumps({'issues':'не массив'})}}]}).encode()
        # setUp replaces audit_model for the rest of the tests; load a fresh module here.
        import importlib.util
        spec=importlib.util.spec_from_file_location('audit_app',Path(app.__file__))
        isolated=importlib.util.module_from_spec(spec);spec.loader.exec_module(isolated)
        with patch.dict(os.environ,{'LLM_BACKEND':'openai'}), patch.object(isolated.urllib.request,'urlopen',return_value=Resp()), self.assertRaises(isolated.ModelError):
            isolated.audit_model(self.product,GOOD)

    def test_title_fit_keeps_exact_model_without_cutting_words(self):
        p=app.validate_input({'name':'Манометр М1','model':'М1'})
        title='Манометр М1 — '+('подробное и длинное описание '*4)
        value,note=app.fit_title(title,p)
        self.assertEqual(value,'Манометр М1')
        self.assertIsNotNone(note)
        self.assertIn('М1',value)

    def test_title_too_long_with_no_safe_fallback_is_flagged(self):
        p=app.validate_input({'name':'Н'*80,'model':'M1'})
        title='M1 '+'A'*80
        out,note=app.fit_title(title,p)
        self.assertEqual(out,title)
        self.assertIsNone(note)

    def test_conflict_about_inequality_not_described_as_different_values(self):
        p=app.validate_input({'name':'Регулятор','description':'Знаки условий разные.','conflicts':['cos φ > 0,4 или ≥ 0,4'], 'specs':{}})
        d={**GOOD,'description':'М1. Указаны разные значения параметра cos φ. '+'А'*800}
        issues,_=app.assess(d,p)
        self.assertTrue(any('знаки условий' in x for x in issues))

    def test_flags_unconfirmed_durability_and_industrial_use(self):
        p=app.validate_input({'name':'датчик М1','model':'М1','description':'Датчик измеряет температуру.'})
        d={**GOOD,'commercial':'Для промышленных задач, надёжность и долговечность.'}
        issues,_=app.assess(d,p)
        self.assertTrue(any('промышлен' in x for x in issues))
        self.assertTrue(any('долговечн' in x for x in issues))

    def test_flags_partial_ambient_range(self):
        p=app.validate_input({'name':'датчик М1','model':'М1','description':'Датчик температуры.', 'specs':{'Температура окружающего воздуха':'−60…+85 °C (по таблице серии)'}})
        d={**GOOD,'description':'Модель М1. Температура окружающего воздуха не превышает +85 °C. '+'А'*800}
        issues,_=app.assess(d,p)
        self.assertTrue(any('только часть диапазона' in x for x in issues))

    def test_flags_unsupported_claim_about_passport(self):
        p=app.validate_input({'name':'регулятор','description':'Сведения требуют уточнения по паспорту.', 'conflicts':['Источники расходятся.']})
        d={**GOOD,'commercial':'В паспорте и на сайте продавца условия различаются.'}
        issues,_=app.assess(d,p)
        self.assertTrue(any('не подтверждено содержимое паспорта' in x for x in issues))

    def test_native_valid_model_response(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps({'done_reason':'stop','message':{'content':json.dumps(GOOD)}}).encode()
        with patch.dict(os.environ,{'LLM_BACKEND':'ollama'}), patch.object(app.urllib.request,'urlopen',return_value=Resp()):
            result=app.call_model(self.product)
        self.assertEqual(result['title'],GOOD['title'])
        self.assertEqual(result['queries'],GOOD['queries'])

    def test_native_ollama_bounds_context_and_unloads_model(self):
        captured={}
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps({'done_reason':'stop','message':{'content':json.dumps({'ok':True})}}).encode()
        def fake(req,timeout):
            captured['url']=req.full_url
            captured['body']=json.loads(req.data)
            captured['headers']=dict(req.header_items())
            return Resp()
        with patch.dict(os.environ,{'OLLAMA_CONTEXT_SIZE':'3072','LLM_MODEL':'model','LLM_API_KEY':'secret'}), patch.object(app.urllib.request,'urlopen',side_effect=fake):
            result=app.ollama_native_json([{'role':'user','content':'данные'}],300)
        self.assertEqual(result,{'ok':True})
        self.assertEqual(captured['body']['options']['num_ctx'],3072)
        self.assertEqual(captured['body']['keep_alive'],0)
        self.assertNotIn('Authorization',captured['headers'])
        self.assertTrue(captured['url'].endswith('/api/chat'))

    def test_native_records_near_context_limit_without_prompt_text(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps({'done_reason':'stop','prompt_eval_count':3000,'eval_count':12,'message':{'content':'{}'}}).encode()
        app.REQUEST_METRICS.clear()
        with patch.dict(os.environ,{'OLLAMA_CONTEXT_SIZE':'3072'}), patch.object(app.urllib.request,'urlopen',return_value=Resp()):
            app.ollama_native_json([{'role':'user','content':'confidential'}],2048)
        self.assertTrue(app.REQUEST_METRICS[-1]['near_context_limit'])
        self.assertNotIn('confidential',str(app.REQUEST_METRICS))

    def test_native_non_object_response_is_handled(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'[]'
        with patch.object(app.urllib.request,'urlopen',return_value=Resp()), self.assertRaises(app.ModelFormatError):
            app.ollama_native_json([],100)

    def test_native_truncated_output_is_not_accepted(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps({'done_reason':'length','message':{'content':'{}'}}).encode()
        with patch.object(app.urllib.request,'urlopen',return_value=Resp()), self.assertRaises(app.ModelFormatError):
            app.ollama_native_json([],100)

    def test_unknown_backend_is_rejected(self):
        with patch.dict(os.environ,{'LLM_BACKEND':'ollmaa'}),self.assertRaises(app.InputError):
            app.selected_backend()

    def test_flags_overbroad_aggressive_media_condition(self):
        p=app.validate_input({'name':'датчик','description':'Для сред, неагрессивных к защитной арматуре и чувствительному элементу.'})
        d={**GOOD,'commercial':'Не подходит для измерений в агрессивных средах.'}
        issues,_=app.assess(d,p)
        self.assertTrue(any('слишком широкое' in issue for issue in issues))

    def test_common_series_qualifiers_are_recognized(self):
        self.assertTrue(app.is_series_value('−60…+85 °C (по таблице серии)'))
        self.assertTrue(app.is_series_value('IP54 (по данным серии)'))
        self.assertTrue(app.is_series_value('IP54: данные серии'))
        self.assertFalse(app.is_series_value('IP54'))

    def test_series_qualifier_is_added_and_change_recorded(self):
        p=app.validate_input({'name':'датчик','specs':{'Температура окружающего воздуха':'−60…+85 °C (по таблице серии)'}})
        d={'description':'Датчик измеряет температуру.','commercial':'Окружающий воздух от −60 до +85 °C.'}
        changes=app.add_series_qualifiers(d,p)
        self.assertIn('по данным серии',d['commercial'])
        self.assertEqual(changes[0]['source_fields'],['specs.Температура окружающего воздуха'])
        self.assertNotIn('по данным серии',changes[0]['original'])
        self.assertIn('по данным серии',changes[0]['result'])

    def test_series_qualifier_not_added_to_unrelated_numbers(self):
        p=app.validate_input({'name':'датчик','specs':{'Температура окружающего воздуха':'−60…+85 °C (по таблице серии)'}})
        d={'description':'Давление среды от −60 до +85 единиц.','commercial':'Область применения уточнить.'}
        self.assertEqual(app.add_series_qualifiers(d,p),[])

    def test_series_qualifier_not_added_when_no_match(self):
        p=app.validate_input({'name':'датчик','specs':{'Температура окружающего воздуха':'−60…+85 °C (по таблице серии)'}})
        d={'description':'Диапазон от −10 до +30 °C.','commercial':'Область применения уточнить.'}
        self.assertEqual(app.add_series_qualifiers(d,p),[])

    def test_quarantines_only_overbroad_media_restriction(self):
        p=app.validate_input({'name':'датчик','description':'Для сред, неагрессивных к защитной арматуре и чувствительному элементу.'})
        d={'description':'Назначение описано.','commercial':'Среда неагрессивна к арматуре. Не подходит для агрессивных сред.'}
        removed=app.quarantine_overbroad_media(d,p)
        self.assertEqual(len(removed),1)
        self.assertNotIn('Не подходит',d['commercial'])
        self.assertIn('Не подходит',removed[0]['text'])

    def test_pipeline_records_quarantine_and_preserves_raw_model_response(self):
        p=app.validate_input({'name':'датчик М1','model':'М1','description':'Для сред, неагрессивных к защитной арматуре и чувствительному элементу.'})
        draft={**GOOD,'commercial':'Среда неагрессивна к арматуре и чувствительному элементу. Не подходит для агрессивных сред.'}
        with patch.dict(os.environ,{'LLM_MAX_ATTEMPTS':'1'}), patch.object(app,'call_model',return_value=draft):
            result=app.generate(p)
        self.assertIn('Не подходит',result['raw_generation']['commercial'])
        self.assertNotIn('Не подходит',result['commercial'])
        self.assertEqual(result['review']['quarantined_claims'][0]['field'],'commercial')

    def test_does_not_quarantine_specific_media_condition(self):
        p=app.validate_input({'name':'датчик','description':'Для сред, неагрессивных к защитной арматуре и чувствительному элементу.'})
        text='Не подходит для агрессивных сред к защитной арматуре и чувствительному элементу.'
        d={'description':'Назначение описано.','commercial':text}
        self.assertEqual(app.quarantine_overbroad_media(d,p),[])
        self.assertEqual(d['commercial'],text)

    def test_flags_unwarranted_bound_for_poll_time(self):
        p=app.validate_input({'name':'регулятор М1','model':'М1','specs':{'Время опроса одного входа':'0,3 с'}})
        d={**GOOD,'description':'М1. Время опроса не превышает 0,3 с. '+'А'*800}
        issues,_=app.assess(d,p)
        self.assertTrue(any('неподтверждённое условие' in x for x in issues))

    def test_flags_humidity_missing_no_condensation(self):
        p=app.validate_input({'name':'регулятор М1','model':'М1','specs':{'Относительная влажность':'не более 80% при +25 °C и ниже без конденсации влаги'}})
        d={**GOOD,'description':'М1. Влажность не более 80% при +25 °C. '+'А'*800}
        issues,_=app.assess(d,p)
        self.assertTrue(any('отсутствия конденсации' in x for x in issues))

    def test_flags_humidity_missing_lower_temperature_condition(self):
        p=app.validate_input({'name':'регулятор М1','model':'М1','specs':{'Относительная влажность':'не более 80% при +25 °C и более низких температурах без конденсации влаги'}})
        d={**GOOD,'description':'М1. Влажность не более 80% при +25 °C без конденсации. '+'А'*800}
        issues,_=app.assess(d,p)
        self.assertTrue(any('более низких температур' in x for x in issues))

    def test_unknown_profile_remains_explicit(self):
        p=app.validate_input({'name':'Неизвестный прибор'})
        profile,_,missing=app.missing_data(p)
        self.assertEqual(profile,'other')
        self.assertTrue(any(x['field']=='profile' for x in missing))

if __name__=='__main__': unittest.main()
