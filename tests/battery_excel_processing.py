import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import datetime, random, re, zipfile

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import openpyxl
from utils import excel_processing as ep
from utils import text_processing as tp

WORK = env.tmpdir('excel_')
def path(name): return os.path.join(WORK, name)
def make_xlsx(name, rows, extra_sheets=None, formulas=False):
    wb = openpyxl.Workbook(); ws = wb.active
    for row in rows: ws.append(row)
    for title, sheet_rows in (extra_sheets or {}).items():
        sh = wb.create_sheet(title)
        for row in sheet_rows: sh.append(row)
    p = path(name); wb.save(p); return p

# ===================== чтение строк =====================
p = make_xlsx('basic.xlsx', [['Болт', 12, 3.5, None, '  пробелы  '], [None, None], ['', '   '], [datetime.datetime(2026, 10, 7), True, 'ост. 5 шт']])
rows = ep.read_excel_rows(p)
check('строка листа — одна строка текста: непустые ячейки через « | », пробелы по краям срезаны, пустые ячейки пропущены', rows[0] == 'Болт | 12 | 3.5 | пробелы', str(rows))
check('полностью пустые строки и строки из одних пробелов пропускаются', len(rows) == 2)
check('даты и логические значения превращаются в текст (2026-10-07 00:00:00, True)', rows[1] == '2026-10-07 00:00:00 | True | ост. 5 шт', rows[1])
check('кириллица читается как есть', ep.read_excel_rows(make_xlsx('cyr.xlsx', [['Номенклатура', 'Ёж', 'Щётка']])) == ['Номенклатура | Ёж | Щётка'])
check('только ПЕРВЫЙ лист (остальные игнорируются)', ep.read_excel_rows(make_xlsx('two.xlsx', [['первый лист']], {'Второй': [['второй лист']]})) == ['первый лист'])
check('пустой лист — нет строк, текст пустой', ep.read_excel_rows(make_xlsx('empty.xlsx', [])) == [] and ep.read_excel_as_text(path('empty.xlsx')) == '')
check('read_excel_as_text: строки через перевод строки (по одной на топик)', ep.read_excel_as_text(p) == '\n'.join(rows))

# фильтр «исключить строки»
p = make_xlsx('filter.xlsx', [['Болт', 'акция'], ['Гайка', 'обычная'], ['Шайба', 'Акция'], ['Винт', 'ост. 5']])
check('exclude_substring: строки, содержащие подстроку, исключаются (регистр важен: «Акция» не исключена)', ep.read_excel_rows(p, 'акция') == ['Гайка | обычная', 'Шайба | Акция', 'Винт | ост. 5'])
check('пробелы вокруг подстроки срезаются; пустая подстрока и None — без фильтра', ep.read_excel_rows(p, '  акция  ') == ep.read_excel_rows(p, 'акция') and len(ep.read_excel_rows(p, '')) == 4 and len(ep.read_excel_rows(p, None)) == 4)
check('(особенность) подстрока ищется в УЖЕ склеенной строке — «Гайка | обычная» исключается и по « | » между ячейками', ep.read_excel_rows(p, 'Гайка | обычная') == ['Болт | акция', 'Шайба | Акция', 'Винт | ост. 5'])
check('read_excel_as_text применяет тот же фильтр', ep.read_excel_as_text(p, 'акция') == 'Гайка | обычная\nШайба | Акция\nВинт | ост. 5')

# ошибки и ресурсы
for label, target in (('нет файла', path('нет_такого.xlsx')),):
    try: ep.read_excel_rows(target); err = None
    except Exception as e: err = type(e).__name__
    check(f'{label}: исключение FileNotFoundError (вызывающий код показывает ошибку)', err == 'FileNotFoundError', str(err))
open(path('notxlsx.xlsx'), 'wb').write('это не xlsx'.encode('utf-8'))
try: ep.read_excel_rows(path('notxlsx.xlsx')); err = None
except Exception as e: err = type(e).__name__
check('файл не в формате xlsx: исключение, а не пустой результат', err is not None, str(err))
p = make_xlsx('close.xlsx', [['а', 'б']]); ep.read_excel_rows(p)
try: os.remove(p); removed = True
except OSError: removed = False
check('файл закрыт после чтения: его можно удалить (на Windows незакрытая книга блокирует файл)', removed)

# формулы
wbf = openpyxl.Workbook(); wsf = wbf.active; wsf.append(['=1+2', '=SUM(A1:A1)']); wsf.append(['Итого', '=1+2']); pf = path('formula.xlsx'); wbf.save(pf)
check('(ограничение) читаются СОХРАНЁННЫЕ значения формул: файл, записанный программой без пересчёта в Excel, даёт пустые ячейки — строка из одних формул пропадает',
      ep.read_excel_rows(pf) == ['Итого'], str(ep.read_excel_rows(pf)))

# свойство
rnd = random.Random(31); ok_rows = True
for i in range(60):
    grid = [[rnd.choice([None, '', ' ', 'слово', 'Ёж ёж', 'abc', 7, 3.5, ' пробел ']) for _ in range(rnd.randint(1, 5))] for _ in range(rnd.randint(1, 8))]
    expected = []
    for row in grid:
        parts = [str(v).strip() for v in row if v is not None and str(v).strip()]
        if parts: expected.append(' | '.join(parts))
    ok_rows &= ep.read_excel_rows(make_xlsx(f'rnd{i}.xlsx', grid)) == expected
check('свойство (60 случайных таблиц): результат = непустые строки, непустые ячейки через « | »', ok_rows)

# известные ошибки
p_ok = make_xlsx('dim.xlsx', [[f'строка {i}', i * 10] for i in range(1, 8)])
p_bad = path('dim_bad.xlsx')
with zipfile.ZipFile(p_ok) as zin, zipfile.ZipFile(p_bad, 'w', zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == 'xl/worksheets/sheet1.xml':
            data = re.sub(r'<dimension ref="[^"]+"/>', '<dimension ref="A1"/>', data.decode('utf-8')).encode('utf-8')
        zout.writestr(item, data)
check('исправный файл: все 7 строк', len(ep.read_excel_rows(p_ok)) == 7)
got = ep.read_excel_rows(p_bad)
check('файл с неверной «размерностью» листа (A1 вместо A1:B7 — так пишут некоторые программы) читается ЦЕЛИКОМ, а не одной строкой', len(got) == 7,
            f'прочитано {len(got)} из 7 строк — остальные молча пропали из индекса')
p_nl = make_xlsx('newline.xlsx', [['Болт М12', 'Оцинкованный\nс шайбой', 150], ['Гайка М12', 'без покрытия', 30]])
nl_rows = ep.read_excel_rows(p_nl)
topics = tp.split_into_sections_by_separator(ep.read_excel_as_text(p_nl).split('\n'), 'ExcelRow1')
check('ячейка с переносом строки (Alt+Enter) не превращает одну строку таблицы в несколько топиков (строка листа = один топик)', len(topics) == 2 and all('\n' not in r for r in nl_rows),
            f"строк листа 2, топиков {len(topics)}: {[s['title'] for s in topics]}")
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
