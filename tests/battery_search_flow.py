import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import re

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import services.search_controller as scm
import stats_logger
from vector_engines import CHUNK_BASED_MODEL_TYPES

# Оркестровка поиска (SearchController.do_search) проверяется в ИЗОЛЯЦИИ: тяжёлые внутренние шаги (отрисовка страницы,
# панель «Совпадения», векторный поиск, режим «**») заменены записью вызовов, а все собеседники — заглушки. Так видно
# ровно то, что решает do_search: что вызвать, с какими аргументами, в каком порядке и при каких условиях.
LOG = []
def rec(name, ret=None):
    return lambda *a, **k: (LOG.append((name,) + a + (tuple(sorted(k.items())) if k else ())), ret)[1]
def calls(name): return [c for c in LOG if c[0] == name]
def names(): return [c[0] for c in LOG]

class Box:
    def __getattr__(self, kind):
        if kind.startswith('__'): raise AttributeError(kind)
        return lambda title='', text='', *a, **k: LOG.append(('msg', kind, title, text)) or True
scm.messagebox = Box()
stats_logger.STATS_ENABLED = False

class Entry:
    def __init__(self, text=''): self.text = text
    def get(self): return self.text
class Pane:
    def __init__(self, tag): self.tag = tag; self.result_text = types_ns(delete=rec(tag + '.rt.delete'))
class WordPanel:
    def __init__(self, tag): self.clear = rec(tag + '.clear')
class Renderer:
    def __init__(self, tag):
        self.tag = tag; self.result_text = types_ns(delete=rec(tag + '.rt.delete'))
        self.render_help_text = rec(tag + '.help'); self.set_pane_label = rec(tag + '.label')
import types
def types_ns(**kw): return types.SimpleNamespace(**kw)
class Btn:
    def __init__(self): self.state = None
    def config(self, **kw): self.state = kw.get('state', self.state)
class IndexManager:
    index_display_map = {'idx_a': 'Таблица А', 'idx_b': 'Таблица Б', 'idx_book': 'Книга', 'idx_c': 'Таблица В'}
    def __init__(self, selected): self.selected = selected
    def get_selected_indices_ordered(self): return list(self.selected)
class VMM:
    def is_vector_key(self, key): return key in ('FT модель', 'MiniLM модель', 'FT вторая')
    def get_model_type(self, key): return 'minilm' if key == 'MiniLM модель' else 'fasttext'
class Engine:
    def __init__(self, engine_type='manticore', current='idx_book', results=None, raises=None):
        self.engine_type = engine_type; self._current_index = current; self.results = results if results is not None else {}; self.raises = raises
    def search(self, query, indices=None, **kw):
        LOG.append(('search', query, tuple(indices) if indices is not None else None, tuple(sorted(kw.items()))))
        if self.raises: raise self.raises
        return self.results.get(tuple(indices) if indices else None, self.results.get('*', []))

CONFIG_DICT = {'a.xlsx': ('Таблица А', '---', ''), 'b.xlsx': ('Таблица Б', '---', ''), 'c.xlsx': ('Таблица В', '---', ''), 'book.txt': ('Книга', 'N1000', '')}
RES = [{'meta': {'matched_words': ['слово'], 'max_level': 10}, 'text': 'слово тут', 'file': 'book.txt'}]
class Clock:
    """Детерминированные часы: каждый вызов time() на 13 мс позже предыдущего (время поиска = ровно 13 мс)."""
    def __init__(self, step=0.013): self.t = 0.0; self.step = step
    def time(self): v = self.t; self.t += self.step; return v
def search_with_clock(sc):
    real = scm.time; scm.time = Clock()
    try: sc.do_search()
    finally: scm.time = real

def make(query='слово', selected=('idx_book',), engine=None, vmm=None, split_enabled=False, with_split_panes=True, real_nav=False, hide=True):
    LOG.clear()
    engine = engine or Engine(results={'*': RES})
    sc = scm.SearchController(
        engine=engine, config={}, result_text=types_ns(delete=rec('rt.delete')), word_panel=WordPanel('wp'), query_entry=Entry(query),
        index_manager=IndexManager(selected), file_manager=None, status_update_callback=rec('status'),
        get_current_index_name_callback=lambda: 'текущий', config_dict=CONFIG_DICT, results_renderer=Renderer('r1'),
        results_renderer_2=Renderer('r2') if with_split_panes else None, word_panel_2=WordPanel('wp2') if with_split_panes else None,
        split_view_enabled_callback=(lambda: split_enabled), set_split_view_active_callback=rec('set_split'),
        vector_model_manager=vmm, hide_vector_viz_callback=rec('hide_viz') if hide else None)
    sc._apply_filter_and_display = rec('display', 7.0); sc._apply_filter_and_display_b = rec('display_b', 3.0)
    sc._update_word_panel_from_results = rec('wp_from'); sc._update_word_panel_from_results_b = rec('wp_from_b')
    sc._do_vector_search = rec('vector'); sc._do_single_file_browse = rec('browse')
    if not real_nav: sc._update_nav_buttons = rec('nav')
    return sc

# ===================== A. условия начала =====================
sc = make(engine=Engine(current=None)); sc.do_search()
check('индекс не выбран: предупреждение «Индекс не выбран.» и больше ничего (даже визуализация не скрывается)', LOG == [('msg', 'showwarning', 'Внимание', 'Индекс не выбран.')], str(LOG))
sc = make(); sc.engine = None; sc.do_search()
check('движка нет вовсе — то же предупреждение, без падения', LOG == [('msg', 'showwarning', 'Внимание', 'Индекс не выбран.')])
sc = make(); sc.do_search()
check('первым делом скрывается показанная визуализация (до чтения запроса)', names()[0] == 'hide_viz')
sc = make(hide=False); sc.do_search()
check('без колбэка скрытия визуализации поиск работает', calls('search'))

# ===================== B. короткий запрос =====================
for q in ('', 'а', ' а '):
    sc = make(q, real_nav=True); sc.btn_first, sc.btn_back, sc.btn_forward, sc.btn_last = Btn(), Btn(), Btn(), Btn()
    sc.excluded_words.add('x'); sc.is_viewing_file = True; sc.saved_state = {'k': 1}; sc.do_search()
    check(f'запрос {q!r} (короче 2 символов): справка, панель «Совпадения» очищена, исключения и состояние просмотра сброшены, поиска нет',
          calls('r1.help') and calls('wp.clear') and not calls('search') and sc.excluded_words == set() and sc.is_viewing_file is False and sc.saved_state == {}, str(LOG))
sc = make('ab'); sc.do_search()
check('запрос из двух символов проходит первый барьер, но в обычном режиме слова короче 3 символов отбрасываются: справка, без поиска', calls('r1.help') and not calls('search'))

# ===================== C. «**» и выход из режима просмотра =====================
sc = make('**'); sc.browse_mode = True; sc.browse_file_label = 'ф'; sc.all_filtered_topics = ['блок']; sc.do_search()
check('«**»: запускается просмотр файла, поиска нет, режим просмотра НЕ сбрасывается', names().count('browse') == 1 and not calls('search') and sc.browse_mode is True and sc.all_filtered_topics == ['блок'])
sc = make('слово'); sc.browse_mode = True; sc.browse_index = 'i'; sc.browse_file_label = 'ф'; sc.all_filtered_topics = ['блок']; sc.results_page = 3; sc.do_search()
check('любой другой запрос выводит из режима «**»: метка файла и блоки сброшены', sc.browse_mode is False and sc.browse_file_label is None and sc.all_filtered_topics == [] and sc.results_page == 0)

# ===================== D. исключённые слова: «продолжение» запроса =====================
def excl_after(prev, new):
    sc = make(new); sc._last_query = prev; sc.excluded_words.add('исключено'); sc.do_search(); return sc.excluded_words
check('дописывание слова сохраняет исключения (бог -> бога)', excl_after('бог', 'бога') == {'исключено'})
check('стирание сохраняет исключения (бога -> бо)', excl_after('бога', 'бо') == {'исключено'})
check('регистр не важен (бог -> БОГ)', excl_after('бог', 'БОГ') == {'исключено'})
check('другой запрос сбрасывает исключения (бог -> небо)', excl_after('бог', 'небо') == set())
check('первый запрос после запуска (прежнего нет) — продолжение: исключения не трогаются', excl_after('', 'слово') == {'исключено'})
sc = make('бог'); sc.do_search()
check('запрос запоминается для сравнения со следующим', sc._last_query == 'бог')

# ===================== E. обычный поиск =====================
sc = make('Бог создал', selected=('idx_book',)); search_with_clock(sc)
check('Manticore, один отмеченный индекс: engine.search(запрос, indices=[индекс], min_word_length=3)', calls('search') == [('search', 'Бог создал', ('idx_book',), (('min_word_length', 3),))], str(calls('search')))
check('слова запроса — в нижнем регистре; фрагменты для подсветки сохраняют регистр запроса (сопоставление потом без учёта регистра), без повторов', sc.current_query_words_lower == ['бог', 'создал'] and {'Бог', 'создал'} <= set(sc.current_partial_fragments) and len(sc.current_partial_fragments) == len(set(sc.current_partial_fragments)), str(sc.current_partial_fragments))
check('уровни всех фрагментов собраны (слово целиком — уровень 10, признак must_start)', ('создал', 10, False) in sc._last_all_fragments_levels and ('Бог', 10, False) in sc._last_all_fragments_levels, str(sc._last_all_fragments_levels))
check('результаты запомнены, панель «Совпадения» и страница обновлены в таком порядке', sc._full_topic_data == RES and names().index('wp_from') < names().index('display'))
check('перед поиском очищены окно результатов и панель «Совпадения»', names().index('wp.clear') < names().index('search') and names().index('rt.delete') < names().index('search'))
check('нет отдельного режима разделения: callback получил False', calls('set_split') == [('set_split', False)] and sc.split_mode_active is False)
status = calls('status')
check('итог в статусной строке: время ПОИСКА (13 мс) и время ВЫВОДА (7 мс) — каждое на своём месте', status and status[-1][1] == 'ПОИСК -13 мс  ВЫВОД РЕЗУЛЬТАТОВ -7 мс', str(status))
sc = make('Бог'); sc._typing_stats_str = 'Б,о,г'; sc._typing_total_ms = 1234.4; search_with_clock(sc)
check('со статистикой набора в статусе добавлена часть «ЗАПРОС-…»', calls('status')[-1][1] == "ЗАПРОС-1234 мс: 'Бог'='Б,о,г'  ПОИСК -13 мс  ВЫВОД РЕЗУЛЬТАТОВ -7 мс", str(calls('status')))
sc = make('слово', selected=()); sc.do_search()
check('ничего не отмечено (Manticore): ищется по текущему индексу движка', calls('search')[0][2] == ('idx_book',))
sc = make('слово', selected=('idx_a', 'idx_book')); sc.do_search()
check('несколько отмеченных — в порядке отметки', calls('search')[0][2] == ('idx_a', 'idx_book'))
sc = make('слово', engine=Engine('fts5', results={'*': RES})); sc.do_search()
check('движок FTS5: индексы не передаются (indices=None), панель индексов не опрашивается', calls('search')[0][2] is None)
sc = make('а б'); sc.do_search()
check('в запросе нет слов длиннее 2 символов: справка (после очистки окон), без поиска', calls('r1.help') and not calls('search') and names().index('rt.delete') < names().index('r1.help'))
sc = make('слово', engine=Engine(raises=RuntimeError('нет связи'))); sc.do_search()
check('ошибка движка: окно «Ошибка поиска: …», дальше ничего не происходит', calls('msg') == [('msg', 'showerror', 'Ошибка', 'Ошибка поиска: нет связи')] and not calls('display') and not calls('status'), str(LOG[-3:]))
sc = make('слово', engine=Engine(results={'*': []})); sc.do_search()
check('ничего не найдено: справка, обновление кнопок листания, панель очищена; страница не рисуется, статуса нет', calls('r1.help') and calls('nav') and not calls('display') and not calls('status'))

# ===================== F. после пустого поиска не должно оставаться старых результатов =====================
sc = make('слово', engine=Engine(results={'*': []}), real_nav=True); sc.btn_first, sc.btn_back, sc.btn_forward, sc.btn_last = Btn(), Btn(), Btn(), Btn()
sc.all_filtered_topics = [{'meta': {}, 'text': f't{i}'} for i in range(100)]; sc.results_page = 2; sc.do_search()
check('после поиска без результатов листание отключено, а результаты прошлого поиска сброшены (на экране справка)',
            sc.all_filtered_topics == [] and sc.results_page == 0 and sc.btn_forward.state == 'disabled' and sc.btn_back.state == 'disabled',
            f"осталось топиков {len(sc.all_filtered_topics)}, страница {sc.results_page}, «Вперёд»: {sc.btn_forward.state}, «Назад»: {sc.btn_back.state}")

# ----- F2. состояние сбрасывается на ВСЕХ путях, где экран пустеет; потребители состояния безопасны -----
def stale(**kw):
    sc = make(real_nav=True, **kw); sc.btn_first, sc.btn_back, sc.btn_forward, sc.btn_last = Btn(), Btn(), Btn(), Btn()
    sc.all_filtered_topics = ['x']; sc.all_filtered_topics_b = ['y']; sc._full_topic_data = ['z']; sc._full_topic_data_b = ['w']
    sc.word_counts = {'a': 1}; sc.word_counts_b = {'b': 1}; sc.all_topic_words = {'c': 1}; sc.results_page = 3
    return sc
def clean(sc): return (sc.all_filtered_topics, sc.all_filtered_topics_b, sc._full_topic_data, sc._full_topic_data_b, sc.word_counts, sc.word_counts_b, sc.all_topic_words, sc.results_page) == ([], [], [], [], {}, {}, {}, 0)
for label, kw in (('запрос короче 2 символов', dict(query='а')), ('в запросе нет слов длиннее 2 символов', dict(query='а б')),
                  ('ошибка движка', dict(query='слово', engine=Engine(raises=RuntimeError('сбой')))), ('поиск без результатов', dict(query='слово', engine=Engine(results={'*': []}))),
                  ('два файла, в обоих пусто', dict(query='Болт', selected=('idx_a', 'idx_b'), engine=Engine(results={('idx_a',): [], ('idx_b',): []}), split_enabled=True)),
                  ('FastText без обычного индекса (подсказка)', dict(query='слово', selected=('FT модель',), vmm=VMM()))):
    sc = stale(**kw); sc.do_search()
    check(f'старые результаты забыты: {label}', clean(sc), str((sc.all_filtered_topics, sc._full_topic_data, sc.results_page)))
sc = stale(query='слово', selected=('FT модель', 'idx_book'), vmm=VMM()); sc.do_search()
check('при запуске векторного поиска do_search состояние не трогает (его ведёт сам векторный поиск)', sc.all_filtered_topics == ['x'] and sc.results_page == 3 and calls('vector'))
sc = stale(query='слово', engine=Engine(results={'*': []})); sc.do_search(); LOG.clear()
try:
    sc.page_forward(); sc.go_to_last_page(); sc.go_to_first_page(); sc.page_back(lambda: None); sc.toggle_brief_mode(); sc.refresh_display(); sc.reset_exclusions(); ok = True; err = ''
except Exception as e:
    ok, err = False, repr(e)
check('после пустого поиска листание, «Кратко», обновление и сброс исключений безопасны: ничего, кроме справки, не рисуют', ok and set(names()) <= {'r1.help', 'nav'} and sc.results_page == 0, err or str(names()))
check('кнопки листания после пустого поиска выключены', sc.btn_forward.state == 'disabled' and sc.btn_back.state == 'disabled' and sc.btn_first.state == 'disabled' and sc.btn_last.state == 'disabled')

# ----- F3. выбор режима: SearchPlan -----
sc = make(selected=('FT модель', 'idx_a', 'idx_book'), vmm=VMM()); plan = sc._plan_search()
check('SearchPlan: отмеченные по порядку, первая модель, обычные индексы отдельно', (plan.selected_ordered, plan.vector_key, plan.real_indices, plan.indices_to_search) == (['FT модель', 'idx_a', 'idx_book'], 'FT модель', ['idx_a', 'idx_book'], ['FT модель', 'idx_a', 'idx_book']), str(plan))
sc = make(selected=(), vmm=VMM()); plan = sc._plan_search()
check('SearchPlan: ничего не отмечено (Manticore) — искать по текущему индексу движка, модели нет', (plan.selected_ordered, plan.indices_to_search, plan.vector_key, plan.real_indices) == ([], ['idx_book'], None, []), str(plan))
sc = make(selected=('idx_a',), engine=Engine('fts5')); plan = sc._plan_search()
check('SearchPlan: FTS5 — индексы не передаются, отметки не опрашиваются', (plan.selected_ordered, plan.indices_to_search, plan.vector_key) == ([], None, None), str(plan))
check('SearchPlan — именованный кортеж с полями selected_ordered, indices_to_search, vector_key, real_indices', scm.SearchPlan._fields == ('selected_ordered', 'indices_to_search', 'vector_key', 'real_indices'))

# ===================== G. векторные модели =====================
sc = make('слово', selected=('FT модель', 'idx_a', 'idx_book'), vmm=VMM()); sc.do_search()
check('FastText + обычные индексы: векторный поиск (запрос, модель, обычные индексы), обычный поиск не идёт', calls('vector') == [('vector', 'слово', 'FT модель', ['idx_a', 'idx_book'])] and not calls('search'), str(calls('vector')))
sc = make('слово', selected=('FT модель',), vmm=VMM()); sc.do_search()
check('FastText без обычного индекса: справка и подсказка «отметьте галочкой ещё и хотя бы один обычный индекс», поиска нет',
      calls('r1.help') and calls('nav') and not calls('vector') and not calls('search') and 'отметьте галочкой' in calls('status')[-1][1], str(LOG))
assert 'minilm' in CHUNK_BASED_MODEL_TYPES and 'fasttext' not in CHUNK_BASED_MODEL_TYPES, CHUNK_BASED_MODEL_TYPES  # условие, от которого зависят проверки ниже
sc = make('слово', selected=('MiniLM модель',), vmm=VMM()); sc.do_search()
check('MiniLM знает свой индекс: векторный поиск и без отмеченных обычных индексов', calls('vector') == [('vector', 'слово', 'MiniLM модель', [])], str(calls('vector')))
sc = make('слово', selected=('idx_a', 'FT модель', 'FT вторая', 'idx_book'), vmm=VMM()); sc.do_search()
check('несколько моделей: берётся первая, вторая как индекс не используется, порядок обычных индексов сохраняется', calls('vector') == [('vector', 'слово', 'FT модель', ['idx_a', 'idx_book'])], str(calls('vector')))
sc = make('слово', selected=('FT модель', 'idx_book'), vmm=None); sc.do_search()
check('(особенность) без менеджера векторных моделей ключ модели считается обычным индексом и уходит в поиск', calls('search')[0][2] == ('FT модель', 'idx_book') and not calls('vector'))
sc = make('слово', selected=('FT модель', 'idx_book'), vmm=VMM()); sc.do_search()
check('при векторном поиске окна результатов не очищаются самим do_search (это делает векторный поиск)', not calls('rt.delete') and not calls('set_split'))

# ===================== H. режим разделения (два Excel-файла) =====================
RES_A = [{'meta': {'matched_words': ['болт'], 'max_level': 10}, 'text': 'болт м12'}]; RES_B = [{'meta': {'matched_words': ['болт'], 'max_level': 9}, 'text': 'болт м10'}]
eng = lambda a=None, b=None: Engine(results={('idx_a',): RES_A if a is None else a, ('idx_b',): RES_B if b is None else b})
sc = make('Болт М 12', selected=('idx_a', 'idx_b'), engine=eng(), split_enabled=True); search_with_clock(sc)
check('два Excel-индекса и режим включён: разделение активно, callback получил True', sc.split_mode_active is True and calls('set_split') == [('set_split', True)])
check('поиск идёт отдельно по каждому файлу, с минимальной длиной слова 2 и «уникальным» рейтингом',
      calls('search') == [('search', 'Болт М 12', ('idx_a',), (('min_word_length', 2), ('unique_word_rating', True))), ('search', 'Болт М 12', ('idx_b',), (('min_word_length', 2), ('unique_word_rating', True)))], str(calls('search')))
check('в режиме разделения «М», «12» учитываются: слова запроса от 2 символов', sc.current_query_words_lower == ['болт', '12'], str(sc.current_query_words_lower))
check('очищены оба окна и обе панели «Совпадения»', all(calls(n) for n in ('wp.clear', 'wp2.clear', 'rt.delete', 'r2.rt.delete')))
check('подписи над окнами: «файл (алиас)» для каждого', [c[1] for c in calls('r1.label')] == ['a.xlsx (Таблица А)'] and [c[1] for c in calls('r2.label')] == ['b.xlsx (Таблица Б)'], str(calls('r1.label') + calls('r2.label')))
check('результаты обоих файлов запомнены и показаны, порядок: панели «Совпадения» -> страница', sc._full_topic_data == RES_A and sc._full_topic_data_b == RES_B and names().index('wp_from_b') < names().index('display'))
check('итог в статусе: поиск по ОБОИМ файлам — одним замером (13 мс), вывод — по верхнему окну (7 мс)', calls('status')[-1][1] == 'ПОИСК -13 мс  ВЫВОД РЕЗУЛЬТАТОВ -7 мс', str(calls('status')))
sc = make('Болт', selected=('idx_a', 'idx_b'), engine=eng([], []), split_enabled=True); sc.do_search()
check('в обоих файлах пусто: справка, страницы не рисуются', calls('r1.help') and not calls('display') and not calls('display_b'))
sc = make('Болт', selected=('idx_a', 'idx_b'), engine=eng([], None), split_enabled=True); sc.do_search()
check('пусто только в одном файле — всё равно показываются оба окна', calls('display') and calls('display_b') and not calls('r1.help'))
for label, kw in (('режим выключен в настройках', dict(selected=('idx_a', 'idx_b'), split_enabled=False)),
                  ('отмечен один индекс', dict(selected=('idx_a',), split_enabled=True)),
                  ('отмечено три индекса', dict(selected=('idx_a', 'idx_b', 'idx_c'), split_enabled=True)),
                  ('один из двух — не Excel', dict(selected=('idx_a', 'idx_book'), split_enabled=True)),
                  ('нет второго окна', dict(selected=('idx_a', 'idx_b'), split_enabled=True, with_split_panes=False))):
    sc = make('Болт', engine=Engine(results={'*': RES_A}), **kw); sc.do_search()
    check(f'разделения нет ({label}): обычный поиск, callback получил False', sc.split_mode_active is False and calls('set_split') == [('set_split', False)] and len(calls('search')) == 1 and not calls('display_b'), str(calls('set_split')))
sc = make('слово'); 
check('_is_excel_index: по алиасу из настроек (idx_a -> a.xlsx — Excel, idx_book -> book.txt — нет)', sc._is_excel_index('idx_a') and not sc._is_excel_index('idx_book'))
check('_is_excel_index: неизвестный индекс — по расширению самого имени, регистр не важен', sc._is_excel_index('данные.XLSX') and not sc._is_excel_index('данные.txt') and not sc._is_excel_index('нет_расширения'))
check('_format_index_file_label: «файл (алиас)» по имени индекса; неизвестный индекс — просто его имя', sc._format_index_file_label('idx_a') == 'a.xlsx (Таблица А)' and sc._format_index_file_label('неизвестный') == 'неизвестный', sc._format_index_file_label('неизвестный'))

# ===================== I. журнал статистики =====================
stats_logger.STATS_ENABLED = True
for fn in ('log_search', 'log_exclusions', 'log_typing_stats'): setattr(stats_logger, fn, rec(fn))
sc = make('слово', selected=('idx_a', 'idx_book')); sc.do_search()
ls = calls('log_search'); kw = dict(ls[0][1:]) if ls else {}
check('журнал: log_search(движок, запрос, «индекс1, индекс2», время)', len(ls) == 1 and kw.get('index_name') == 'idx_a, idx_book' and kw.get('query') == 'слово' and kw.get('engine_type') == 'manticore' and 'search_time_ms' in kw, str(ls))
check('журнал: исключения и статистика набора записаны', len(calls('log_exclusions')) == 1 and len(calls('log_typing_stats')) == 1)
sc = make('слово', engine=Engine('fts5', results={'*': RES})); sc.do_search()
check('журнал, FTS5 (индексы не передаются): имя индекса — текущий, как его называет окно', dict(calls('log_search')[0][1:])['index_name'] == 'текущий')
sc = make('Болт', selected=('idx_a', 'idx_b'), engine=eng(), split_enabled=True); sc.do_search()
check('журнал, разделение: «idx_a + idx_b (разделение)»', dict(calls('log_search')[0][1:])['index_name'] == 'idx_a + idx_b (разделение)')
sc = make('а'); sc.do_search()
check('журнал, короткий запрос: записываются только исключения', len(calls('log_exclusions')) == 1 and not calls('log_search'))
stats_logger.STATS_ENABLED = False
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
