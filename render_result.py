#!/usr/bin/env python3
"""Render a saved result for a content manager. Does not call or edit the LLM."""
import argparse
import html
import json
import re
import sys


def text(value):
    if not isinstance(value, str):
        raise ValueError('Текстовые поля результата должны быть строками.')
    value = html.escape(value, quote=False)
    return re.sub(r'([\\`*_{}\[\]#|])', r'\\\1', value).replace('\n', ' ')


def render_markdown(result):
    if not isinstance(result, dict):
        raise ValueError('Ожидается JSON-объект результата программы.')
    lines = ['# Черновик карточки товара', '',
             '> Требуется проверка человеком перед публикацией.', '']
    for key, label in [('title', 'SEO-заголовок'), ('description', 'SEO-описание')]:
        lines.extend(['## ' + label, '', text(result[key]), ''])
    lines.extend(['## Характеристики', '', '| Параметр | Значение |', '|---|---|'])
    for key, value in result['characteristics'].items():
        lines.append(f'| {text(key)} | {text(value)} |')
    lines.extend(['', '## Поисковые запросы', ''])
    lines.extend('- ' + text(q) for q in result['queries'])
    lines.extend(['', '## Для менеджера', '', text(result['commercial']), '',
                  '## Что уточнить', ''])
    missing = result['missing_fields']
    if missing:
        lines.extend('- ' + text(item['field']) + ': ' + text(item['reason']) for item in missing)
    else:
        lines.append('Автоматически не обнаружено пустых обязательных полей. Данные серии сверить с паспортом конкретного исполнения.')
    review = result['review']
    warnings = list(review['automated_issues']) + list(review.get('context_warnings', []))
    for key in ('audit_error', 'last_format_error'):
        if review.get(key): warnings.append(review[key])
    lines.extend(['', '## Проверка', '',
                  f'Заголовок: {len(result["title"])} символов. Описание: {len(result["description"])} символов с пробелами. Запросов: {len(result["queries"])}.', ''])
    if warnings:
        lines.extend('- ' + text(w) for w in dict.fromkeys(warnings))
    else:
        lines.append('Автоматических замечаний нет. Это не подтверждает отсутствие смысловых ошибок.')
    lines.extend(['', 'Представление сформировано из JSON без редактирования текста карточки. Исходный ответ модели, программные изменения и источники сохранены в полном JSON.', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Показать сохранённый результат в Markdown без запуска модели')
    parser.add_argument('input', help='JSON результата app.py, не исходный JSON товара')
    args = parser.parse_args()
    try:
        with open(args.input, encoding='utf-8') as stream:
            result = json.load(stream)
        print(render_markdown(result), end='')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f'Ошибка формата результата: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
