import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import contextlib, io, random, re, time, types, zipfile

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

from utils import text_processing as tp
from docx import Document

WORK = env.tmpdir('textproc_')
def path(name): return os.path.join(WORK, name)
def write_bytes(name, data): p = path(name); open(p, 'wb').write(data); return p
def make_docx(name, paragraphs, table=None):
    """paragraphs: список абзацев; абзац — строка или список «кусков»: строка = текст прогона, '<TAB>' и '<BR>' — табуляция и разрыв строки."""
    doc = Document()
    for item in paragraphs:
        p = doc.add_paragraph()
        for part in (item if isinstance(item, list) else [item]):
            run = p.add_run('' if part in ('<TAB>', '<BR>') else part)
            if part == '<TAB>': run.add_tab()
            if part == '<BR>': run.add_break()
    if table:
        cell = doc.add_table(rows=1, cols=1).rows[0].cells[0]; cell.text = table
    p = path(name); doc.save(p); return p

# ===================== A. чтение файлов =====================
check('utf-8', tp.read_text_file(write_bytes('u8.txt', 'Привет, мир\nвторая'.encode('utf-8'))) == 'Привет, мир\nвторая')
check('cp1251 (не годится как utf-8 — берётся следующая кодировка)', tp.read_text_file(write_bytes('c1251.txt', 'Привет, мир'.encode('cp1251'))) == 'Привет, мир')
check('CRLF в файле читается как обычный перевод строки', tp.read_text_file(write_bytes('crlf.txt', 'а\r\nб\r\n'.encode('utf-8'))) == 'а\nб\n')
check('пустой файл — пустая строка', tp.read_text_file(write_bytes('empty.txt', b'')) == '')
check('(особенность) BOM UTF-8 остаётся первым символом текста', tp.read_text_file(write_bytes('bom.txt', '\ufeffПривет'.encode('utf-8'))) == '\ufeffПривет')
check('файл с «непонятными» байтами читается (latin-1 принимает любые) и исключения не бывает', isinstance(tp.read_text_file(write_bytes('junk.txt', b'\xff\xfe\x98\x81')), str))
check('(ограничение) koi8-r в списке кодировок недостижим: latin-1 стоит раньше и принимает любые байты',
      tp.TEXT_ENCODINGS.index('latin-1') < tp.TEXT_ENCODINGS.index('koi8-r') and tp.TEXT_ENCODINGS[:2] == ['utf-8', 'cp1251'])
check('расширение определяется без учёта регистра (.DOCX читается как docx)', tp.read_text_file(make_docx('UP.DOCX', ['Раз', 'Два'])) == 'Раз\nДва')

# docx
tp._docx_paragraphs_cache.clear()
pp = make_docx('doc1.docx', ['Первый абзац', '', ['Таб', '<TAB>', 'уляция'], ['Строка1', '<BR>', 'Строка2'], ['Много ', 'прогонов ', 'в абзаце']], table='В ТАБЛИЦЕ')
fast = tp._read_docx_paragraphs_fast(pp); lib = tp._read_docx_paragraphs_with_docx_lib(pp)
check('docx: быстрый разбор XML выдаёт абзацы с табуляцией, разрывом строки и несколькими прогонами', fast == ['Первый абзац', '', 'Таб\tуляция', 'Строка1\nСтрока2', 'Много прогонов в абзаце'], str(fast))
check('docx: быстрый разбор и python-docx дают ОДИНАКОВЫЙ результат (абзацы таблиц не входят ни там, ни там)', fast == lib and 'В ТАБЛИЦЕ' not in ' '.join(fast))
check('docx: read_text_file склеивает абзацы переводом строки, пустые сохраняет', tp.read_text_file(pp) == '\n'.join(fast))
check('docx: keep_empty_docx_paragraphs=False убирает пустые абзацы (так читает индексация)', tp.read_text_file(pp, keep_empty_docx_paragraphs=False) == '\n'.join(p for p in fast if p.strip()))
check('docx: пустой абзац — разница между режимами ровно в нём', tp.read_text_file(pp).count('\n') == tp.read_text_file(pp, False).count('\n') + 1)

# кеш docx
tp._docx_paragraphs_cache.clear(); calls = []; real_fast = tp._read_docx_paragraphs_fast
def counting(p): calls.append(p); return real_fast(p)
tp._read_docx_paragraphs_fast = counting
try:
    cp = make_docx('cache.docx', ['Старое'])
    tp._get_docx_paragraphs_cached(cp); tp._get_docx_paragraphs_cached(cp); tp._get_docx_paragraphs_cached(cp)
    check('кеш: повторное чтение того же файла не разбирает его заново', len(calls) == 1)
    make_docx('cache.docx', ['Новое содержимое длиннее'])
    st = os.stat(cp); os.utime(cp, (st.st_atime + 10, st.st_mtime + 10))
    check('кеш: файл изменился на диске — читается заново и отдаёт новое содержимое', tp._get_docx_paragraphs_cached(cp) == ['Новое содержимое длиннее'] and len(calls) == 2)
    tp._docx_paragraphs_cache.clear(); files = [make_docx(f'lru{i}.docx', [f'файл {i}']) for i in range(7)]
    for f in files[:5]: tp._get_docx_paragraphs_cached(f)
    tp._get_docx_paragraphs_cached(files[0])           # самый старый становится самым свежим
    tp._get_docx_paragraphs_cached(files[5])           # переполнение: вытесняется самый давний = files[1]
    keys = list(tp._docx_paragraphs_cache)
    check('кеш: хранится не больше 5 файлов, вытесняется давно не использовавшийся (а не просто первый добавленный)',
          len(keys) == 5 and os.path.abspath(files[1]) not in keys and os.path.abspath(files[0]) in keys, str([os.path.basename(k) for k in keys]))
finally:
    tp._read_docx_paragraphs_fast = real_fast

# запасной способ и ошибки
tp._docx_paragraphs_cache.clear()
def broken(p): raise ValueError('нестандартный документ')
tp._read_docx_paragraphs_fast = broken
try:
    fp = make_docx('fallback.docx', ['Через', 'python-docx'])
    check('если быстрый разбор не справился — используется python-docx, результат тот же', tp.read_text_file(fp) == 'Через\npython-docx')
finally:
    tp._read_docx_paragraphs_fast = real_fast
tp._docx_paragraphs_cache.clear()
for label, p in (('битый .docx (не zip)', write_bytes('bad.docx', 'это не docx'.encode('utf-8'))), ('несуществующий .docx', path('нет_такого.docx'))):
    try: tp.read_text_file(p); msg = None
    except Exception as e: msg = str(e)
    check(f'{label}: понятная ошибка «Ошибка чтения .docx», а не молчание', msg is not None and msg.startswith('Ошибка чтения .docx'), str(msg))

# ===================== B. имена индексов =====================
S = tp.make_safe_index_name
check('кириллица транслитерируется: Библия.txt -> bibliya', S('Библия.txt', 'manticore') == ('bibliya', 'bibliya'))
check('пробелы -> «_»: Книга Мудрости.docx', S('Книга Мудрости.docx', 'manticore') == ('kniga_mudrosti', 'kniga_mudrosti'))
check('Elastic: полное имя с префиксом ms_', S('Библия.txt', 'elasticsearch') == ('bibliya', 'ms_bibliya'))
check('ведущая цифра: для Manticore добавляется idx_, для Elastic префикс ms_ уже решает', S('1 Глава.txt', 'manticore') == ('idx_1_glava', 'idx_1_glava') and S('1 Глава.txt', 'elasticsearch') == ('1_glava', 'ms_1_glava'))
check('имя из одних знаков -> «index»', S('!!!.txt', 'manticore') == ('index', 'index') and S('!!!.txt', 'elasticsearch') == ('index', 'ms_index'))
check('всегда нижний регистр (Manticore хранит имена таблиц так)', S('ABC.TXT', 'manticore')[0] == 'abc' and S('ЩЁ.txt', 'manticore')[0] == 'sche')
check('повторные и крайние «_» схлопываются: __a__b__ -> a_b; скобки и пробелы тоже', S('__a__b__.txt', 'manticore')[0] == 'a_b' and S('мой файл (копия 2).docx', 'manticore')[0] == 'moy_fayl_kopiya_2')
check('папка в пути отбрасывается', S('D:/папка/Книга.txt', 'manticore')[0] == 'kniga')
check('украинские буквы: Їжак -> yizhak', S('Їжак.txt', 'manticore')[0] == 'yizhak')
names = ['Библия', 'Гита', 'Реформа', 'Коран', 'Талмуд', 'Дхаммапада']
check('РАЗНЫЕ кириллические имена дают РАЗНЫЕ имена индексов (ради этого и введена транслитерация)', len({S(n + '.txt', 'manticore')[0] for n in names}) == len(names) and 'index' not in {S(n + '.txt', 'manticore')[0] for n in names})
check('результат безопасен: только латиница, цифры и «_»', all(re.fullmatch(r'[a-z0-9_]+', S(n, 'manticore')[0]) for n in ('Ёж.txt', 'ДА-ДА.docx', 'x y.txt', 'Ц#ц.txt', 'a.b.c.txt')))
check('(ограничение) транслитерация делает «я.txt» и «ya.txt» одним именем — коллизия возможна', S('я.txt', 'manticore') == S('ya.txt', 'manticore'))
check('идемпотентно: уже безопасное имя не меняется', S('my_book.txt', 'manticore')[0] == 'my_book')
check('вся русская азбука транслитерируется в латиницу', all(ord(c) < 128 for c in tp._transliterate('абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ')))

# ===================== C. разбиение на топики =====================
def view(sections): return [(s['title'], s['lines'], s['start_line']) for s in sections]
split = tp.split_into_sections_by_separator

lines = ['Вступление', '1 Первый', 'текст', '2 Второй', 'ещё', '', '3 Третий']
check('Numeric: топик начинается со строки, начинающейся с числа; текст до первого числа — отдельный топик без названия',
      view(split(lines, 'Numeric')) == [('', ['Вступление'], 0), ('1 Первый', ['1 Первый', 'текст'], 1), ('2 Второй', ['2 Второй', 'ещё', ''], 3), ('3 Третий', ['3 Третий'], 6)], str(view(split(lines, 'Numeric'))))
check('Numeric: пробелы перед числом допускаются, название обрезается до 100 символов', view(split(['   7 ' + 'x' * 150], 'Numeric'))[0][0] == ('7 ' + 'x' * 150)[:100])
check('Numeric: без нумерованных строк — один топик на весь текст; пустой ввод — нет топиков', len(split(['а', 'б'], 'Numeric')) == 1 and split(['а', 'б'], 'Numeric')[0]['title'] == '' and split([], 'Numeric') == [])

lines = ['преамбула', '=== Глава 1', 'а', '   === Глава 2', 'б']
check('строковый разделитель: топик начинается со строки, начинающейся с него (пробелы по краям не мешают); начало — отдельный топик',
      [(t, s) for t, _l, s in view(split(lines, '==='))] == [('', 0), ('=== Глава 1', 1), ('=== Глава 2', 3)] and split(lines, '===')[2]['lines'][0] == '   === Глава 2')
check('строковый разделитель в СЕРЕДИНЕ строки (не первой) топик не начинает',
      len(split(['начало', 'а === б', 'в'], '===')) == 1 and len(split(['начало', '=== б', 'в'], '===')) == 2)
check('пустой разделитель: каждая строка — отдельный топик', len(split(['а', 'б', 'в'], '')) == 3)
check('(особенность) разделитель, начинающийся с латинской «N» и не число («Note:»), понимается как размер блока (100): строк по такому слову не разделить',
      len(split(['Note: а', 'x', 'Note: б', 'y'], 'Note:')) == 1 and split(['Note: а', 'x'], 'Note:')[0]['title'].startswith('Блок 1'))

lines = ['a', '', '  ', 'b b', 'c' * 150]
ex = split(lines, 'ExcelRow1')
check('ExcelRow1: каждая непустая строка — топик, пустые пропускаются, start_line — номер исходной строки, название ≤ 100', [(s['lines'], s['start_line']) for s in ex] == [(['a'], 0), (['b b'], 3), (['c' * 150], 4)] and len(ex[2]['title']) == 100)

# фиксированный размер
lines = ['aaa bbb ccc', 'ddd eee fff', 'ggg hhh iii', 'jjj kkk lll']
fx = split(lines, 'N12')
check('N12: блоки по ~12 символов, обрываются на пробелах, с названием «Блок k (символы a-b)» и номером строки начала',
      view(fx) == [('Блок 1 (символы 1-8)', ['aaa bbb'], 0), ('Блок 2 (символы 9-20)', ['ccc\nddd eee'], 0), ('Блок 3 (символы 21-32)', ['fff\nggg hhh'], 1),
                   ('Блок 4 (символы 33-44)', ['iii\njjj kkk'], 2), ('Блок 5 (символы 45-47)', ['lll'], 3)], str(view(fx)))
long_text = [' '.join(['слово'] * 80)]
base = view(split(long_text, 'N100'))
check('неверный размер (Nabc, N0, N-5, N) = размер по умолчанию 100', all(view(split(long_text, s)) == base for s in ('Nabc', 'N0', 'N-5', 'N')) and len(base) > 1)
check('размер больше текста — один блок на весь текст', len(split(lines, 'N100000')) == 1 and split(lines, 'N100000')[0]['lines'][0] == '\n'.join(lines))
check('пустой текст и текст из пробелов — нет блоков', split([], 'N50') == [] and split(['   ', ''], 'N50') == [])
rnd = random.Random(21); ok_loss = ok_size = True
for _ in range(120):
    words = [''.join(rnd.choice('абвгд') for _ in range(rnd.randint(1, 12))) for _ in range(rnd.randint(1, 60))]
    text = ' '.join(words); size = max(rnd.randint(5, 80), len(words[-1])); blocks = [s['lines'][0] for s in split([text], f'N{size}')]  # последнее слово ≤ размера: краевой случай — ниже
    ok_loss &= ' '.join(' '.join(blocks).split()) == ' '.join(words)
    ok_size &= all(len(b) <= max(size, max(len(w) for w in words)) for b in blocks)
check('свойство (120 случайных текстов): ничего не теряется и не рвётся посреди слова, блок не длиннее max(размер, самое длинное слово)', ok_loss and ok_size)
tail = split(['aaa bbb ' + 'c' * 13], 'N8')
check('N8: последнее слово текста, длиннее размера блока, не режется посреди слова', [s['lines'][0] for s in tail] == ['aaa bbb', 'c' * 13],
            f"получилось {[s['lines'][0] for s in tail]}")
check('длинное слово НЕ в конце продлевает блок до пробела (не режется)', [s['lines'][0] for s in split(['aaa ' + 'c' * 13 + ' bbb'], 'N8')] == ['aaa', 'c' * 13, 'bbb'], str([s['lines'][0] for s in split(['aaa ' + 'c' * 13 + ' bbb'], 'N8')]))

# блоки по размеру
bs = tp.split_into_blocks_by_size_with_positions
check('по размеру: блоки на границах пробелов, с позициями начала и конца', bs('aaa bbb ccc ddd', 8) == (['aaa bbb', 'ccc ddd'], {'starts': [0, 8], 'ends': [8, 15]}), str(bs('aaa bbb ccc ddd', 8)))
check('по размеру: размер ≤ 0 — один блок целиком; пустой текст — нет блоков', bs('текст', 0) == (['текст'], {'starts': [0], 'ends': [5]}) and bs('текст', -3)[0] == ['текст'] and bs('', 10) == ([], {'starts': [], 'ends': []}))
rnd = random.Random(22); ok_cover = ok_contig = ok_len = ok_whole = True
for _ in range(120):
    text = ' '.join(''.join(rnd.choice('абвгд') for _ in range(rnd.randint(1, 12))) for _ in range(rnd.randint(1, 60))); size = max(rnd.randint(5, 80), len(text.split()[-1]))
    blocks, pos = bs(text, size)
    ok_whole &= ' '.join(blocks).split() == text.split()
    ok_cover &= ''.join(text[s:e] for s, e in zip(pos['starts'], pos['ends'])) == text
    ok_contig &= pos['starts'][0] == 0 and pos['ends'][-1] == len(text) and all(pos['ends'][i] == pos['starts'][i + 1] for i in range(len(blocks) - 1))
    ok_len &= all(len(b) <= max(size, max(len(w) for w in text.split())) for b in blocks)
check('свойство (120 случайных текстов): блоки покрывают текст без дыр и наложений (end[i] = start[i+1])', ok_cover and ok_contig)
check('свойство: блок не длиннее max(размер, самое длинное слово)', ok_len)
check('свойство: слова не режутся (список слов из блоков = списку слов текста)', ok_whole)
tail_blocks = bs('aaa bbb ' + 'c' * 13, 8)[0]
check('по размеру: последнее слово, длиннее размера блока, не режется посреди слова', tail_blocks == ['aaa bbb', 'c' * 13], f'получилось {tail_blocks}')

# смысловое разбиение
sem = tp.split_into_blocks_by_semantic_with_positions
check('смысловое: пустой текст — нет блоков', sem('') == ([], {'starts': [], 'ends': []}))
check('смысловое: короткий текст без точек — один блок', sem('просто текст без точки', 200)[0] == ['просто текст без точки'])
text5 = "Первое предложение здесь. Второе предложение там. Третье предложение тут. Четвёртое предложение везде. Пятое предложение всегда."
blocks, pos = sem(text5, 60)
check('смысловое (цель 60): предложения собираются в блоки не длиннее цели', len(blocks) == 3 and all(len(b) <= 60 for b in blocks), str(blocks))
rnd = random.Random(23); ok_words = ok_size = True
def rand_sentence(): return ' '.join(''.join(rnd.choice('абвгдежз') for _ in range(rnd.randint(2, 9))) for _ in range(rnd.randint(2, 14))) + rnd.choice(['.', '!', '?'])
for _ in range(100):
    paragraphs = ['  '.join(rand_sentence() for _ in range(rnd.randint(1, 6))) for _ in range(rnd.randint(1, 4))]
    text = '\n\n'.join(paragraphs); target = rnd.choice([40, 80, 150, 300]); blocks, _p = sem(text, target)
    ok_words &= sorted(re.findall(r'\w+', text)) == sorted(re.findall(r'\w+', ' '.join(blocks)))
    ok_size &= all(len(b) <= max(1.5 * target, 12) for b in blocks)
check('свойство (100 случайных текстов): слова не теряются и не дублируются при разбиении', ok_words)
check('свойство: блок не длиннее 1,5 цели (длиннее — только слишком длинное предложение, оно режется по словам)', ok_size)
blocks, pos = sem(text5, 60)
check('смысловое: позиций столько же, сколько блоков (начал и концов по одному на блок)', len(pos['starts']) == len(blocks) == len(pos['ends']), f"блоков {len(blocks)}, начал {len(pos['starts'])}, концов {len(pos['ends'])}")
first_words = [b.split()[0] for b in blocks]
check('смысловое: начало каждого блока указывает на его первое слово в тексте', len(pos['starts']) >= len(blocks) and all(text5[pos['starts'][i]:].startswith(first_words[i]) for i in range(len(blocks))),
            f"начала {pos['starts']}; с этих мест начинается: {[text5[s:s + 10] for s in pos['starts'][:len(blocks)]]}")
long_text5 = ' '.join(['слово'] * 40); blocks, pos = sem(long_text5, 50)
check('смысловое: у кусков слишком длинного предложения начала разные и растут', len(blocks) > 2 and pos['starts'][:len(blocks)] == sorted(set(pos['starts'][:len(blocks)])) and len(set(pos['starts'])) == len(blocks), f"начала {pos['starts']}")
ns_lines = ['Первое предложение здесь.', 'Второе предложение там.', 'Третье предложение тут.', 'Четвёртое предложение везде.', 'Пятое предложение всегда.']
ns = split(ns_lines, 'NS60')
check('NS60: топики «Блок i (смысловой)», по одному на смысловой блок, текст сохранён', [s['title'] for s in ns] == ['Блок 1 (смысловой)', 'Блок 2 (смысловой)', 'Блок 3 (смысловой)'] and sorted(re.findall(r'\w+', ' '.join(s['lines'][0] for s in ns))) == sorted(re.findall(r'\w+', '\n'.join(ns_lines))))
check('NS: номер строки начала не выходит за границы текста', all(0 <= s['start_line'] < len(ns_lines) for s in ns))
check('NS60: номер строки начала топика = строка, где лежит его первое предложение (0, 2, 4)', [s['start_line'] for s in ns] == [0, 2, 4], f"получилось {[s['start_line'] for s in ns]}")
check('NS с неверным размером (NSabc) = размер по умолчанию 200', view(split(ns_lines, 'NSabc')) == view(split(ns_lines, 'NS200')))

# ===================== D. журнал разбиения =====================
def log_text(sep, sections):
    p = path('log_' + str(abs(hash(sep))) + '.txt'); tp.log_sections(sep, sections, log_file=p); return open(p, encoding='utf-8').read()
one = [{'lines': ['текст'], 'title': 'a', 'start_line': 5}]
check('журнал: расшифровка разделителей (Numeric, NS150, NSabc, N1000, Nxx, строка)',
      'Разделитель по номерам строк' in log_text('Numeric', one) and 'Смысловой блок, ~150 символов' in log_text('NS150', one) and 'неверный параметр: NSabc' in log_text('NSabc', one)
      and 'Фиксированный размер: 1000 символов' in log_text('N1000', one) and 'Фиксированный размер (неверный параметр: Nxx)' in log_text('Nxx', one) and "Строковый разделитель: '==='" in log_text('===', one))
many = [{'lines': [f'текст {i}'], 'title': str(i), 'start_line': i * 3} for i in range(1, 11)]
lt = log_text('N100', many)
check('журнал: «Всего топиков: 10», подробно только первые 7 с позициями', 'Всего топиков: 10' in lt and 'Топик 7 ---' in lt and 'Топик 8' not in lt and 'Позиция (строка): 21' in lt)
check('журнал: длинный текст топика обрезается до 500 символов с «...»', ('Текст: ' + 'ы' * 500 + '...') in log_text('N100', [{'lines': ['ы' * 600], 'title': 't', 'start_line': 0}]))
buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    try: tp.log_sections('N100', one, log_file=path('нет_папки/лог.txt')); raised = False
    except Exception: raised = True
check('журнал: нельзя записать файл — исключения нет, сообщение выводится (диагностика не должна ронять индексацию)', not raised and 'Ошибка записи диагностики' in buffer.getvalue())

# ===================== E. предложения =====================
saved = {k: sys.modules.get(k) for k in ('nltk', 'nltk.tokenize')}
def restore():
    for k, v in saved.items():
        if v is None: sys.modules.pop(k, None)
        else: sys.modules[k] = v
try:
    sys.modules['nltk'] = None     # «nltk не установлен»: import даёт ImportError -> запасное разбиение по знакам
    check('без nltk: разбиение по концам предложений (. ! ?)', tp.split_sentences('Первое. Второе! Третье? Четвёртое') == ['Первое.', 'Второе!', 'Третье?', 'Четвёртое'])
    check('без nltk: пробелы и переводы строк между предложениями убираются, пустой текст — пустой список', tp.split_sentences('А.\n\n  Б.   В.') == ['А.', 'Б.', 'В.'] and tp.split_sentences('') == [] and tp.split_sentences('   ') == [])
    check('без nltk: текст без знаков — одно предложение', tp.split_sentences('просто слова без точки') == ['просто слова без точки'])
    check('без nltk (известная слабость, см. описание функции): сокращение «т.е.» режет предложение', tp.split_sentences('Это т.е. пример.') == ['Это т.е.', 'пример.'])

    data_calls = []
    fake_nltk = types.ModuleType('nltk'); fake_nltk.data = types.SimpleNamespace(find=lambda name: data_calls.append(name))
    fake_tok = types.ModuleType('nltk.tokenize'); fake_tok.sent_tokenize = lambda text, language=None: [f'[{language}] {text}']
    sys.modules['nltk'] = fake_nltk; sys.modules['nltk.tokenize'] = fake_tok
    check('с nltk: используется его токенизатор для русского языка', tp.split_sentences('Привет. Мир.') == ['[russian] Привет. Мир.'] and data_calls == ['tokenizers/punkt_tab'])
    def find_missing(name): raise LookupError(name)
    fake_nltk.data = types.SimpleNamespace(find=find_missing)
    check('nltk есть, но данных punkt нет — тихий переход на запасное разбиение', tp.split_sentences('Раз. Два.') == ['Раз.', 'Два.'])
    fake_nltk.data = types.SimpleNamespace(find=lambda name: None)
    def broken_tokenizer(text, language=None): raise RuntimeError('сбой токенизатора')
    fake_tok.sent_tokenize = broken_tokenizer
    check('сбой токенизатора nltk — тоже запасное разбиение, а не падение', tp.split_sentences('Раз. Два.') == ['Раз.', 'Два.'])
finally:
    restore()
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
