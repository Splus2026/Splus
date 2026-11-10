import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import services.search_controller as scm
import stats_logger
stats_logger.STATS_ENABLED = False

# Подготовка страницы и фильтрация результатов: что именно уходит в отрисовщик и в панель «Совпадения». Заглушки записывают
# аргументы как есть (LOG), сами виджеты не нужны.
LOG = []
ns = types.SimpleNamespace
def names(): return [c[0] for c in LOG]
def calls(name): return [c for c in LOG if c[0] == name]
class Renderer:
    def __init__(self, tag=''): self.tag = tag
    def render_help_text(self): LOG.append((self.tag + 'help',))
    def render_blocks_page(self, topics): LOG.append((self.tag + 'blocks', list(topics)))
    def render_results_page_compact(self, topics, exact, partial, brief): LOG.append((self.tag + 'compact', list(topics), exact, partial, brief))
    def render_results_page(self, topics, **kw): LOG.append((self.tag + 'page', list(topics), kw))
    def render_error(self, text): LOG.append((self.tag + 'error', text))
class Panel:
    def __init__(self, tag=''): self.tag = tag
    def clear(self): LOG.append((self.tag + 'panel.clear',))
    def update_words(self, exact, prefix, counts, color): LOG.append((self.tag + 'panel.words', set(exact), dict(prefix), dict(counts), color))
class Btn:
    def __init__(self): self.state = None
    def config(self, **kw): self.state = kw.get('state', self.state)
CFG = {'book.txt': ('Книга', 'N1000', ''), 'plain.txt': ('plain.txt', 'N', ''), 'a.xlsx': ('Таблица', '-', '')}
def make(topics=(), page=0, split=False, brief=False, browse=False, config=None, current='idx_book', display_map=None, topics_b=(), words=('слово',), fragments=()):
    LOG.clear()
    sc = scm.SearchController(engine=ns(engine_type='manticore', _current_index='idx_book'), config=config or {}, result_text=ns(update_idletasks=lambda: LOG.append(('idle',))),
        word_panel=Panel(), query_entry=ns(get=lambda: 'слово'), index_manager=ns(index_display_map=display_map if display_map is not None else {'idx_book': 'Книга'}, get_selected_indices_ordered=lambda: []),
        file_manager=None, status_update_callback=lambda m: LOG.append(('status', m)), get_current_index_name_callback=lambda: current, config_dict=CFG,
        results_renderer=Renderer(), results_renderer_2=Renderer('2.'), word_panel_2=Panel('2.'))
    sc._update_nav_buttons = lambda: LOG.append(('nav',))
    sc.all_filtered_topics = list(topics); sc.all_filtered_topics_b = list(topics_b); sc.results_page = page; sc.split_mode_active = split; sc.brief_mode = brief
    sc.current_query_words_lower = list(words); sc.current_partial_fragments = list(fragments)
    if browse: sc.browse_mode = True; sc.browse_file_label = 'Книга'
    return sc
def T(i, level=10, count=1, words=('слово',), **kw): return {'rowid': i, 'content': f'текст {i}', 'file_name': kw.pop('file_name', 'book.txt'), 'meta': {'matched_words': list(words), 'max_level': level, 'count_at_max': count}, **kw}

# ===================== A. _display_page: ветки =====================
sc = make(); sc.is_viewing_file = True; sc.saved_state = {'k': 1}; r = sc._display_page(measure=True)
check('нет топиков: справка и кнопки листания; режим просмотра файла «застрявший» сбрасывается; с measure возвращается время', names() == ['help', 'nav'] and sc.is_viewing_file is False and sc.saved_state == {} and isinstance(r, float) and sc._display_page() is None)
topics = [T(i) for i in range(45)]
sc = make(topics, page=1); sc._display_page()
page = calls('page')[0]
check('страница 2 из 3: топики 20..39, сквозные номера start+i, параметры страницы', [t['global_idx'] for t in page[1]] == list(range(20, 40)) and page[2]['page_num'] == 1 and page[2]['total_count'] == 45, str(page[2]))
sc = make(topics, words=['слово'], fragments=['сл'], brief=True); sc._display_page(); kw = calls('page')[0][2]
check('в отрисовщик передаются слова для подсветки, фрагменты и режим «Кратко»', kw['exact_words'] == ['слово'] and kw['partial_fragments'] == ['сл'] and kw['brief_mode'] is True, str(kw))
sc = make(topics, page=2); sc._display_page(); check('последняя страница неполная: 5 топиков', [t['global_idx'] for t in calls('page')[0][1]] == list(range(40, 45)))
check('после страницы обновляются кнопки листания', names()[-1] == 'nav')
check('с measure=True возвращается время отрисовки', isinstance(make(topics)._display_page(measure=True), float))
sc = make(topics, page=1, browse=True); sc._display_page()
check('режим «**»: блоки без шапок, статус «блоков: 45, страница 2 из 3»', calls('blocks') and len(calls('blocks')[0][1]) == 20 and not calls('page') and ('status', '📄 Книга — блоков: 45, страница 2 из 3') in LOG, str(calls('status')))
sc = make(topics, split=True, config={'excel_split_page_size': 7}); sc._display_page()
check('режим разделения: компактный вывод, размер страницы из настройки excel_split_page_size (7)', calls('compact') and len(calls('compact')[0][1]) == 7 and not calls('page'), str(len(calls('compact')[0][1])) if calls('compact') else 'нет вывода')
sc = make(topics, split=True, config={'excel_split_page_size': 0}); sc._display_page()
check('размер страницы 0 в настройке заменяется на 20', len(calls('compact')[0][1]) == 20)
sc = make(topics, split=True, brief=True, words=['а'], fragments=['б']); sc._display_page()
check('компактный вывод получает слова, фрагменты и режим «Кратко»', calls('compact')[0][2:] == (['а'], ['б'], True))

# ===================== B. шапки топиков =====================
def header_of(topic, **kw):
    sc = make([topic], **kw); sc._display_page(); return calls('page')[0][1][0]
t1 = header_of(T(1, level=10, count=2))
check('обычный топик: «Файл: имя (алиас) | (уровень N, совп. M)»', t1['header'] == 'Файл: book.txt (Книга) | (уровень 10, совп. 2)' and t1['skip_header'] is False, t1['header'])
check('элемент для отрисовки: сквозной номер, rowid, текст, файл', (t1['global_idx'], t1['rowid'], t1['content'], t1['file_name']) == (0, 1, 'текст 1', 'book.txt'))
check('алиас совпадает с именем файла — показывается только имя', header_of(T(1, file_name='plain.txt'))['header'] == 'Файл: plain.txt | (уровень 10, совп. 1)')
check('файла нет в настройках — просто имя', header_of(T(1, file_name='other.txt'))['header'] == 'Файл: other.txt | (уровень 10, совп. 1)')
check('путь файла обрезается до имени', header_of(T(1, file_name='C:/папка/book.txt'))['header'].startswith('Файл: book.txt (Книга)'))
h = header_of(T(1, file_name='a.xlsx'))
check('Excel-топик: без шапки (одна строка — один топик), skip_header', h['header'] == '' and h['skip_header'] is True and h['file_name'] == 'a.xlsx')
sem = T(1, semantic_score=0.914); sem['meta'] = {}
check('семантический топик: вместо уровня — «семантическая близость N%»', header_of(sem)['header'] == 'Файл: book.txt (Книга) | (семантическая близость 91%)', header_of(sem)['header'])
nofile = T(1); nofile['file_name'] = ''
check('нет имени файла у топика: файл определяется по текущему индексу через его алиас', header_of(nofile)['file_name'] == 'book.txt' and header_of(nofile)['header'].startswith('Файл: book.txt (Книга)'))
check('нет имени файла и индекс неизвестен: подставляется имя текущего индекса', header_of(nofile, current='неизвестный', display_map={})['file_name'] == 'неизвестный')
check('топик без мета-данных — уровень 0, совп. 0', header_of({'rowid': 5, 'content': 'х', 'file_name': 'book.txt'})['header'].endswith('(уровень 0, совп. 0)'))

# ===================== C. второй файл (разделение) =====================
sc = make(topics_b=[T(i) for i in range(30)], page=1, split=True, words=['а'], fragments=['б'], brief=True); sc._display_page_b()
check('второй файл: компактный вывод в renderer_2, страница общая с первым, те же слова/фрагменты/«Кратко»', calls('2.compact') and len(calls('2.compact')[0][1]) == 10 and calls('2.compact')[0][2:] == (['а'], ['б'], True), str(calls('2.compact')[0][1:2]) if calls('2.compact') else '')
sc = make(split=True); sc._display_page_b()
check('второй файл пуст: «Нет результатов.» во втором окне', LOG == [('2.error', 'Нет результатов.')])
sc = make(topics_b=[T(1)]); sc.renderer_2 = None; sc._display_page_b()
check('нет второго окна — ничего не делает', LOG == [])

# ===================== D. фильтрация по исключённым словам и показ =====================
mixed = [T(1, level=5, count=1, words=['а']), T(2, level=10, count=1, words=['б']), T(3, level=10, count=3, words=['а', 'б']), T(4, level=7, count=9, words=['в'])]
sc = make(); shown = []; sc._display_page = lambda *a, **k: shown.append(list(sc.all_filtered_topics)) or 4.0
sc.is_viewing_file = True; sc.saved_state = {'k': 1}; sc.results_page = 5; r = sc._apply_filter_and_display(mixed, 12.0)
check('сортировка: по уровню, затем по числу совпадений на этом уровне, от лучшего', [t['rowid'] for t in shown[0]] == [3, 2, 4, 1], str([t['rowid'] for t in shown[0]]))
check('страница сброшена на 0, просмотр файла сброшен, возвращается время показа', sc.results_page == 0 and sc.is_viewing_file is False and sc.saved_state == {} and r == 4.0)
sc = make(); sc._display_page = lambda *a, **k: 1.0; sc.excluded_words.update({'а'}); sc._apply_filter_and_display(mixed, 1.0)
check('исключённое слово скрывает топик, только если ВСЕ его совпавшие слова исключены (топик 3 с «а» и «б» остаётся)', sorted(t['rowid'] for t in sc.all_filtered_topics) == [2, 3, 4], str(sorted(t['rowid'] for t in sc.all_filtered_topics)))
sc = make(); sc._display_page = lambda *a, **k: 1.0; sc._apply_filter_and_display([{'rowid': 1, 'meta': {'matched_words': []}}, {'rowid': 2}], 1.0)
check('(особенность) топик без совпавших слов отфильтровывается всегда, даже без исключений', sc.all_filtered_topics == [])
sc = make(); sc.excluded_words.update({'а', 'б', 'в'}); r = sc._apply_filter_and_display(mixed, 1.0)
check('исключены все слова: справка и кнопки листания, страница не рисуется, возвращается 0.0', 'help' in names() and 'nav' in names() and not calls('page') and r == 0.0 and sc.all_filtered_topics == [])
sc = make(); sc.word_counts = {'слово': 2}; sc._apply_filter_and_display([T(1)], 1.0)
check('панель «Совпадения» обновляется при показе', calls('panel.words'))
sc = make(); sc._display_page = lambda *a, **k: 1.0; sc.excluded_words.update({'а'}); sc._apply_filter_and_display_b(mixed)
check('второй файл: тот же фильтр по исключённым словам, сортировка и показ на втором окне', sorted(t['rowid'] for t in sc.all_filtered_topics_b) == [2, 3, 4] and [t['rowid'] for t in sc.all_filtered_topics_b][:1] == [3])
sc = make(); sc.excluded_words.update({'а', 'б', 'в'}); sc._apply_filter_and_display_b(mixed)
check('второй файл, всё исключено: «Нет результатов.» во втором окне', calls('2.error') == [('2.error', 'Нет результатов.')] and sc.all_filtered_topics_b == [])

# ===================== E. «обновить после исключения слова» =====================
sc = make(); sc.refresh_display()
check('нет данных последнего поиска — ничего не делает', LOG == [])
sc = make(); sc._full_topic_data = mixed; sc.excluded_words.update({'а'}); sc.results_page = 9; sc.refresh_display()
check('исключили слово: топики пересчитаны, страница подрезана до существующей, страница нарисована, панель и экран обновлены', sorted(t['rowid'] for t in sc.all_filtered_topics) == [2, 3, 4] and sc.results_page == 0 and calls('page') and calls('idle'), str(names()))
sc = make(); sc._full_topic_data = mixed; sc.excluded_words.update({'а', 'б', 'в'}); sc.refresh_display()
check('исключили всё: справка, кнопки, панель; страница не рисуется', 'help' in names() and 'nav' in names() and not calls('page'))
sc = make(split=True); sc._full_topic_data = mixed; sc._full_topic_data_b = mixed; sc.excluded_words.update({'а'}); sc.refresh_display()
check('в режиме разделения обновляется и второй файл (исключения общие)', sorted(t['rowid'] for t in sc.all_filtered_topics_b) == [2, 3, 4])
sc = make(); sc._full_topic_data = mixed; sc._full_topic_data_b = mixed; sc.excluded_words.update({'а'}); sc.refresh_display()
check('без режима разделения второй файл не трогается', sc.all_filtered_topics_b == [])
sc = make(); sc._full_topic_data = mixed; sc.excluded_words.update({'а'}); sc.reset_exclusions()
check('«сбросить исключения»: список пуст, все топики снова показаны', sc.excluded_words == set() and len(sc.all_filtered_topics) == 4)

# ===================== F. панель «Совпадения» =====================
sc = make(words=['слово']); sc.word_counts = {'слово': 3, 'словарь': 1, 'словом': 4, 'ово': 2}; sc._last_all_fragments_levels = [('слов', 8, False), ('сло', 6, False), ('ово', 5, False)]; sc._update_word_panel()
p = calls('panel.words')[0]
check('панель: точное слово запроса — только по РАВЕНСТВУ («словом», начинающееся так же, — не точное); для прочих — самая длинная подходящая часть запроса', p[1] == {'слово'} and p[2] == {'словарь': 'слов', 'словом': 'слов', 'ово': 'ово'} and p[3] == {'слово': 3, 'словарь': 1, 'словом': 4, 'ово': 2} and p[4] == 'blue', str(p))
sc = make(); sc.word_counts = {}; sc._update_word_panel()
check('нет слов — панель очищается', LOG == [('panel.clear',)])
sc = make(words=['слово']); sc.word_counts_b = {'слово': 1, 'словарь': 2}; sc._last_all_fragments_levels = [('слов', 8, False)]; sc._update_word_panel_b()
check('панель второго файла считается так же, по своим счётчикам', calls('2.panel.words')[0][1:] == ({'слово'}, {'словарь': 'слов'}, {'слово': 1, 'словарь': 2}, 'blue'))
sc = make(); sc.word_panel_2 = None; sc.word_counts_b = {'а': 1}; sc._update_word_panel_b()
check('нет второй панели — ничего не делает', LOG == [])
sc = make(); sc.word_counts_b = {}; sc._update_word_panel_b()
check('второй файл без слов — вторая панель очищается', LOG == [('2.panel.clear',)])
sc = make(); sc._update_word_panel_from_results([T(1, level=5, words=['а', 'б']), T(2, level=9, words=['а'])])
check('счётчики слов и лучший уровень каждого слова', sc.word_counts == {'а': 2, 'б': 1} and sc.all_topic_words == {'а': 9, 'б': 5}, str((sc.word_counts, sc.all_topic_words)))
check('уровни фрагментов пересчитываются из запроса в поле ввода', ('слово', 10, False) in sc._last_all_fragments_levels)
sc = make(); sc._update_word_panel_from_results_b([T(1, words=['а', 'б']), T(2, words=['а'])])
check('счётчики слов второго файла (без уровней — они общие)', sc.word_counts_b == {'а': 2, 'б': 1})
sc = make(); sc._display_page = lambda *a, **k: LOG.append(('displayed',)); r = sc.toggle_brief_mode()
check('«Кратко»: переключает режим, перерисовывает страницу, возвращает новое значение', r is True and sc.brief_mode is True and calls('displayed'))
sc = make(); sc.is_viewing_file = True; sc._display_page = lambda *a, **k: LOG.append(('displayed',)); sc.toggle_brief_mode()
check('«Кратко» при просмотре файла страницу результатов не перерисовывает', sc.brief_mode is True and not calls('displayed'))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
