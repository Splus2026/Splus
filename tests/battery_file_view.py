import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import re, types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import services.search_controller as scm
import stats_logger

# Просмотр файла по гиперссылке: клик по заголовку топика -> поиск файла на диске -> показ нужного места с подсветкой -> «назад к
# результатам». Файлы настоящие (во временной папке, она же — рабочая: пути «DB/…» разрешаются от неё), отрисовщик — запись вызовов.
WORK = env.tmpdir('fileview_'); os.chdir(WORK); os.makedirs('DB')
LOG = []
ns = types.SimpleNamespace
def rec(name, ret=None): return lambda *a, **k: (LOG.append((name,) + a + (tuple(sorted(k.items())) if k else ())), ret)[1]
def calls(name): return [c for c in LOG if c[0] == name]
def names(): return [c[0] for c in LOG]
class Box:
    def __getattr__(self, kind):
        if kind.startswith('__'): raise AttributeError(kind)
        return lambda title='', text='', *a, **k: LOG.append(('msg', kind, title, text)) or True
scm.messagebox = Box(); stats_logger.STATS_ENABLED = False
class Renderer:
    def render_file_content(self, content, back, file_name=''): LOG.append(('content', content, back, file_name)); return 7
    def scroll_to_file_position(self, line, col): LOG.append(('scroll', line, col))
    def apply_highlights(self, intervals, offset): LOG.append(('hl', [list(i) for i in intervals], offset)); return len(intervals)
    def render_error(self, text): LOG.append(('error', text))
    def scroll_to_topic(self, rowid, global_idx): LOG.append(('scroll_topic', rowid, global_idx))
    def render_help_text(self): LOG.append(('help',))
class Engine:
    engine_type = 'manticore'; _current_index = 'idx'
    def __init__(self, sections=None, raises=None): self.sections = sections or {}; self.raises = raises
    def get_section_info(self, rowid):
        LOG.append(('get_section_info', rowid))
        if self.raises: raise self.raises
        return self.sections.get(rowid)
CFG_BASES = {'book.txt': ('Книга', 'N', ''), 'alias.txt': ('Псевдоним', 'N', ''), 'sub/deep.txt': ('Глубокий', 'N', '')}
def make(topics=(), config=None, engine=None, words=('слово',), fragments=()):
    LOG.clear()
    sc = scm.SearchController(engine=engine or Engine(), config=config or {}, result_text=None, word_panel=None, query_entry=None, index_manager=ns(index_display_map={}),
        file_manager=None, status_update_callback=rec('status'), get_current_index_name_callback=lambda: 'idx', config_dict=CFG_BASES, results_renderer=Renderer())
    sc._update_nav_buttons = rec('nav'); sc.all_filtered_topics = list(topics); sc.current_query_words_lower = list(words); sc.current_partial_fragments = list(fragments)
    return sc
def write(rel, text):
    os.makedirs(os.path.dirname(os.path.join(WORK, rel)) or WORK, exist_ok=True); open(os.path.join(WORK, rel), 'w', encoding='utf-8', newline='').write(text); return rel
LINES = [f'Строка {i}: слово{i} текст' for i in range(1, 11)]
BOOK = '\n'.join(LINES)
write('DB/book.txt', BOOK)

# ===================== A. клик по заголовку =====================
def click(tags, x=10, y=20):
    sc = make(); sc.result_text = ns(index=lambda spec: LOG.append(('index', spec)) or '1.0', tag_names=lambda idx: tags); sc._open_file_for_topic = rec('open'); sc.on_hyperlink_click(ns(x=x, y=y)); return sc
click(['sel', 'block_3_17'])
check('клик: позиция мыши переводится в индекс виджета, тег block_<номер>_<rowid> открывает файл топика (rowid, номер в списке)', calls('index') == [('index', '@10,20')] and calls('open') == [('open', 17, 3)], str(LOG))
click(['block_x_17']); check('номер в списке не число — файл всё равно открывается, номер = None', calls('open') == [('open', 17, None)])
click(['block_1_2_3']); check('тег неверного вида (4 части) игнорируется', not calls('open'))
click(['sel', 'current']); check('на заголовке нет тега блока — ничего не происходит', not calls('open'))
click(['block_0_5', 'block_1_6']); check('несколько тегов блока — открывается первый', calls('open') == [('open', 5, 0)])

# ===================== B. какой файл открыть =====================
def topic(rowid, file_name='book.txt', position='0', content='', **kw): return {'rowid': rowid, 'file_name': file_name, 'position': position, 'content': content, **kw}
def open_topic(sc, rowid, global_idx=None):
    sc._display_file_content = rec('display'); LOG.clear(); sc._open_file_for_topic(rowid, global_idx); return calls('display')
sc = make([topic(1, content='первый'), topic(2, content='второй', position='4')], config={'highlight_context_size': 300, 'max_display_chars': 999})
d = open_topic(sc, 2, 1)
check('топик берётся из списка результатов по номеру и rowid; в просмотр уходят путь, позиция, слова, фрагменты, текст топика, имя файла, настройки подсветки', d == [('display', os.path.join('DB', 'book.txt'), '4', ['слово'], [], 'второй', 'book.txt', 300, 999, ('global_idx', 1), ('rowid', 2))], str(d))
sc = make([topic(1, content='первый'), topic(2, content='второй')])
d = open_topic(sc, 1, 1)
check('номер указывает на топик с ДРУГИМ rowid — берётся первый топик с таким rowid', len(d) == 1 and d[0][5] == 'первый', str(d))
d = open_topic(sc, 2, None)
check('номера нет — поиск по rowid', len(d) == 1 and d[0][5] == 'второй')
d = open_topic(make([topic(1), topic(1, content='дубль')]), 1, 1)
check('rowid совпадает у топиков из разных индексов: решает номер в списке, а не только rowid', len(d) == 1 and d[0][5] == 'дубль', str(d))
d = open_topic(make([topic(1)]), 1, 99)
check('номер вне списка — запасной поиск по rowid', len(d) == 1)
sc = make([topic(1, content='т')]); d = open_topic(sc, 1, 0)
check('настройки подсветки по умолчанию: контекст 500, окно 50 000 символов (из self.config, не из словаря баз)', d[0][6:8] == ('book.txt', 500) and d[0][8] == 50000, str(d))
sc = make(engine=Engine({5: {'file_name': 'book.txt', 'position': '2', 'text': 'из индекса'}})); d = open_topic(sc, 5, 0)
check('топика нет в результатах — данные берутся из индекса движка (get_section_info)', calls('get_section_info') == [('get_section_info', 5)] and d[0][2:] and d[0][2] == '2' and d[0][5] == 'из индекса', str(LOG))
sc = make(engine=Engine({5: {'file_name': 'book.txt'}})); d = open_topic(sc, 5, 0)
check('в данных индекса нет позиции и текста — подставляются «0» и пустая строка', len(d) == 1 and d[0][2] == '0' and d[0][5] == '', str(d))
sc = make(engine=Engine({})); open_topic(sc, 5, 0)
check('и в индексе нет: «Не удалось получить информацию о топике N», просмотр не открывается', calls('msg') == [('msg', 'showerror', 'Ошибка', 'Не удалось получить информацию о топике 5')] and not calls('display'), str(LOG))
sc = make([{'rowid': 1, 'content': 'т'}]); open_topic(sc, 1, 0)
check('у топика нет имени файла: сообщение «Для этого топика не сохранено имя файла.»', calls('msg') == [('msg', 'showinfo', 'Информация', 'Для этого топика не сохранено имя файла.')] and not calls('display'), str(LOG))
d = open_topic(make([{'rowid': 1, 'file_name': 'book.txt'}]), 1, 0)
check('нет позиции — «0», нет текста — пустая строка', d[0][2] == '0' and d[0][5] == '')
sc = make([topic(1)], engine=Engine(raises=RuntimeError('x'))); sc.all_filtered_topics = []; open_topic(sc, 1, None)
check('сбой при получении данных: «Не удалось открыть файл: …» (исключение не выходит наружу)', calls('msg') == [('msg', 'showerror', 'Ошибка', 'Не удалось открыть файл: x')] and not calls('display'), str(LOG))

# ===================== C. где лежит файл =====================
def resolved(file_name, **kw):
    d = open_topic(make([topic(1, file_name=file_name)]), 1, 0); return d[0][1] if d else None
write('DB/только_в_db.txt', 'а'); write('в_корне.txt', 'б'); write('DB/общий.txt', 'в DB'); write('общий.txt', 'в корне'); write('DB/сам/вложенный.txt', 'г'); write('вне_db.txt', 'д')
check('имя файла как есть (путь от рабочей папки)', resolved('в_корне.txt') == 'в_корне.txt')
check('в папке DB', resolved('только_в_db.txt') == os.path.join('DB', 'только_в_db.txt'))
check('путь с подпапкой относительно DB', resolved('сам/вложенный.txt') == os.path.join('DB', 'сам/вложенный.txt'))
check('(особенность) файл с тем же именем в рабочей папке и в DB: берётся файл из рабочей папки, DB — следующий', resolved('общий.txt') == 'общий.txt')
check('путь с чужой машины находится по имени файла в DB', resolved('C:/другой/компьютер/только_в_db.txt') == os.path.join('DB', 'только_в_db.txt'))
check('путь с чужой машины находится по имени файла в рабочей папке', resolved('D:/где-то/в_корне.txt') == 'в_корне.txt')
write('DB/alias_target.txt', 'х'); CFG_BASES['alias_target.txt'] = ('Красивое имя', 'N', '')
check('имя файла = алиас из настроек: файл находится по ключу настройки (в DB)', resolved('Красивое имя') == os.path.join('DB', 'alias_target.txt'))
write('вне_папок/лежит.txt', 'и'); CFG_BASES[os.path.join(WORK, 'вне_папок', 'лежит.txt')] = ('Лежит где угодно', 'N', '')
check('в настройках путь к файлу абсолютный — он и используется', resolved('Лежит где угодно') == os.path.join(WORK, 'вне_папок', 'лежит.txt'))
check('в настройках путь абсолютный, а топик хранит только имя файла: файл находится по имени из ключа настройки', resolved('лежит.txt') == os.path.join(WORK, 'вне_папок', 'лежит.txt'), str(resolved('лежит.txt')))
d = open_topic(make([topic(1, file_name='нет_такого_файла.txt')]), 1, 0)
check('файл нигде нет: «Файл не найден: имя», просмотр не открывается', not d and calls('msg') == [('msg', 'showerror', 'Ошибка', 'Файл не найден: нет_такого_файла.txt')], str(LOG))
CFG_BASES['нет_на_диске.txt'] = ('Есть в настройках', 'N', '')
d = open_topic(make([topic(1, file_name='Есть в настройках')]), 1, 0)
check('файл есть в настройках, но на диске нет — «Файл не найден»', not d and calls('msg') and calls('msg')[0][3] == 'Файл не найден: Есть в настройках')

# ===================== D. показ файла =====================
def view(path='DB/book.txt', position='0', topic_text='', words=('слово',), fragments=(), file_name='book.txt', context=500, max_chars=50000, rowid=3, global_idx=2, topics=(), page=0, **kw):
    sc = make(topics, words=words, fragments=fragments); sc.results_page = page
    sc._display_file_content(path, position, list(words), list(fragments), topic_text, file_name, context, max_chars, rowid=rowid, global_idx=global_idx); return sc
sc = view(topic_text=LINES[3] + '\n' + LINES[4], topics=[topic(1), topic(2)], page=1)
check('состояние результатов сохранено ДО показа файла (копии списков), просмотр включён, метка файла «имя (алиас)»',
      sc.is_viewing_file is True and sc.saved_state['results_page'] == 1 and sc.saved_state['clicked_rowid'] == 3 and sc.saved_state['clicked_global_idx'] == 2 and len(sc.saved_state['all_filtered_topics']) == 2
      and sc.saved_state['all_filtered_topics'] is not sc.all_filtered_topics and sc.saved_state['current_query_words_lower'] == ['слово'] and sc._current_view_file_label == 'book.txt (Книга)', str(sc.saved_state))
c = calls('content')[0]
check('файл целиком отдан отрисовщику с обработчиком «назад к результатам» и именем файла', c[1] == BOOK and c[2] == sc._back_to_results_from_file and c[3] == 'book.txt')
check('прокрутка — на строку и столбец топика (топик начинается с 4-й строки)', calls('scroll') == [('scroll', 4, 0)], str(calls('scroll')))
hl = calls('hl')[0]
check('подсветка вычислена по тексту файла и применена со смещением, которое вернул отрисовщик (7)', hl[2] == 7 and len(hl[1]) == 10 and all(i[2] == 'highlight' for i in hl[1]), str(hl)[:200])
st = calls('status')
check('статус: время открытия, размер файла, область, число тегов', st and re.fullmatch(r'Время открытия файла: \d+ мс \| Размер 0\.00 МБ \| Область %d симв\. \| Подсветка 10 тегов' % len(BOOK), st[-1][1]), str(st))
check('после показа обновляются кнопки листания', names()[-1] == 'nav' and 'error' not in names())
sc = view(topic_text='такого текста в файле нет', position='0')
check('топик в файле не найден, позиции нет: показ с начала файла (строка 1)', calls('scroll') == [('scroll', 1, 0)] and calls('content')[0][1] == BOOK)
sc = view(topic_text='такого нет', position='6')
check('топик не найден, но известен номер строки (.txt): прокрутка на строку 7 с отступом по символам', calls('scroll') == [('scroll', 7, 0)], str(calls('scroll')))
write('DB/пустой.txt', ''); sc = view(path='DB/пустой.txt', file_name='пустой.txt')
check('пустой файл: показывается без ошибки, прокрутка на начало', calls('content')[0][1] == '' and calls('scroll') == [('scroll', 1, 0)] and not calls('error'), str(LOG)[:200])
sc = view(path='DB/нет_файла.txt', file_name='нет_файла.txt', topics=[topic(1)], page=2)
check('файл не прочитался: в окне «Ошибка загрузки файла: …», просмотр выключен, сохранённое состояние сброшено, кнопки не трогаются',
      calls('error') and calls('error')[0][1].startswith('Ошибка загрузки файла:') and sc.is_viewing_file is False and sc.saved_state == {} and not calls('nav') and not calls('content'), str(LOG)[:300])
from docx import Document
d_ = Document(); [d_.add_paragraph(t) for t in ('Первый абзац', '', 'Третий слово абзац')]; d_.save(os.path.join(WORK, 'DB', 'доки.docx'))
sc = view(path='DB/доки.docx', file_name='доки.docx', topic_text='Третий слово абзац')
check('.docx: читается как текст (пустые абзацы сохранены), топик найден на 3-й строке', calls('content')[0][1] == 'Первый абзац\n\nТретий слово абзац' and calls('scroll') == [('scroll', 3, 0)], str(LOG)[:200])
stats_logger.STATS_ENABLED = True; stats_logger.log_file_open = rec('log_file_open')
sc = view(topic_text=LINES[3]); kw = dict(calls('log_file_open')[0][1:]) if calls('log_file_open') else {}
check('журнал статистики: путь, этапы, размер, область, число интервалов и тегов', kw.get('file_path') == 'DB/book.txt' and kw.get('display_size_chars') == len(BOOK) and kw.get('tags_applied') == 10 and kw.get('intervals_found') == 10 and 'total_time_ms' in kw and 'file_size_mb' in kw, str(kw))
stats_logger.STATS_ENABLED = False

# окно просмотра большого файла
BIG_LINES = [f'Строка {i:05d} слово{i}' for i in range(6000)]; BIG = '\n'.join(BIG_LINES); write('DB/big.txt', BIG)
def big(topic_text, **kw):
    sc = view(path='DB/big.txt', file_name='big.txt', topic_text=topic_text, **kw); return sc, calls('content')[0][1]
sc, shown = big(BIG_LINES[3000])
check('большой файл: показывается окно ровно в 50 000 символов, центрированное на топике, топик внутри', len(shown) == 50000 and BIG_LINES[3000] in shown and shown.find(BIG_LINES[3000]) == 25000, f'{len(shown)} символов, топик на месте {shown.find(BIG_LINES[3000])}')
check('прокрутка в окне считается от НАЧАЛА окна, а не файла', calls('scroll')[0][1] == shown[:shown.find(BIG_LINES[3000])].count('\n') + 1, str(calls('scroll')))
sc, shown = big(BIG_LINES[5990])
check('топик в конце большого файла: окно прижато к концу (последние 50 000 символов)', shown == BIG[-50000:])
sc, shown = big(BIG_LINES[3000], max_chars=0)
check('предел 0 — файл показывается целиком', shown == BIG)
sc, shown = big(BIG_LINES[3000], max_chars=len(BIG) + 1)
check('файл не больше предела — целиком', shown == BIG)
sc, shown = big(BIG_LINES[20] + '\n' + BIG_LINES[21])
check('топик недалеко от начала большого файла (внутри первой половины окна): окно начинается с начала файла', shown == BIG[:50000], shown[:30])
sc, shown = big(BIG_LINES[0] + '\n' + BIG_LINES[1])
check('топик в самом НАЧАЛЕ большого файла (позиция 0): показывается начало файла, а не его середина', shown == BIG[:50000], f"показано окно, начинающееся с «{shown[:22]}»")
sc, shown = big('такого текста в файле нет')
check('топик не найден, позиция неизвестна: большой файл показывается С НАЧАЛА (как и маленький), а не с середины', shown == BIG[:50000], f"показано окно, начинающееся с «{shown[:22]}»")

# ===================== E. назад к результатам =====================
sc = make(); sc._display_page = rec('display_page'); sc._back_to_results_from_file()
check('не в режиме просмотра файла — ничего не происходит', LOG == [])
topics = [topic(1), topic(2)]
sc = view(topic_text=LINES[3], topics=topics, page=1, rowid=2, global_idx=1)
sc.all_filtered_topics = []; sc.results_page = 9; sc.current_query_words_lower = ['другое']; sc.current_partial_fragments = ['д']; sc._display_page = rec('display_page'); LOG.clear()
sc._back_to_results_from_file()
check('возврат: результаты, страница, слова и фрагменты восстановлены из сохранённого состояния; просмотр выключен, сохранённое сброшено',
      sc.all_filtered_topics == topics and sc.results_page == 1 and sc.current_query_words_lower == ['слово'] and sc.current_partial_fragments == [] and sc.is_viewing_file is False and sc.saved_state == {})
check('возврат: страница перерисована, кнопки обновлены, прокрутка к топику, на который кликнули (rowid и номер)', names() == ['display_page', 'nav', 'scroll_topic'] and calls('scroll_topic') == [('scroll_topic', 2, 1)], str(names()))
sc = view(topic_text=LINES[3], rowid=None, global_idx=None); sc._display_page = rec('display_page'); LOG.clear(); sc._back_to_results_from_file()
check('кликнутого топика нет (rowid=None) — прокрутки к топику нет', 'scroll_topic' not in names() and names() == ['display_page', 'nav'])
sc = make(); sc.is_viewing_file = True; sc.saved_state = {}; sc._display_page = rec('display_page'); sc._back_to_results_from_file()
check('сохранённого состояния нет — подставляются пустые значения, без падения', sc.all_filtered_topics == [] and sc.results_page == 0 and sc.current_query_words_lower == [] and calls('display_page'))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
