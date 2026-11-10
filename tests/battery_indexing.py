import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import tkinter as tk
import services.file_manager as fmm
import stats_logger
from utils.text_processing import make_safe_index_name
from docx import Document
import openpyxl

# Файлы и индексация: список файлов, выбор в списке, «добавить в индекс» (Manticore, Elastic, FTS5). Файлы настоящие — во временной
# рабочей папке; движок — заглушка, записывающая каждый вызов (и каждое изменение _current_file_name). Пути в ожиданиях — через
# os.path.join: на Windows они выглядят иначе, чем на Linux.
WORK = env.tmpdir('indexing_'); os.chdir(WORK); os.makedirs('DB')
LOG = []
ns = types.SimpleNamespace
def rec(name, ret=None): return lambda *a, **k: (LOG.append((name,) + a + (tuple(sorted(k.items())) if k else ())), ret)[1]
def calls(name): return [c for c in LOG if c[0] == name]
def names(): return [c[0] for c in LOG]
class Box:
    answers = {}
    def __getattr__(self, kind):
        if kind.startswith('__'): raise AttributeError(kind)
        return lambda title='', text='', *a, **k: (LOG.append(('msg', kind, title, text)), Box.answers.get(kind, True))[1]
fmm.messagebox = Box(); stats_logger.STATS_ENABLED = False

class Listbox:
    def __init__(self): self.items = []; self.sel = ()
    def delete(self, a, b): self.items = []; self.sel = ()
    def insert(self, pos, text): self.items.append(text)
    def curselection(self): return tuple(self.sel)
    def get(self, i): return self.items[i]
    def selection_clear(self, a, b): self.sel = ()
    def selection_set(self, a, b): self.sel = tuple(range(len(self.items)))
class Engine:
    def __init__(self, engine_type='manticore', existing=(), fail_create=False, fail_text=False, list_raises=False, data_dir='.'):
        self.engine_type = engine_type; self.existing = list(existing); self.fail_create = fail_create; self.fail_text = fail_text; self.list_raises = list_raises; self.data_dir = data_dir; self._cfn = None
    @property
    def _current_file_name(self): return self._cfn
    @_current_file_name.setter
    def _current_file_name(self, value): LOG.append(('file_name', value)); self._cfn = value
    def list_indices(self):
        LOG.append(('list_indices',))
        if self.list_raises: raise RuntimeError('Manticore не отвечает')
        return list(self.existing)
    def create_index(self, name):
        LOG.append(('create_index', name))
        if self.fail_create: raise RuntimeError('нельзя создать')
        return 'ms_' + name if self.engine_type == 'elasticsearch' else name
    def index_text(self, text, separator):
        LOG.append(('index_text', text, separator, self._cfn))
        if self.fail_text: raise RuntimeError('сбой индексации')
        return len(text.splitlines())

CONFIG = {'книга.txt': ('Книга', 'N500', ''), 'таблица.xlsx': ('Таблица', 'ExcelRow1', 'служебная'), 'Библия (синод).txt': ('Синод', 'N1000', '')}
def make(engine=None, config=None, listbox=None, default_separator='N1000'):
    LOG.clear(); Box.answers = {}
    fm = fmm.FileManager(engine or Engine(), CONFIG if config is None else config, default_separator, listbox, rec('status'), {}, rec('update_index_list'))
    fm.update_text_list = rec('update_text_list')
    return fm
def write(rel, text='первая строка\nвторая строка'):
    path = os.path.join(WORK, *rel.split('/')); os.makedirs(os.path.dirname(path), exist_ok=True); open(path, 'w', encoding='utf-8', newline='').write(text); return os.path.join(*rel.split('/'))
def run_index(fm, files):
    fm.selected_text_files = list(files); LOG.clear()
    fm.add_to_index(rec('show'), rec('update'), rec('hide'))
def summary(): return calls('msg')[-1][3] if calls('msg') else ''
def DB(name): return os.path.join('DB', name)

write('книга.txt', 'один\nдва\nтри'); write('DB/книга2.txt'); write('a.txt'); write('B.TXT'); write('сл.DOCX', ''); write('данные.xlsx', '')
write('DB/нота.txt'); write('DB/пустой.txt', '   \n  '); write('картинка.png', 'x'); write('DB/заметки.md', 'x'); os.makedirs('подпапка.txt', exist_ok=True)
d_ = Document(); [d_.add_paragraph(t) for t in ('Первый абзац', '', 'Третий абзац')]; d_.save(os.path.join(WORK, 'DB', 'доки.docx'))
wb = openpyxl.Workbook(); wb.active.append(['Болт', 12]); wb.active.append(['служебная строка', 1]); wb.active.append(['Гайка', 7]); wb.save(os.path.join(WORK, 'DB', 'таблица.xlsx'))

# ===================== A. список файлов =====================
fm = make(); scan = fm._scan_text_files()
check('в списке — файлы txt/docx/xlsx из рабочей папки (подпапка пустая) и из DB; расширение без учёта регистра', sorted(scan) == sorted([('', 'a.txt'), ('', 'B.TXT'), ('', 'книга.txt'), ('', 'сл.DOCX'), ('', 'данные.xlsx'),
      ('DB', 'книга2.txt'), ('DB', 'нота.txt'), ('DB', 'пустой.txt'), ('DB', 'доки.docx'), ('DB', 'таблица.xlsx')]), str(sorted(scan)))
check('чужие расширения (png, md) и папки в список не попадают', not any(f.endswith(('.png', '.md')) or f == 'подпапка.txt' for _d, f in scan))
os.rename('DB', 'DB_off'); check('нет папки DB — только рабочая папка, без ошибки', all(d == '' for d, _f in make()._scan_text_files())); os.rename('DB_off', 'DB')
lb = Listbox(); fm = make(listbox=lb); fm.update_text_list = fmm.FileManager.update_text_list.__get__(fm); fm.update_text_list()
check('подписи в списке: файл из DB — с «/» в начале; если файл описан в настройках — «(алиас)» в конце', '/книга2.txt' in lb.items and 'a.txt' in lb.items and 'книга.txt (Книга)' in lb.items and '/таблица.xlsx (Таблица)' in lb.items, str(sorted(lb.items)))
check('список перед заполнением очищается (повторное обновление не дублирует)', (fm.update_text_list(), len(lb.items) == len(scan))[1])
fm = make(listbox=None); fm.update_text_list = fmm.FileManager.update_text_list.__get__(fm)
check('списка файлов нет (окно без него) — обновление ничего не делает, выбор пуст', fm.update_text_list() is None and (fm._update_selected_text_files(), fm.selected_text_files == [])[1])

# ===================== B. выбор в списке =====================
def select(items, indices, config=None):
    lb = Listbox(); lb.items = list(items); lb.sel = tuple(indices); fm = make(listbox=lb, config=config); fm.on_text_select(None); return fm.selected_text_files
check('выбор: файл из рабочей папки — по имени; файл из DB («/имя») — путь DB/имя; подпись алиаса отбрасывается', select(['книга.txt (Книга)', '/нота.txt', 'a.txt', '/книга2.txt (Алиас)'], (0, 1, 2, 3)) == ['книга.txt', DB('нота.txt'), 'a.txt', DB('книга2.txt')])
check('выбор: порядок — как выбрано в списке, невыбранные пропускаются', select(['a.txt', 'b.txt', 'c.txt'], (2, 0)) == ['c.txt', 'a.txt'])
check('выбор: ничего не выбрано — пусто', select(['a.txt'], ()) == [])
for label, items, expected in (('файл «a (1).txt» без алиаса', ['a (1).txt'], ['a (1).txt']), ('файл в DB «Отчёт (копия).docx» с алиасом', ['/Отчёт (копия).docx (Алиас)'], [DB('Отчёт (копия).docx')]),
                               ('алиас со скобками «Библия (синод)»', ['/нота.txt (Библия (синод))'], [DB('нота.txt')]), ('файл со скобками и алиасом со скобками', ['/Библия (синод).txt (Синод (старый))'], [DB('Библия (синод).txt')])):
    got = select(items, (0,))
    check(f'выбор: имя с « (» разбирается верно — {label}', got == expected, f'получилось {got}, ожидалось {expected}')
fm = make(listbox=Listbox()); fm.text_listbox.items = ['a.txt', 'b.txt']
fm.text_listbox._scan = None; fm._scan_text_files = lambda: [('', 'a.txt'), ('', 'b.txt')]
fm.on_text_right_click(None)
check('правый клик: выбрано не всё — выбираются все файлы, выбор обновлён', fm.text_listbox.sel == (0, 1) and fm.selected_text_files == ['a.txt', 'b.txt'])
fm.on_text_right_click(None)
check('правый клик: выбрано всё — выбор снимается', fm.text_listbox.sel == () and fm.selected_text_files == [])
fm = make(listbox=Listbox()); fm._scan_text_files = lambda: []; fm.on_text_right_click(None)
check('правый клик, когда файлов нет, — ничего не происходит', fm.selected_text_files == [])

# ===================== C. добавление в индекс: условия =====================
fm = make(); run_index(fm, [])
check('ничего не выбрано: предупреждение «Нет выбора», движок не трогается', calls('msg') == [('msg', 'showwarning', 'Нет выбора', "Выберите файлы в списке 'Файлы' (используйте Ctrl+клик или Shift+клик).")] and names() == ['msg'])
fm = make(); run_index(fm, ['книга.txt', 'нет_файла.txt', DB('нет_и_тут.txt')])
check('есть несуществующие файлы: ошибка со списком, ничего не индексируется и не показывается прогресс', calls('msg') == [('msg', 'showerror', 'Ошибка', 'Следующие файлы не найдены:\nнет_файла.txt\n' + DB('нет_и_тут.txt'))] and 'show' not in names() and 'list_indices' not in names(), str(LOG))

# ===================== D. Manticore =====================
fm = make(Engine('manticore')); run_index(fm, ['книга.txt'])
check('Manticore: прогресс показывается на N файлов, затем индекс создаётся по безопасному имени, файл идёт в индекс с настройками из конфигурации (разделитель N500)',
      calls('show') == [('show', ('initial', 0), ('max_value', 1), ('mode', 'determinate'))] and calls('create_index') == [('create_index', 'kniga')] and calls('index_text') == [('index_text', 'один\nдва\nтри', 'N500', 'книга.txt')], str(LOG))
check('имя индекса запомнено для показа под алиасом файла', fm.index_display_map == {'kniga': 'Книга'})
check('порядок вызовов: список индексов -> создание -> имя файла -> запись -> сброс имени -> статус -> прогресс -> скрыть -> обновить списки -> итог',
      names() == ['show', 'list_indices', 'create_index', 'file_name', 'index_text', 'file_name', 'status', 'update', 'hide', 'update_index_list', 'update_text_list', 'msg'], str(names()))
check('имя файла в движке выставляется на время записи и потом сбрасывается', calls('file_name') == [('file_name', 'книга.txt'), ('file_name', None)])
check('статус: время, имя под алиасом, число записей', calls('status')[0][1].startswith('Время создания индекса: ') and calls('status')[0][1].endswith("мс | Индекс 'Книга' создан (3 записей)") , calls('status')[0][1])
check('итог: «Обработано файлов: 1 / Успешно: 1»', summary() == 'Индексация завершена.\nОбработано файлов: 1\nУспешно: 1' and calls('msg')[-1][:3] == ('msg', 'showinfo', 'Результат индексации'), summary())
fm = make(Engine('manticore')); run_index(fm, ['a.txt'])
check('файла нет в настройках: имя — без расширения, разделитель — по умолчанию (N1000), индекс — по безопасному имени', fm.index_display_map == {'a': 'a'} and calls('index_text')[0][2] == 'N1000' and calls('create_index') == [('create_index', 'a')])
fm = make(Engine('manticore'), default_separator='===') ; run_index(fm, ['a.txt'])
check('разделитель по умолчанию берётся из настроек программы', calls('index_text')[0][2] == '===')
fm = make(Engine('manticore')); run_index(fm, [DB('таблица.xlsx')])
check('Excel из настроек: строки с подстрокой «служебная» исключены, разделитель из настроек (ExcelRow1)', calls('index_text') == [('index_text', 'Болт | 12\nГайка | 7', 'ExcelRow1', 'таблица.xlsx')], str(calls('index_text')))
fm = make(Engine('manticore')); run_index(fm, ['данные.xlsx']); write('данные.xlsx', '')
fm = make(Engine('manticore'), config={}); wb2 = openpyxl.Workbook(); wb2.active.append(['x', 1]); wb2.save(os.path.join(WORK, 'таблица2.xlsx')); run_index(fm, ['таблица2.xlsx'])
check('Excel, которого нет в настройках: разделитель «ExcelRow1» (одна строка — один топик), а не общий', calls('index_text') == [('index_text', 'x | 1', 'ExcelRow1', 'таблица2.xlsx')], str(calls('index_text')))
fm = make(Engine('manticore')); run_index(fm, [DB('доки.docx')])
check('.docx индексируется без пустых абзацев (в отличие от просмотра файла)', calls('index_text')[0][1] == 'Первый абзац\nТретий абзац', str(calls('index_text')))
fm = make(Engine('manticore')); run_index(fm, [DB('нота.txt')])
check('файл из DB: безопасное имя из имени файла', calls('create_index') == [('create_index', 'nota')])
fm = make(Engine('manticore', existing=['KNIGA'])); run_index(fm, ['книга.txt'])
check('индекс уже есть (сравнение без учёта регистра: Manticore хранит имена по-своему): вопрос «Перезаписать?» с номером файла', calls('msg')[0] == ('msg', 'askyesno', 'Перезапись', "Индекс 'Книга' уже существует. Перезаписать?\n(Файл 1 из 1)") and calls('create_index'), str(calls('msg')[:1]))
fm = make(Engine('manticore', existing=['kniga'])); Box.answers = {'askyesno': False}; fm.selected_text_files = ['книга.txt', 'a.txt']; LOG.clear(); fm.add_to_index(rec('show'), rec('update'), rec('hide'))
check('«Нет» на перезапись: файл пропущен (индекс не создаётся), прогресс всё равно двигается, остальные файлы идут дальше', [c[1] for c in calls('create_index')] == ['a'] and calls('update') == [('update', 1), ('update', 2)], str(calls('create_index')))
check('в итоге «обработано» считает и пропущенные, «успешно» — только проиндексированные', summary() == 'Индексация завершена.\nОбработано файлов: 2\nУспешно: 1', summary())
fm = make(Engine('manticore')); run_index(fm, ['книга.txt', 'a.txt', DB('нота.txt')])
check('несколько файлов: каждый по очереди, прогресс 1, 2, 3, скрытие и обновление списков один раз в конце', [c[1] for c in calls('create_index')] == ['kniga', 'a', 'nota'] and calls('update') == [('update', 1), ('update', 2), ('update', 3)] and names().count('hide') == 1 and names().count('update_index_list') == 1)

# ===================== E. Elastic и FTS5 =====================
fm = make(Engine('elasticsearch')); run_index(fm, ['книга.txt'])
check('Elastic: имя индекса с префиксом ms_ запоминается под алиасом', calls('create_index') == [('create_index', 'kniga')] and fm.index_display_map == {'ms_kniga': 'Книга'}, str(fm.index_display_map))
fm = make(Engine('elasticsearch', existing=['MS_KNIGA'])); run_index(fm, ['книга.txt'])
check('Elastic: уже существующий индекс определяется по имени с префиксом, без учёта регистра', calls('msg')[0][2] == 'Перезапись')
fm = make(Engine('fts5')); run_index(fm, ['книга.txt'])
check('FTS5: индекс называется по алиасу файла, разделитель из настроек, имя индексов движка не опрашивается', calls('create_index') == [('create_index', 'Книга')] and calls('index_text')[0][2] == 'N500' and 'list_indices' not in names() and fm.index_display_map == {})
fm = make(Engine('fts5')); os.makedirs('indicies_fts5', exist_ok=True); open(os.path.join('indicies_fts5', 'Книга.db'), 'w').write('x'); run_index(fm, ['книга.txt'])
check('FTS5: индекс уже есть (файл в indicies_fts5) — вопрос «Перезаписать?»', calls('msg')[0][2] == 'Перезапись')
os.remove(os.path.join('indicies_fts5', 'Книга.db')); open('Книга.db', 'w').write('x'); fm = make(Engine('fts5')); run_index(fm, ['книга.txt'])
check('FTS5: индекс уже есть (файл рядом с программой) — вопрос «Перезаписать?»', calls('msg')[0][2] == 'Перезапись'); os.remove('Книга.db')

# ===================== F. ошибки =====================
def errors_of(**kw):
    fm = make(Engine('manticore', **kw)); run_index(fm, kw.pop('files', ['книга.txt'])); return fm, summary()
fm = make(Engine('manticore')); run_index(fm, [DB('пустой.txt')])
check('файл из одних пробелов: ошибка «файл пуст», индекс не создаётся, прогресс двигается', 'create_index' not in names() and calls('update') == [('update', 1)] and 'пустой.txt: файл пуст' in summary() and 'Успешно: 0' in summary(), summary())
os.remove(os.path.join(WORK, 'DB', 'таблица.xlsx')); open(os.path.join(WORK, 'битый.xlsx'), 'w').write('не xlsx'); fm = make(Engine('manticore')); run_index(fm, ['битый.xlsx', 'a.txt'])
check('файл не читается: ошибка записана, остальные файлы идут дальше', 'битый.xlsx: ' in summary() and [c[1] for c in calls('create_index')] == ['a'] and 'Успешно: 1' in summary() and 'Ошибок: 1' in summary(), summary())
fm = make(Engine('manticore', fail_text=True)); run_index(fm, ['книга.txt', 'a.txt'])
check('сбой индексации: «ошибка индексации – …» в итоге, оба файла пробуются, успешных нет, статус об индексе не показывается', summary().count('ошибка индексации – сбой индексации') == 2 and 'Успешно: 0' in summary() and not calls('status'), summary())
fm = make(Engine('manticore', fail_create=True)); run_index(fm, ['книга.txt'])
check('нельзя создать индекс: та же ошибка, индекс под алиасом не запоминается', 'ошибка индексации – нельзя создать' in summary() and fm.index_display_map == {})
fm = make(Engine('manticore', fail_text=True)); files = []
for i in range(8): files.append(write(f'ош{i}.txt'))
run_index(fm, files)
check('в итоге — не больше 5 ошибок подробно, остальное «... и ещё N ошибок»', 'Ошибок: 8' in summary() and summary().count('ошибка индексации') == 5 and summary().endswith('... и ещё 3 ошибок'), summary()[-120:])

# ===================== G. журнал статистики =====================
stats_logger.STATS_ENABLED = True; stats_logger.log_index_creation = rec('log_index_creation')
fm = make(Engine('fts5')); os.makedirs('indicies_fts5', exist_ok=True)
class FtsEngine(Engine):
    def create_index(self, name):
        open(os.path.join('indicies_fts5', f'{name}.db'), 'wb').write(b'x' * 123); return super().create_index(name)
fm = make(FtsEngine('fts5')); run_index(fm, ['книга.txt']); kw = dict(calls('log_index_creation')[0][1:]) if calls('log_index_creation') else {}
check('журнал, FTS5: движок, имя файла, размеры файла и индекса (файл индекса), разделитель, число блоков, время', kw.get('engine_type') == 'fts5' and kw.get('source_filename') == 'книга.txt' and kw.get('file_size_bytes') == os.path.getsize('книга.txt')
      and kw.get('index_size_bytes') == 123 and kw.get('separator') == 'N500' and kw.get('blocks_count') == 3 and 'build_time_ms' in kw, str(kw))
os.makedirs('mdata', exist_ok=True); [open(os.path.join('mdata', f'kniga.{e}'), 'wb').write(b'y' * 10) for e in ('spd', 'spa', 'sph')]
fm = make(Engine('manticore', data_dir='mdata')); run_index(fm, ['книга.txt']); kw = dict(calls('log_index_creation')[0][1:])
check('журнал, Manticore: размер индекса — сумма файлов kniga.* в каталоге данных движка', kw.get('index_size_bytes') == 30 and kw.get('engine_type') == 'manticore', str(kw))
fm = make(Engine('elasticsearch')); run_index(fm, ['книга.txt']); kw = dict(calls('log_index_creation')[0][1:])
check('журнал, Elastic: размер индекса не определяется (0)', kw.get('index_size_bytes') == 0)
fm = make(Engine('manticore', fail_text=True)); run_index(fm, ['книга.txt'])
check('журнал при сбое индексации не пишется', not calls('log_index_creation'))
stats_logger.STATS_ENABLED = False

# ===================== H. известные ошибки =====================
write('~$lock.docx', 'служебный'); write('DB/~$lock2.docx', 'служебный')
scan = make()._scan_text_files()
check('служебные файлы Word (~$…, появляются, пока документ открыт в Word) в список файлов не попадают', not any(f.startswith('~$') for _d, f in scan), str([f for _d, f in scan if f.startswith('~$')]))
for et in ('manticore', 'fts5'):
    eng = Engine(et, fail_text=True); fm = make(eng); run_index(fm, ['книга.txt'])
    check(f'после сбоя индексации имя файла в движке ({et}) сбрасывается — чужие записи не получат имя этого файла', eng._cfn is None, f'осталось {eng._cfn!r}')
eng = Engine('manticore', list_raises=True); fm = make(eng); ev = []
try:
    run_index(fm, ['книга.txt', 'a.txt']); crashed = None
except Exception as e:
    crashed = e
check('движок не отвечает на список индексов: исключение не выходит наружу — прогресс скрыт, списки обновлены, итог с ошибками показан',
            crashed is None and 'hide' in names() and 'update_index_list' in names() and 'Ошибок: 2' in summary(), f'исключение {crashed!r}; вызовы {names()}')
# ===================== I. разбор подписи списка и таблица подписей =====================
pl = fmm.parse_listbox_entry
check('parse_listbox_entry: имя без алиаса, с алиасом, со скобками в имени и в алиасе, регистр расширения не важен', pl('a.txt') == 'a.txt' and pl('a.txt (Алиас)') == 'a.txt' and pl('a (1).txt') == 'a (1).txt'
      and pl('Отчёт (копия).docx (Алиас)') == 'Отчёт (копия).docx' and pl('нота.txt (Синод (старый))') == 'нота.txt' and pl('Книга.TXT (К)') == 'Книга.TXT' and pl('/файл.xlsx (Т)') == '/файл.xlsx')
check('parse_listbox_entry: двойное расширение и «расширение посреди имени» не режут имя', pl('x.txt.docx') == 'x.txt.docx' and pl('report.txt (copy).docx') == 'report.txt (copy).docx')
check('parse_listbox_entry: подпись не от файла (нет расширения) возвращается как есть', pl('что-то (там)') == 'что-то (там)')
lb = Listbox(); fm = make(listbox=lb, config={'x.txt (a).docx': ('Алиас', 'N', '')}); write('x.txt (a).docx', 'т'); fm.update_text_list = fmm.FileManager.update_text_list.__get__(fm); fm.update_text_list()
lb.sel = (lb.items.index('x.txt (a).docx (Алиас)'),); fm._update_selected_text_files()
check('патологическое имя «x.txt (a).docx» с алиасом: по таблице подписей выбирается ТОЧНО, без разбора текста', fm.selected_text_files == ['x.txt (a).docx'], str(fm.selected_text_files))
lb.sel = (); lb.items.append('чужая подпись.txt (Алиас)'); lb.sel = (len(lb.items) - 1,); fm._update_selected_text_files()
check('подписи нет в таблице (список заполнили не мы) — запасной разбор по расширению', fm.selected_text_files == ['чужая подпись.txt'])
os.remove('x.txt (a).docx'); fm.update_text_list(); check('при обновлении списка таблица подписей пересоздаётся (удалённый файл из неё уходит)', 'x.txt (a).docx (Алиас)' not in fm._listed_entries)
check('файл «служебный Word» определяется по «~$» в начале имени, регистр расширения не важен', fmm.FileManager._is_indexable_name('a.TXT') and not fmm.FileManager._is_indexable_name('~$a.docx') and not fmm.FileManager._is_indexable_name('a.pdf') and fmm.FileManager._is_indexable_name('a~$.txt'))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
