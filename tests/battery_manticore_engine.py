import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import contextlib, io, re, types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

try:
    import pymysql
except ImportError:
    pymysql = types.ModuleType('pymysql'); pymysql.connect = lambda **k: None; sys.modules['pymysql'] = pymysql
import engines.manticore_engine as me

# Данные и поиск Manticore. Сервера нет: вместо него небольшой «SQL-сервер» в памяти, который понимает ровно те запросы, что отправляет
# движок (SHOW/CREATE/DROP TABLE, INSERT пачками с экранированием, SELECT по id, постраничное чтение, MAX(id), MATCH-поиск), и может
# отказывать по заданию. По нему видно, что реально записано в таблицы, а не только какие запросы ушли.
from tests.fake_manticore import Server, Cursor, Conn

def engine(tables=None, current='idx', file_name='книга.txt', search_limit=200, with_conn=True):
    srv = Server(tables); e = me.ManticoreEngine.__new__(me.ManticoreEngine)
    e.conn = Conn(srv) if with_conn else None; e.cursor = Cursor(srv) if with_conn else None; e._current_index = current; e.index = current; e._current_file_name = file_name
    e.default_separator = 'ExcelRow1'; e.search_limit = search_limit; return e, srv
def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()) as out: r = fn(*a, **k)
    return r, out.getvalue()
def stored(srv, name='idx'): return [(rid, *row) for rid, row in sorted(srv.tables[name].items())]
def inserts(srv): return [s for s in srv.sql if s.lstrip().startswith('INSERT')]

# ===================== A. экранирование =====================
e, _ = engine()
check('_escape_ident: имя в обратных кавычках, кавычки в имени удваиваются, пустое имя — ``', e._escape_ident('книга') == '`книга`' and e._escape_ident('a`b') == '`a``b`' and e._escape_ident('') == '``' and e._escape_ident(None) == '``')
check('_escape_string: через соединение (как у драйвера); None — пустая строка', e._escape_string("он сказал: \"О'Брайен\"\n") == "он сказал: \\\"О\\'Брайен\\\"\\n" and e._escape_string(None) == '')
e, _ = engine(with_conn=False); check('_escape_string без соединения: удваивает кавычки и обратные косые', e._escape_string("a'b\\c") == "a''b\\\\c")
# ===================== B. список, выбор, создание, удаление =====================
e, srv = engine(with_conn=False); check('list_indices без соединения — пустой список', e.list_indices() == [])
e, srv = engine({'книга': {}, '.служебный': {}, 'ещё': {}}); check('list_indices: служебные таблицы (имя с точки) не показываются', sorted(e.list_indices()) == ['ещё', 'книга'])
e, srv = engine({'a': {}}); srv.fail_when = lambda s: s.startswith('SHOW'); r, out = quiet(e.list_indices); check('list_indices: сбой сервера — пустой список с причиной в консоли, исключения нет', r == [] and 'Ошибка получения списка индексов' in out)
e, srv = engine({'книга': {}}, current=None); check('select_index: существующий индекс становится выбранным', e.select_index('книга') is True and e.index == 'книга' and e._current_index == 'книга')
check('select_index: нет такого индекса — False, выбор не меняется', e.select_index('нет') is False and e.index == 'книга')
e, srv = engine(with_conn=False)
try: e.create_index('x'); raised = None
except Exception as ex: raised = str(ex)
check('create_index без соединения — «Нет соединения с Manticore»', raised == 'Нет соединения с Manticore')
e, srv = engine({}, current=None); r, _ = quiet(e.create_index, 'новый')
check('create_index: таблица создаётся со схемой (id, section_id, section_text, file_name, position), RT, инфиксы от 2 символов; индекс становится выбранным', 'новый' in srv.tables and any("type='rt'" in s and "min_infix_len='2'" in s and 'section_text text' in s for s in srv.sql) and e.index == 'новый' and e._current_index == 'новый')
e, srv = engine({'Книга': {1: ('т', 'ф', '0')}}); quiet(e.create_index, 'книга')
check('create_index: индекс уже есть (без учёта регистра) — удаляется ПОД ЕГО НАСТОЯЩИМ именем и создаётся заново пустым', list(srv.tables) == ['книга'] and srv.tables['книга'] == {} and any(s.strip().startswith('DROP TABLE `Книга`') for s in srv.sql), str(srv.sql))
e, srv = engine({}, current=None); quiet(e.create_index, 'a`b'); check('create_index: обратная кавычка в имени экранируется', 'a`b' in srv.tables)
e, srv = engine({}); srv.fail_when = lambda s: s.lstrip().startswith('CREATE')
try: quiet(e.create_index, 'x'); raised = None
except RuntimeError as ex: raised = str(ex)
check('create_index: сервер отказал — исключение пробрасывается (вызывающий покажет ошибку), выбор индекса не меняется', raised == 'сервер отказал' and e.index == 'idx')
e, srv = engine({'a': {}, 'b': {}}, current='a'); r, _ = quiet(e.delete_index, 'a')
check('delete_index: таблица удалена; если это был выбранный индекс — выбор сбрасывается', r is True and list(srv.tables) == ['b'] and e._current_index is None and e.index is None)
e, srv = engine({'a': {}, 'b': {}}, current='a'); quiet(e.delete_index, 'b'); check('delete_index: другой индекс — выбор не трогается', e._current_index == 'a' and e.index == 'a')
e, srv = engine({}); r, out = quiet(e.delete_index, 'нет'); check('delete_index: нет такой таблицы — False с причиной, исключения нет', r is False and 'Ошибка удаления индекса' in out)
e, srv = engine(with_conn=False); check('delete_index без соединения — False', e.delete_index('x') is False)

# ===================== C. запись текста (index_text) =====================
def text_of(n): return '\n'.join(f'строка {i}' for i in range(n))
e, srv = engine({}, current=None)
try: e.index_text('текст'); raised = None
except Exception as ex: raised = str(ex)
check('index_text: индекс не выбран — «Индекс не выбран.»', raised == 'Индекс не выбран.')
e, srv = engine({'idx': {}}); r, _ = quiet(e.index_text, 'раз\nдва\nтри', 'ExcelRow1')
check('index_text: строки таблицы — id и section_id с 1, текст секции, имя файла, позиция (номер строки начала); возвращается число вставленных', r == 3 and stored(srv) == [(1, 'раз', 'книга.txt', '0'), (2, 'два', 'книга.txt', '1'), (3, 'три', 'книга.txt', '2')], str(stored(srv)))
e, srv = engine({'idx': {}}); r, _ = quiet(e.index_text, 'aaaa bbbb cccc dddd', 'N10')
check('index_text: разделитель N10 режет текст на блоки по ~10 СИМВОЛОВ, не разрывая слов; позиция — номер строки начала блока', r == 2 and [(x[1], x[3]) for x in stored(srv)] == [('aaaa bbbb', '0'), ('cccc dddd', '0')], str(stored(srv)))
e, srv = engine({'idx': {}}); e.default_separator = 'ExcelRow1'; quiet(e.index_text, 'раз\nдва'); check('index_text: разделитель не задан — по умолчанию движка (здесь «одна строка — один топик»)', len(srv.tables['idx']) == 2)
tricky = "О'Брайен сказал: \"привет\\мир\"\tи\x00ушёл"
e, srv = engine({'idx': {}}, file_name="кн'ига.txt"); quiet(e.index_text, tricky, 'ExcelRow1')
check('index_text: кавычки, обратные косые, табуляция, нулевой символ и кавычка в имени файла записываются без искажений (экранирование)', stored(srv) == [(1, tricky, "кн'ига.txt", '0')], str(stored(srv)))
e, srv = engine({'idx': {}}, file_name=None); quiet(e.index_text, 'раз', 'ExcelRow1')
check('index_text: имя файла не задано — «indexed_file»', stored(srv)[0][2] == 'indexed_file' and e._current_file_name == 'indexed_file')
e, srv = engine({'idx': {}}); quiet(e.index_text, text_of(450), 'ExcelRow1')
check('index_text: 450 секций — три пакета (200 + 200 + 50), все 450 строк в таблице', len(inserts(srv)) == 3 and len(srv.tables['idx']) == 450 and sorted(srv.tables['idx']) == list(range(1, 451)))
check('index_text: на время записи автофиксация выключается, потом включается; записанное фиксируется', srv.autocommit_log == [False, True] and srv.commits == 1, str((srv.autocommit_log, srv.commits)))
e, srv = engine({'idx': {}}); r, out = quiet(e.index_text, '', 'ExcelRow1')
check('index_text: пустой текст — 0, ни одной записи и ни одного запроса записи, автофиксация не трогается', r == 0 and not inserts(srv) and srv.autocommit_log == [] and 'Не найдено топиков' in out)
calls = []; e, srv = engine({'idx': {}}); quiet(e.index_text, text_of(450), 'ExcelRow1', lambda done, total: calls.append((done, total)))
check('index_text: прогресс — после пакетов, кратных сотне, и в конце всегда (450, 450)', calls[-1] == (450, 450) and calls[0] == (200, 450) and all(t == 450 for _d, t in calls), str(calls))
# отказ отдельного пакета
def fail_second_batch(srv):
    n = [0]
    def rule(s):
        if s.lstrip().startswith('INSERT') and s.count("', '") > 10:     # пакет, а не одиночная строка
            n[0] += 1; return n[0] == 2
        return False
    srv.fail_when = rule
e, srv = engine({'idx': {}}); fail_second_batch(srv); r, out = quiet(e.index_text, text_of(1000), 'ExcelRow1')
check('второй пакет не принят: его строки досылаются по одной — в таблице есть строки первого и второго пакетов', all(i in srv.tables['idx'] for i in range(1, 401)), f'{len(srv.tables["idx"])} строк')
check('после отказа одного пакета следующие пакеты всё равно записываются: в таблице все 1000 секций, функция возвращает 1000 (раньше после построчной досылки цикл обрывался — книга молча обрезалась)', r == 1000 and len(srv.tables['idx']) == 1000 and sorted(srv.tables['idx']) == list(range(1, 1001)), f'возвращено {r}, в таблице {len(srv.tables["idx"])}')
e, srv = engine({'idx': {}}); bad = ('строка 5', 'строка 250')
srv.fail_when = lambda s: s.lstrip().startswith('INSERT') and any(f"'{b}'" in s for b in bad)
r, out = quiet(e.index_text, text_of(300), 'ExcelRow1')
check('отдельная «плохая» секция (отказ и пакета, и построчной досылки) пропускается, остальные записываются: из 300 секций записаны 298, возвращается 298', r == 298 and 6 not in srv.tables['idx'] and 7 in srv.tables['idx'] and 251 not in srv.tables['idx'] and 252 in srv.tables['idx'] and len(srv.tables['idx']) == 298, f'возвращено {r}, в таблице {len(srv.tables["idx"])}')
e, srv = engine({'idx': {}}); e.conn.escape_fails_on = 'строка 3'
try: quiet(e.index_text, text_of(10), 'ExcelRow1'); raised = None
except RuntimeError as ex: raised = str(ex)
check('неожиданный сбой посреди записи (не ошибка сервера) не оставляет автофиксацию выключенной', raised == 'не удалось экранировать' and srv.autocommit_log and srv.autocommit_log[-1] is True, f'автофиксация: {srv.autocommit_log}')
# ===================== D. index_file =====================
WORK = env.tmpdir('mcengine_')
def write_bytes(name, data): p = os.path.join(WORK, name); open(p, 'wb').write(data); return p
e, srv = engine({'idx': {}}, file_name=None); seen = []; orig = e.index_text; e.index_text = lambda *a, **k: (seen.append(e._current_file_name), orig(*a, **k))[1]
r, _ = quiet(e.index_file, write_bytes('юникод.txt', 'раз\nдва'.encode('utf-8')), 'ExcelRow1')
check('index_file: файл в utf-8 — читается; на время записи имя файла = имя без пути, потом сбрасывается', r == 2 and seen == ['юникод.txt'] and e._current_file_name is None and stored(srv)[0][2] == 'юникод.txt', str(seen))
e, srv = engine({'idx': {}}, file_name=None); quiet(e.index_file, write_bytes('вин.txt', 'привет\nмир'.encode('cp1251')), 'ExcelRow1')
check('index_file: файл в cp1251 — переключается на cp1251', [x[1] for x in stored(srv)] == ['привет', 'мир'], str(stored(srv)))
e, srv = engine({'idx': {}}, file_name=None); r, out = quiet(e.index_file, write_bytes('мусор.txt', b'\xff\xfe\x98 abc\nxyz'), 'ExcelRow1')
check('index_file: файл, который не читается ни в utf-8, ни в cp1251, читается как latin-1 (последняя кодировка, которая не отказывает)', r == 2 and 'Кодировка: latin-1' in out, out[:200])
# ===================== E. чтение секций =====================
T = {'idx': {1: ('первый', 'a.txt', '0'), 2: ('второй', None, None)}}
e, srv = engine(T); check('get_section_text: текст по rowid; нет строки — None', e.get_section_text(1) == 'первый' and e.get_section_text(99) is None)
e, srv = engine(T, current=None); check('get_section_text и get_section_info без выбранного индекса — None', e.get_section_text(1) is None and e.get_section_info(1) is None)
e, srv = engine(T); check('get_section_info: текст, файл, позиция; пустое имя файла — «», нет позиции — «0»; нет строки — None', e.get_section_info(1) == {'text': 'первый', 'file_name': 'a.txt', 'position': '0'} and e.get_section_info(2) == {'text': 'второй', 'file_name': '', 'position': '0'} and e.get_section_info(99) is None)
e, srv = engine({'a': {1: ('из a', 'f', '3')}, 'b': {1: ('из b', 'g', '4')}}, current='a'); check('get_section_info_from: берёт строку из УКАЗАННОГО индекса, а не текущего', e.get_section_info_from('b', 1)['text'] == 'из b' and e.get_section_info(1)['text'] == 'из a')
e, srv = engine(T); srv.fail_when = lambda s: 'WHERE id' in s; r, out = quiet(e.get_section_info_from, 'idx', 1); check('чтение секции: сбой сервера — None с причиной в консоли', r is None and 'Ошибка получения информации о топике' in out and quiet(e.get_section_text, 1)[0] is None)
big = {'idx': {i: (f'т{i}', 'ф' if i % 2 else None, '0') for i in range(1, 1201)}}
e, srv = engine(big); rows = e.get_all_sections('idx')
check('get_all_sections: 1200 строк читаются постранично (по 500) — приходят ВСЕ, по возрастанию id, пустое имя файла — «»', [r[0] for r in rows] == list(range(1, 1201)) and rows[1][2] == '' and len([s for s in srv.sql if s.startswith('SELECT id')]) in (3, 4), f'{len(rows)} строк, запросов {len([s for s in srv.sql if s.startswith("SELECT id")])}')
rows2 = engine({'idx': {i: ('т', 'ф', '0') for i in range(1, 1501)}})[0].get_all_sections('idx', batch_size=2000)
check('get_all_sections: даже если вызвать с размером пакета больше предела сервера (2000 при пределе 1000), прочитаются ВСЕ 1500 строк, а не первая тысяча', len(rows2) == 1500, f'прочитано {len(rows2)}')
e, srv = engine({'idx': {i: ('т', 'ф', '0') for i in range(1, 501)}}); rows = e.get_all_sections('idx'); check('get_all_sections: ровно кратное размеру пакета число строк — лишний пустой запрос и полный результат', len(rows) == 500)
e, srv = engine({'idx': {}}); check('get_all_sections: пустой индекс — []', e.get_all_sections('idx') == [])
e, srv = engine({'idx': {i: ('т', 'ф', '0') for i in range(1, 1201)}}); n = [0]; srv.fail_when = lambda s: (n.__setitem__(0, n[0] + 1), n[0] == 2)[1]
rows, out = quiet(e.get_all_sections, 'idx'); check('get_all_sections: сбой посреди чтения — возвращается прочитанное к этому моменту, с причиной в консоли', len(rows) == 500 and 'Ошибка получения топиков индекса' in out, str(len(rows)))
# ===================== F. вспомогательные индексы «окон смысла» =====================
e, srv = engine(with_conn=False)
for name, call in (('ensure_chunk_index', lambda: e.ensure_chunk_index('x')), ('insert_chunks', lambda: e.insert_chunks('x', ['а'], 'ф'))):
    try: call(); raised = None
    except Exception as ex: raised = str(ex)
    check(f'{name} без соединения — «Нет соединения с Manticore»', raised == 'Нет соединения с Manticore')
e, srv = engine({}); r = e.ensure_chunk_index('model_x'); check('ensure_chunk_index: нет индекса — создаётся (True); выбранный индекс программы не меняется', r is True and 'model_x' in srv.tables and e.index == 'idx' and e._current_index == 'idx')
e, srv = engine({'Model_X': {1: ('т', 'ф', '0')}}); r = e.ensure_chunk_index('model_x'); check('ensure_chunk_index: уже есть (без учёта регистра) и пересоздавать не просят — False, данные целы', r is False and srv.tables['Model_X'] == {1: ('т', 'ф', '0')})
r = e.ensure_chunk_index('model_x', drop_if_exists=True); check('ensure_chunk_index(drop_if_exists=True): удаляется под настоящим именем и создаётся заново пустым (True)', r is True and list(srv.tables) == ['model_x'] and srv.tables['model_x'] == {})
e, srv = engine({'m': {}}); r = e.insert_chunks('m', ['один', "два'три", 'четыре'], "ф'айл.txt")
check('insert_chunks: куски записываются с id с 1, имя файла и позиция «0», экранирование соблюдается; возвращается число', r == 3 and stored(srv, 'm') == [(1, 'один', "ф'айл.txt", '0'), (2, "два'три", "ф'айл.txt", '0'), (3, 'четыре', "ф'айл.txt", '0')], str(stored(srv, 'm')))
r = e.insert_chunks('m', ['пять', 'шесть'], 'ф'); check('insert_chunks: следующая вставка продолжает нумерацию с MAX(id)+1 (дообучение ДОБАВЛЯЕТ, а не перезаписывает)', r == 2 and [x[0] for x in stored(srv, 'm')] == [1, 2, 3, 4, 5], str([x[0] for x in stored(srv, 'm')]))
check('insert_chunks: пустой список — 0 без запросов', engine({'m': {}})[0].insert_chunks('m', [], 'ф') == 0)
e, srv = engine({'m': {}}); e.insert_chunks('m', [f'т{i}' for i in range(450)], 'ф'); check('insert_chunks: пакеты по 200, фиксация одна, автофиксация выключается и включается', len(inserts(srv)) == 3 and srv.commits == 1 and srv.autocommit_log == [False, True] and len(srv.tables['m']) == 450)
e, srv = engine({'m': {}}); n = [0]; srv.fail_when = lambda s: s.lstrip().startswith('INSERT') and (n.__setitem__(0, n[0] + 1) or n[0] == 2)
try: quiet(e.insert_chunks, 'm', [f'т{i}' for i in range(450)], 'ф'); raised = None
except RuntimeError as ex: raised = str(ex)
check('insert_chunks: сбой пакета — исключение пробрасывается, автофиксация всё равно включается обратно', raised == 'сервер отказал' and srv.autocommit_log[-1] is True)
e, srv = engine({}); r = engine({'m': {}})[0]; e2, srv2 = engine({'m': {}}); srv2.fail_when = lambda s: s.startswith('SELECT MAX'); r = e2.insert_chunks('m', ['а'], 'ф'); check('insert_chunks: не удалось узнать MAX(id) — нумерация с 1', r == 1 and list(srv2.tables['m']) == [1])
# ===================== G. поиск =====================
DOC = {'idx': {1: ('Бог создал небо и землю', 'a.txt', '0'), 2: ('небо и звёзды над землёй', 'a.txt', '5'), 3: ('совсем другой текст', 'b.txt', '9')}}
e, srv = engine(DOC); res, _ = quiet(e.search, 'небо')
check('search: находит топики со словом; в результате — rowid, текст, мета-данные совпадений, имя файла и позиция', sorted(r['rowid'] for r in res) == [1, 2] and all(set(r) == {'rowid', 'content', 'meta', 'file_name', 'position'} for r in res) and res[0]['file_name'] == 'a.txt', str(res))
e, srv = engine(DOC); quiet(e.search, 'небо земля')
sql = ' '.join(srv.sql[-1].split())
check('search: запрос к серверу — по полю section_text, слова через « | » с инфиксом *слово*, LIMIT из настройки, ранжирование bm25 с весом поля', "MATCH('@(section_text) *небо* | *земля*')" in sql and 'LIMIT 200' in sql and 'ranker=bm25, field_weights=(section_text=10)' in sql and 'FROM `idx`' in sql, sql)
e, srv = engine(DOC, search_limit=7); quiet(e.search, 'небо'); check('search: предел выдачи — настройка manticore_search_limit', 'LIMIT 7' in srv.sql[-1])
e, srv = engine({'a': {1: ('общее слово', 'x', '0')}, 'b': {1: ('общее слово тут', 'y', '0')}}, current='a'); res, _ = quiet(e.search, 'слово', indices=['a', 'b'])
check('search: несколько индексов — один запрос по всем (FROM `a`, `b`); результаты из обоих', ' '.join(srv.sql[-1].split()).count('FROM `a`, `b`') == 1 and {r['file_name'] for r in res} == {'x', 'y'}, str(res))
e, srv = engine({'a': {1: ('слово', 'x', '0')}}, current='a'); res, _ = quiet(e.search, 'слово', indices=['', None, 'a']); check('search: пустые имена индексов отбрасываются', len(res) == 1 and 'FROM `a`' in srv.sql[-1])
e, srv = engine(DOC, current=None); check('search: индекс не выбран и не задан — []; все индексы пустые — []', quiet(e.search, 'небо')[0] == [] and quiet(e.search, 'небо', indices=['', None])[0] == [] and not srv.sql)
e, srv = engine(DOC); check('search: в запросе нет слов нужной длины — [] без обращения к серверу', quiet(e.search, 'да')[0] == [] and not srv.sql)
e, srv = engine(DOC); res, _ = quiet(e.search, 'да', min_word_length=2); check('search: минимальная длина слова задаётся вызывающим (по умолчанию 3)', len(srv.sql) == 1 and 'MATCH(\'@(section_text) *да*\')' in ' '.join(srv.sql[-1].split()))
e, srv = engine({'idx': {1: ('я иду', 'a', '0')}}); quiet(e.search, 'я', min_word_length=1); check('search: слово из одной буквы — без звёздочек (точное слово)', "MATCH('@(section_text) я')" in ' '.join(srv.sql[-1].split()))
e, srv = engine(DOC); srv.fail_when = lambda s: 'MATCH' in s; r, out = quiet(e.search, 'небо'); check('search: сбой сервера — [] с причиной в консоли, исключения нет', r == [] and 'Ошибка поиска' in out)
e, srv = engine({'idx': {1: ('совсем другой', 'a', '0')}}); check('search: сервер ничего не нашёл — []', quiet(e.search, 'небо')[0] == [])
e, srv = engine({'idx': {1: ('небо', 'a', '0'), 2: ('небосвод', 'a', '1')}}); res, _ = quiet(e.search, '.небо.')
check('search: точное слово «.небо.» — серверу отдаётся слово без точек, а строгий отбор по границам слова делает программа после ответа (небосвод отсеивается)', [r['rowid'] for r in res] == [1] and "*небо*" in ' '.join(srv.sql[-1].split()), str(res))
from utils.query_parser import compute_matches, compute_matches_unique, parse_query_words
DOC2 = {'idx': {1: ('небо небо небо', 'a', '0'), 2: ('небо и земля', 'a', '1')}}; qwi = parse_query_words('небо земля')
e, srv = engine(DOC2); r1, _ = quiet(e.search, 'небо земля'); r2, _ = quiet(e.search, 'небо земля', unique_word_rating=True)
by1 = {r['rowid']: r['meta'] for r in r1}; by2 = {r['rowid']: r['meta'] for r in r2}
check('для проверки переключателя тексты подобраны так, что обычный и «уникальный» рейтинги дают РАЗНЫЕ мета-данные', compute_matches(DOC2['idx'][1][0], qwi) != compute_matches_unique(DOC2['idx'][1][0], qwi))
check('search: по умолчанию мета-данные считает compute_matches (каждое вхождение), с unique_word_rating=True — compute_matches_unique (каждое слово запроса один раз)', all(by1[i] == compute_matches(DOC2['idx'][i][0], qwi) for i in (1, 2)) and all(by2[i] == compute_matches_unique(DOC2['idx'][i][0], qwi) for i in (1, 2)), f'{by1} / {by2}')
# ===================== H. помощники и граничные случаи =====================
e, srv = engine({}); sect = {'lines': ['раз', 'два'], 'start_line': 7}
check('_row_values: строка VALUES — id и section_id = номер секции + 1, текст секции из строк через перевод строки, имя файла и позиция с экранированием', e._row_values(4, sect, "ф'а") == "(5, 5, 'раз\\nдва', 'ф\\'а', '7')", e._row_values(4, sect, "ф'а"))
check('_row_values: позиции нет — «0»', e._row_values(0, {'lines': ['х']}, 'ф') == "(1, 1, 'х', 'ф', '0')")
check('_insert_sql: INSERT с перечислением колонок и значениями через запятую', e._insert_sql('`t`', ['(1)', '(2)']) == 'INSERT INTO `t` (id, section_id, section_text, file_name, position) VALUES (1), (2)')
check('_find_existing_index: настоящее имя (без учёта регистра) или None', engine({'Книга': {}})[0]._find_existing_index('книга') == 'Книга' and engine({'а': {}})[0]._find_existing_index('б') is None)
check('_match_expression: слова через « | »; от двух букв — *слово*, одна буква — как есть', me.ManticoreEngine._match_expression([('небо', 3, False), ('я', 1, False), ('земля', 3, False)]) == '*небо* | я | *земля*')
rows_in = [(1, 'небо над головой', 'ф', '3'), (2, 'небосвод', 'ф', '4'), (3, 'небо')]
rated = me.ManticoreEngine._rate_rows(rows_in, [('небо', 3, False)], False)
check('_rate_rows: слово как начало слов — подходят все три строки; у строки без имени файла и позиции подставляются «» и «0»', [(r['rowid'], r['file_name'], r['position']) for r in rated] == [(1, 'ф', '3'), (2, 'ф', '4'), (3, '', '0')], str(rated))
strict = me.ManticoreEngine._rate_rows(rows_in, [('небо', 4, True)], False)
check('_rate_rows: точное слово («.небо.» разбирается как (слово, 4, True)) — «небосвод» отсеивается строгой проверкой программы', [r['rowid'] for r in strict] == [1, 3], str([r['rowid'] for r in strict]))
e, srv = engine({'idx': {}}); calls = []; srv.fail_when = lambda s: s.lstrip().startswith('INSERT') and s.count("', '") > 10 and not calls.append(1) and len(calls) == 1
r, _ = quiet(e.index_text, text_of(300), 'ExcelRow1', lambda d, t: calls.append((d, t)))
check('прогресс при построчной досылке: сообщения приходят и из досылки, и после следующих пакетов; в конце всегда (300, 300)', calls[-1] == (300, 300) and r == 300 and len(srv.tables['idx']) == 300, str(calls[-3:]))
e, srv = engine({'idx': {}}); real_commit = e.conn.commit
def bad_commit(): raise RuntimeError('фиксация не удалась')
e.conn.commit = bad_commit
try: quiet(e.index_text, text_of(5), 'ExcelRow1'); raised = None
except RuntimeError as ex: raised = str(ex)
check('сбой фиксации: исключение пробрасывается, а автофиксация всё равно включается обратно', raised == 'фиксация не удалась' and srv.autocommit_log[-1] is True)
e, srv = engine({'idx': {}}); quiet(e.index_text, '\n\n  \nраз\n\nдва', 'ExcelRow1')
check('«одна строка — один топик»: пустые строки пропускаются, позиция — номер строки в тексте (с нуля), номера секций идут подряд', [(x[0], x[1], x[3]) for x in stored(srv)] == [(1, 'раз', '3'), (2, 'два', '5')], str(stored(srv)))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
