import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

import services.search_controller as scm
import stats_logger

# Поиск по векторным моделями: FastText (_do_vector_search: близкие слова + обычный поиск ими) и MiniLM (_do_semantic_search:
# модель сразу возвращает топики). Собеседники — заглушки, всё, что они получили, записывается в LOG.
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
class Btn:
    def __init__(self): self.state = None
    def config(self, **kw): self.state = kw.get('state', self.state)
class VMM:
    def __init__(self, neighbors=(), matches=(), assoc=('idx_a',), mtype='fasttext'):
        self.neighbors, self.matches, self.assoc, self.mtype = list(neighbors), list(matches), set(assoc), mtype
    def get_model_type(self, key): return self.mtype
    def get_neighbors(self, key, word): LOG.append(('neighbors', key, word)); return self.neighbors
    def get_neighbors_deduplicated(self, key, word): LOG.append(('neighbors_dedup', key, word)); return self.neighbors
    def search_semantic(self, key, query, topn=None): LOG.append(('semantic', key, query, topn)); return self.matches
    def get_associated_indices(self, key): return list(self.assoc)
class Engine:
    engine_type = 'manticore'; _current_index = 'idx_a'
    def __init__(self, results=None, raises=None, sections=None): self.results = results or []; self.raises = raises; self.sections = sections or {}
    def search(self, q, indices=None, **kw):
        LOG.append(('search', q, tuple(indices) if indices is not None else None, tuple(sorted(kw.items()))))
        if self.raises: raise self.raises
        return self.results
    def get_section_info_from(self, index, rowid): return self.sections.get((index, rowid))
def topic(level, count, text='т'): return {'meta': {'matched_words': ['слово'], 'max_level': level, 'count_at_max': count}, 'text': text}

def make(vmm=None, engine=None, config=None, query='слово', variations=None, stale=False):
    LOG.clear()
    sc = scm.SearchController(engine=engine or Engine(), config=config or {}, result_text=ns(delete=rec('rt.delete')),
        word_panel=ns(clear=rec('wp.clear'), update_vector_words=rec('wp.vectors'), show_message=rec('wp.message')), query_entry=ns(get=lambda: query),
        index_manager=ns(index_display_map={}, get_selected_indices_ordered=lambda: ['idx_a']), file_manager=None, status_update_callback=rec('status'),
        get_current_index_name_callback=lambda: 'idx_a', config_dict={'book.txt': ('Книга', 'N', '')},
        results_renderer=ns(render_help_text=rec('help')), vector_model_manager=vmm or VMM(),
        set_split_view_active_callback=rec('set_split'), variations_excluded_callback=(lambda: variations) if variations is not None else None)
    sc.btn_first, sc.btn_back, sc.btn_forward, sc.btn_last = Btn(), Btn(), Btn(), Btn()
    sc._display_page = lambda *a, **k: LOG.append(('display', len(sc.all_filtered_topics), sc.results_page))
    sc._update_nav_buttons = rec('nav')
    if stale:
        sc.all_filtered_topics = [{'meta': {}, 'text': f'старый{i}'} for i in range(100)]; sc._full_topic_data = list(sc.all_filtered_topics); sc.results_page = 2
        sc.word_counts = {'старое': 1}; sc.is_viewing_file = True; sc.saved_state = {'k': 1}; sc.split_mode_active = True
    return sc
def is_clean(sc): return sc.all_filtered_topics == [] and sc._full_topic_data == [] and sc.results_page == 0 and sc.word_counts == {}

# ===================== A. FastText: _do_vector_search =====================
sc = make(VMM(mtype='minilm')); sc._do_semantic_search = rec('semantic_called'); sc._do_vector_search('слово', 'Mini м', ['idx_a'])
check('модель уровня предложений (MiniLM) передаётся в _do_semantic_search с теми же аргументами, больше ничего не делается', LOG == [('semantic_called', 'слово', 'Mini м', ['idx_a'])], str(LOG))
sc = make(VMM(neighbors=[('сосед', .9)]), Engine(results=[topic(10, 1)]), stale=True); sc._do_vector_search('Бог создал небо', 'FT м', ['idx_a', 'idx_b'])
check('режим разделения выключается (callback False), окна и панель очищены, просмотр файла сброшен', sc.split_mode_active is False and ('set_split', False) in LOG and calls('wp.clear') and calls('rt.delete') and sc.is_viewing_file is False and sc.saved_state == {})
check('соседи спрашиваются по ПЕРВОМУ слову запроса (остальные слова молча не учитываются)', calls('neighbors') == [('neighbors', 'FT м', 'Бог')], str(calls('neighbors')))
check('левая панель — слова-соседи с близостью, счётчики слов пусты', calls('wp.vectors') == [('wp.vectors', [('сосед', .9)], ('query_word', 'Бог'), ('vector_key', 'FT м'))] and sc.word_counts == {}, str(calls('wp.vectors')))
check('поиск по обычным индексам по «точечному» запросу .слово. (точное совпадение), слово запроса первым, без повторов, min_word_length=2, «уникальный» рейтинг',
      calls('search') == [('search', '.Бог. .сосед.', ('idx_a', 'idx_b'), (('min_word_length', 2), ('unique_word_rating', True)))], str(calls('search')))
sc = make(VMM(neighbors=[('Бог', .9), ('бог', .8), ('сосед', .7)]), Engine(results=[topic(10, 1)])); sc._do_vector_search('Бог', 'FT м', ['idx_a'])
check('слова запроса и соседей различаются по регистру («Бог» и «бог» — разные слова запроса), повторы одного регистра убраны', calls('search')[0][1] == '.Бог. .бог. .сосед.', calls('search')[0][1])
check('слова для подсветки — в нижнем регистре, без повторов, фрагментов нет', sc.current_query_words_lower == ['бог', 'сосед'] and sc.current_partial_fragments == [] and sc._last_all_fragments_levels == [], str(sc.current_query_words_lower))
sc = make(VMM(neighbors=[('а', .9)]), variations=True); sc._do_vector_search('слово', 'FT м', ['idx_a'])
check('«−В» (словоформы исключены): соседи берутся без словоформ', calls('neighbors_dedup') and not calls('neighbors'))
sc = make(VMM(neighbors=[('а', .9)]), variations=False); sc._do_vector_search('слово', 'FT м', ['idx_a'])
check('«+В» или без колбэка: обычные соседи', calls('neighbors') and not calls('neighbors_dedup'))
tops = [topic(5, 1, 'слабый'), topic(10, 2, 'сильный'), topic(10, 1, 'средний')]
sc = make(VMM(neighbors=[('а', .9)]), Engine(results=tops)); sc._do_vector_search('слово', 'FT м', ['idx_a'])
check('результаты: сортировка по (уровень, число совпадений) от лучшего; исходный порядок сохранён отдельно; страница 0; рисуется один раз',
      [t['text'] for t in sc.all_filtered_topics] == ['сильный', 'средний', 'слабый'] and [t['text'] for t in sc._full_topic_data] == ['слабый', 'сильный', 'средний'] and sc.results_page == 0 and calls('display') == [('display', 3, 0)])
sc = make(VMM(neighbors=[('а', .9)]), Engine(results=[topic(1, 1)]), stale=True); sc._do_vector_search('слово', 'FT м', ['idx_a'])
check('новые результаты заменяют старые, страница сброшена на 0', len(sc.all_filtered_topics) == 1 and sc.results_page == 0)
sc = make(VMM(), query=''); sc._do_vector_search('   ', 'FT м', ['idx_a'])
check('пустое слово запроса: справка, кнопки листания, поиска нет', calls('help') and calls('nav') and not calls('search') and not calls('neighbors'))
sc = make(VMM(neighbors=[('а', .9)]), Engine(raises=RuntimeError('нет связи'))); sc._do_vector_search('слово', 'FT м', ['idx_a'])
check('ошибка движка: окно «Ошибка поиска: …», страница не рисуется', calls('msg') == [('msg', 'showerror', 'Ошибка', 'Ошибка поиска: нет связи')] and not calls('display'))
sc = make(VMM(neighbors=[('а', .9)]), Engine(results=[])); sc._do_vector_search('слово', 'FT м', ['idx_a'])
check('ничего не найдено: справка и обновление кнопок листания, страница не рисуется', calls('help') and calls('nav') and not calls('display'))
stats_logger.STATS_ENABLED = True; stats_logger.log_search = rec('log_search')
sc = make(VMM(neighbors=[('а', .9)]), Engine(results=[topic(1, 1)])); sc._do_vector_search('слово', 'FT м', ['idx_a', 'idx_b'])
kw = dict(calls('log_search')[0][1:]) if calls('log_search') else {}
check('журнал: engine_type = vector, индекс «модель -> индексы»', kw.get('engine_type') == 'vector' and kw.get('index_name') == 'FT м -> idx_a, idx_b' and kw.get('query') == 'слово', str(kw))
stats_logger.STATS_ENABLED = False

# ===================== B. MiniLM: _do_semantic_search =====================
MATCHES = [('idx_a', 1, .91), ('idx_a', 2, .85), ('idx_other', 3, .80)]
SECTIONS = {('idx_a', 1): {'text': 'первый текст', 'file_name': 'book.txt', 'position': '5'}, ('idx_a', 2): {'text': 'второй текст'}}
sc = make(VMM(matches=MATCHES, mtype='minilm'), Engine(sections=SECTIONS), stale=True); sc._do_semantic_search('смысл слов', 'Mini м', ['idx_x'])
check('режим разделения выключен, окна и панель очищены, просмотр файла сброшен', sc.split_mode_active is False and ('set_split', False) in LOG and calls('wp.clear') and calls('rt.delete') and sc.is_viewing_file is False and sc.saved_state == {})
sc = make(VMM(mtype='minilm')); sc._do_semantic_search('  ', 'Mini м', [])
check('пустой запрос: справка, кнопки листания; модель не вызывается, пояснение не показывается', calls('help') and calls('nav') and not calls('semantic') and not calls('wp.message'), str(LOG))
sc = make(VMM(matches=MATCHES, mtype='minilm'), Engine(sections=SECTIONS)); sc._do_semantic_search('смысл слов', 'Mini м', ['idx_x'])
check('вместо списка близких слов левая панель показывает пояснение', len(calls('wp.message')) == 1 and 'Семантический поиск' in calls('wp.message')[0][1] and not calls('wp.vectors'))
check('модель получает ВЕСЬ запрос (не первое слово)', calls('semantic')[0][:3] == ('semantic', 'Mini м', 'смысл слов'), str(calls('semantic')))
check('топики собираются из строк индекса: текст, файл, позиция, близость; индекс не из связанных с моделью отбрасывается; нет данных о строке — топик пропущен',
      [(t['rowid'], t['content'], t['file_name'], t['position'], t['semantic_score']) for t in sc._full_topic_data] == [(1, 'первый текст', 'book.txt', '5', .91), (2, 'второй текст', '', '0', .85)], str(sc._full_topic_data))
sc = make(VMM(matches=[('idx_a', 1, .5), ('idx_a', 2, .9)], mtype='minilm'), Engine(sections=SECTIONS)); sc._do_semantic_search('смысл слов', 'Mini м', [])
check('порядок: в _full_topic_data как вернула модель, в показе — по убыванию близости; страница 0; рисуется один раз', [t['rowid'] for t in sc._full_topic_data] == [1, 2] and [t['rowid'] for t in sc.all_filtered_topics] == [2, 1] and calls('display') == [('display', 2, 0)])
sc = make(VMM(matches=MATCHES, mtype='minilm'), Engine(sections=SECTIONS)); sc._do_semantic_search('Смысл слов', 'Mini м', [])
check('слова запроса для подсветки — от 2 символов (как в режиме разделения), фрагменты и уровни собраны', sc.current_query_words_lower == ['смысл', 'слов'] and {'Смысл', 'слов'} <= set(sc.current_partial_fragments) and ('Смысл', 10, False) in sc._last_all_fragments_levels, str(sc.current_query_words_lower))
sc = make(VMM(matches=[], mtype='minilm')); sc._do_semantic_search('смысл', 'Mini м', [])
check('модель ничего не вернула: справка, подсказка в статусе, кнопки листания', calls('help') and calls('nav') and calls('status') == [('status', '⚠️ Семантический поиск не нашёл ничего среди отмеченных индексов.')] and not calls('display'), str(calls('status')))
sc = make(VMM(matches=[('idx_other', 1, .9)], mtype='minilm')); sc._do_semantic_search('смысл', 'Mini м', [])
check('все совпадения — из чужих индексов: то же сообщение', calls('status') == [('status', '⚠️ Семантический поиск не нашёл ничего среди отмеченных индексов.')])
sc = make(VMM(matches=[('idx_a', 9, .9)], mtype='minilm'), Engine(sections={})); sc._do_semantic_search('смысл', 'Mini м', [])
check('содержимое топиков получить не удалось: «Не удалось получить содержимое найденных топиков.», страница не рисуется', calls('help') and calls('status') == [('status', '⚠️ Не удалось получить содержимое найденных топиков.')] and not calls('display'), str(calls('status')))
stats_logger.STATS_ENABLED = True; stats_logger.log_search = rec('log_search')
sc = make(VMM(matches=MATCHES, mtype='minilm'), Engine(sections=SECTIONS)); sc._do_semantic_search('смысл', 'Mini м', ['idx_x', 'idx_y'])
kw = dict(calls('log_search')[0][1:]) if calls('log_search') else {}
check('журнал: engine_type = semantic, индекс «модель -> отмеченные индексы»', kw.get('engine_type') == 'semantic' and kw.get('index_name') == 'Mini м -> idx_x, idx_y', str(kw))
stats_logger.STATS_ENABLED = False

# ===================== C. известные ошибки =====================
for label, fn, vmm, eng, key in (('FastText: поиск по индексу ничего не нашёл', '_do_vector_search', VMM(neighbors=[('а', .9)]), Engine(results=[]), 'FT м'),
                                 ('FastText: ошибка движка', '_do_vector_search', VMM(neighbors=[('а', .9)]), Engine(raises=RuntimeError('сбой')), 'FT м'),
                                 ('MiniLM: модель ничего не вернула', '_do_semantic_search', VMM(matches=[], mtype='minilm'), Engine(), 'Mini м'),
                                 ('MiniLM: все совпадения из чужих индексов', '_do_semantic_search', VMM(matches=[('idx_other', 1, .9)], mtype='minilm'), Engine(), 'Mini м'),
                                 ('MiniLM: содержимое топиков получить не удалось', '_do_semantic_search', VMM(matches=[('idx_a', 9, .9)], mtype='minilm'), Engine(sections={}), 'Mini м')):
    sc = make(vmm, eng, stale=True); getattr(sc, fn)('смысл слов', key, ['idx_a'])
    check(f'после {label}, старые результаты и страница забыты (на экране справка, листание не должно показывать прошлые результаты)', is_clean(sc),
                f'осталось топиков {len(sc.all_filtered_topics)}, страница {sc.results_page}, счётчики слов {sc.word_counts}')
sc = make(VMM(matches=[], mtype='minilm'), config={'vector_model_topn': 40}); sc._do_semantic_search('смысл', 'Mini м', [])
check('семантический поиск берёт число топиков из настройки vector_model_topn (self.config), а не из словаря баз', calls('semantic')[0][3] == 40, f"в настройках 40, модели передано {calls('semantic')[0][3]}")
sc = make(VMM(matches=[], mtype='minilm'), config={}); sc._do_semantic_search('смысл', 'Mini м', [])
check('настройки нет — по умолчанию 15 топиков', calls('semantic')[0][3] == 15)
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
