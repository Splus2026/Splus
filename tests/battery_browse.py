import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import sys, os, types, tempfile
import tkinter as tk
results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

class FakeText:
    def __init__(self): self.text = ''; self.tags = {}
    def config(self, **k): pass
    configure = config
    def update_idletasks(self): pass
    def tag_config(self, *a, **k): pass
    def tag_bind(self, *a, **k): pass
    def yview(self, *a): pass
    def mark_set(self, *a): pass
    def focus_set(self): pass
    def winfo_ismapped(self): return True
    def tag_prevrange(self, tag, idx): return ()
    def _lines(self): return self.text.split('\n')
    def _sel(self): return self.tags['sel'][0] if self.tags.get('sel') else None
    def _to_off(self, idx):
        idx = str(idx)
        if idx == 'end': return len(self.text) + 1
        if idx == 'end-1c': return len(self.text)
        if idx in ('sel.first', 'sel.last'):
            s = self._sel()
            if not s: raise tk.TclError("text doesn't contain any characters tagged with \"sel\"")
            return s[0] if idx == 'sel.first' else s[1]
        line, col = idx.split('.'); lines = self._lines(); line = int(line)
        col = len(lines[line - 1]) if col == 'end' else int(col)
        return sum(len(l) + 1 for l in lines[:line - 1]) + col
    def _to_idx(self, off):
        lines = self._lines(); n = 0
        for i, l in enumerate(lines, 1):
            if off <= n + len(l): return f"{i}.{off - n}"
            n += len(l) + 1
        return f"{len(lines)}.{len(lines[-1])}"
    def index(self, spec): return self._to_idx(self._to_off(spec))
    def delete(self, a, b=None): self.text = ''; self.tags = {}
    def insert(self, where, text, *tags):
        start = len(self.text); self.text += text
        for group in tags:
            for t in ((group,) if isinstance(group, str) else group):
                self.tags.setdefault(t, []).append((start, len(self.text)))
    def get(self, a, b=None): return self.text[self._to_off(a):self._to_off(b) if b else None]
    def tag_add(self, tag, a, b): self.tags.setdefault(tag, []).append((self._to_off(a), self._to_off(b)))
    def tag_remove(self, tag, a, b): self.tags.pop(tag, None)
    def tag_ranges(self, tag):
        r = self.tags.get(tag, [])
        return (self._to_idx(r[0][0]), self._to_idx(r[0][1])) if r else ()
    def tagged(self, tag): return sorted(self.text[a:b] for a, b in self.tags.get(tag, []))
    def select_text(self, sub, nth=0):
        pos = -1
        for _ in range(nth + 1): pos = self.text.index(sub, pos + 1)
        self.tags['sel'] = [(pos, pos + len(sub))]; return pos
    def selection_get(self):
        s = self._sel()
        if not s: raise tk.TclError("no selection")
        return self.text[s[0]:s[1]]

import services.search_controller as scm
scm.stats_logger = types.SimpleNamespace(STATS_ENABLED=False)
from services.search_controller import SearchController
from ui.results_renderer import ResultsRenderer, BLOCK_SEPARATOR
from services.marks import MarksStore

BIBL = [(5, 'Пятый блок.', 'bibl.txt'), (1, 'Первый блок.\nвторая строка', 'bibl.txt'), (3, 'Третий блок.', 'bibl.txt'),
        (2, 'Второй блок.', 'bibl.txt'), (4, '   ', 'bibl.txt'), (6, 'Шестой блок.', 'bibl.txt'), (7, 'Седьмой блок.', 'bibl.txt')]
DATA = {'bibl': BIBL,
        'gita': [(1, 'Гита один.', 'gita.docx'), (2, 'Гита два.', 'gita.docx')],
        'ost': [(1, 'строка таблицы', 'ost.xlsx')],
        'pdf': [(1, 'текст', 'x.pdf')], 'empty': [], 'boom': None}
class FakeEngine:
    engine_type = 'manticore'; _current_index = 'bibl'
    def __init__(self, data): self.data = data; self.calls = []
    def get_all_sections(self, index):
        self.calls.append(index)
        if self.data[index] is None: raise RuntimeError("Manticore недоступен")
        return list(self.data[index])
class FakeWP:
    def __init__(self): self.cleared = 0
    def clear(self): self.cleared += 1
class FakeEntry:
    def __init__(self, v=''): self.v = v
    def get(self): return self.v
    def set(self, v): self.v = v
class FakeVMM:
    def is_vector_key(self, k): return k.startswith('FT ')

def make(selected, query='**', page_size=3, engine=None, vmm=True):
    widget = FakeText(); rend = ResultsRenderer(widget); rend.marks_store = MarksStore(os.path.join(tempfile.mkdtemp(), 'm.db'))
    state = {'selected': list(selected), 'status': [], 'split_cb': []}
    im = types.SimpleNamespace(get_selected_indices_ordered=lambda: list(state['selected']),
                               index_display_map={'bibl': 'Библия', 'gita': 'Гита', 'ost': 'Остатки'})
    cfg = {'bibl.txt': ('Библия', '===', ''), 'gita.docx': ('Гита', '---', ''), 'ost.xlsx': ('Остатки', '---', '')}
    eng = engine or FakeEngine(DATA)
    entry = FakeEntry(query); wp = FakeWP()
    sc = SearchController(eng, {}, widget, wp, entry, im, None, state['status'].append, lambda: 'bibl', cfg, rend,
                          vector_model_manager=FakeVMM() if vmm else None, hide_vector_viz_callback=lambda: None,
                          set_split_view_active_callback=state['split_cb'].append)
    sc.page_size = page_size
    return sc, widget, rend, state, eng, entry, wp

SEP = BLOCK_SEPARATOR
# ===== условия: пояснения вместо блоков =====
def hint_of(selected, **kw):
    sc, w, r, st, eng, e, wp = make(selected, **kw); sc.do_search(); return sc, w, r, eng
sc, w, r, eng = hint_of([]); check('не отмечено ни одного индекса: пояснение «ровно один», режима нет', 'ровно один' in w.text and not sc.browse_mode and sc.all_filtered_topics == [])
sc, w, r, eng = hint_of(['bibl', 'gita']); check('отмечено два индекса: пояснение, режим не включён, индекс не читался', 'ровно один' in w.text and not sc.browse_mode and eng.calls == [])
sc, w, r, eng = hint_of(['FT Библия [модель]']); check('отмечена векторная модель: пояснение про модель', 'векторная модель' in w.text and not sc.browse_mode and eng.calls == [])
sc, w, r, eng = hint_of(['ost']); check('отмечена таблица Excel: пояснение, блоки не читались', 'Excel' in w.text and not sc.browse_mode and eng.calls == [])
sc, w, r, eng = hint_of(['pdf']); check('файл другого типа (.pdf): пояснение с расширением', '.pdf' in w.text and not sc.browse_mode)
sc, w, r, eng = hint_of(['empty']); check('пустой индекс: пояснение', 'нет блоков' in w.text and not sc.browse_mode)
sc, w, r, eng = hint_of(['boom']); check('индекс не читается: ошибка в окне, а не падение', 'Manticore недоступен' in w.text and not sc.browse_mode)
class NoSections: engine_type = 'elasticsearch'; _current_index = 'bibl'
sc, w, r, eng = hint_of(['bibl'], engine=NoSections()); check('движок без get_all_sections: «только Manticore»', 'Manticore' in w.text and not sc.browse_mode)
check('после пояснения «Ч» недоступна (блоков нет)', r.regions == [] and r.toggle_underline() == ('no_selection', 0))

# ===== показ блоков =====
sc, w, r, st, eng, entry, wp = make(['bibl'])
sc.do_search()
check('режим включён: файл и метка запомнены', sc.browse_mode and sc.browse_index == 'bibl' and sc.browse_file_label == sc._format_file_label('bibl.txt'))
check('блоки в порядке файла (не в порядке выдачи), пустой блок пропущен', [t['rowid'] for t in sc.all_filtered_topics] == [1, 2, 3, 5, 6, 7], str([t['rowid'] for t in sc.all_filtered_topics]))
expected_p0 = 'Первый блок.\nвторая строка' + '\n' + SEP + '\n' + 'Второй блок.' + '\n' + SEP + '\n' + 'Третий блок.'
check('страница 1: три блока, между ними пунктирная линия, без шапок и заголовка страницы', w.text == expected_p0, repr(w.text))
check('линии ровно две (между тремя блоками), ни до первого, ни после последнего', w.text.count(SEP) == 2 and not w.text.startswith(SEP) and not w.text.endswith(SEP))
check('линия пунктирная и серая (отдельный тег)', set(w.tagged('block_separator')) == {SEP})
check('нет ни «Файл:», ни «Результаты поиска»', 'Файл:' not in w.text and 'Результаты' not in w.text)
check('блоки зарегистрированы для «Ч», линии — нет', len(r.regions) == 3 and all(reg['file_name'] == 'bibl.txt' for reg in r.regions) and all(SEP not in reg['display'] for reg in r.regions))
check('строка состояния: файл, число блоков, страница', any('блоков: 6' in s and 'страница 1 из 2' in s for s in st['status']), str(st['status']))
check('окно «Совпадения» очищено, исключённые слова сброшены, подсветки нет', wp.cleared >= 1 and sc.current_query_words_lower == [] and sc.current_partial_fragments == [])
sc.page_forward()
check('«Вперёд»: вторая страница — три оставшихся блока', w.text == 'Пятый блок.' + '\n' + SEP + '\n' + 'Шестой блок.' + '\n' + SEP + '\n' + 'Седьмой блок.', repr(w.text))
sc.go_to_first_page(); check('«В начало»', w.text.startswith('Первый блок.'))
sc.go_to_last_page(); check('«В конец» — последняя страница', w.text.endswith('Седьмой блок.'))
before = w.text; sc.toggle_brief_mode(); after = w.text; sc.toggle_brief_mode()
check('«Кратко/Всё» в этом режиме ничего не ломает (без запроса сокращать нечего)', before == after and w.text == before)

# ===== идемпотентность =====
sc, w, r, st, eng, entry, wp = make(['bibl']); sc.do_search(); sc.page_forward(); text_p2 = w.text; calls = len(eng.calls)
sc.do_search(); sc.do_search()
check('повторный «**» (Enter, Shift, стрелки): индекс не перечитывается', len(eng.calls) == calls)
check('и страница не сбрасывается на первую', sc.results_page == 1 and w.text == text_p2)

# ===== смена индекса =====
sc.index_manager.get_selected_indices_ordered = lambda: ['gita']
sc.do_search()
check('отмечен другой файл: показан он (.docx), с первой страницы', sc.browse_index == 'gita' and sc.results_page == 0 and w.text == 'Гита один.' + '\n' + SEP + '\n' + 'Гита два.', repr(w.text))
check('метка файла обновилась', sc.browse_file_label == sc._format_file_label('gita.docx'))

# ===== режим разделения выключается =====
sc, w, r, st, eng, entry, wp = make(['bibl']); sc.split_mode_active = True; sc.do_search()
check('режим разделения (два Excel) выключен, окно об этом уведомлено', sc.split_mode_active is False and st['split_cb'] == [False])
sc2, w2, r2, st2, eng2, e2, wp2 = make(['bibl']); sc2._full_topic_data = [{'meta': {'matched_words': []}, 'content': 'старый поиск'}]; sc2.do_search(); sc2.refresh_display()
check('refresh_display после входа в режим не подменяет блоки', 'старый поиск' not in w2.text and 'Первый блок.' in w2.text)

# ===== «Ч» в этом режиме =====
sc, w, r, st, eng, entry, wp = make(['bibl']); sc.do_search()
w.select_text('Второй блок'); res = r.toggle_underline()
check('«Ч» работает: подчёркнут фрагмент блока', res == ('added', 1) and w.tagged('user_mark') == ['Второй блок'])
a = w.text.index('вторая строка'); b = w.text.index('Второй')
w.tags['sel'] = [(a, b + 6)]; res = r.toggle_underline()
check('«Ч» через линию между блоками: подчёркнуты части блоков, сама линия — нет', res[0] == 'added' and not any(SEP in t for t in w.tagged('user_mark')), str(w.tagged('user_mark')))
sc.page_forward(); sc.go_to_first_page()
check('подчёркивание не теряется при листании', 'Второй' in ''.join(w.tagged('user_mark')))

# ===== «КП» =====
import ui.app_window as aw
KF = os.path.join(tempfile.mkdtemp(), 'kc.txt'); aw.KEY_CONCEPTS_FILE = KF
win = aw.AppWindow.__new__(aw.AppWindow); win.toasts = []; win.logs = []
win._show_temporary_notification = lambda m, duration_ms=700: win.toasts.append(m); win._update_log_field = win.logs.append
win.vector_viz_canvas = types.SimpleNamespace(winfo_ismapped=lambda: False); win.result_text = w; win.result_text_2 = None
sc.go_to_last_page(); w.select_text('Седьмой'); win._add_key_concept()
from utils import key_concepts as KC
check('«КП» работает: слово из блока в словаре', KC.load_key_concepts(KF) == ['седьмой'] and win.toasts[-1] == 'Добавлено: седьмой')

# ===== конспект правой кнопкой =====
CF = os.path.join(tempfile.mkdtemp(), 'conspect.txt'); aw.CONSPECT_FILE = CF
win.search_controller = sc; win.root = types.SimpleNamespace(after=lambda ms, fn: fn())
win._conspect_lock = False; win._last_conspect_text = None; win._last_conspect_source = None; win._conspect_source_written = True
sc.go_to_first_page(); w.select_text('Третий блок.')
ev = types.SimpleNamespace(widget=w)
check('источник цитаты в этом режиме — отмеченный файл (шапок у блоков нет)', win._get_conspect_source_label(w) == sc.browse_file_label and sc.browse_file_label)
win.append_selection_to_conspect(ev)
win.append_selection_to_conspect(ev)
win.append_selection_to_conspect(ev)
content = open(CF, encoding='utf-8').read()
check('правый щелчок: цитата, второй — источник, третий ничего (как в остальных режимах)',
      content == f".......Третий блок.\n({sc.browse_file_label})\n", repr(content))

# ===== выход из режима =====
sc.query_entry.set('x'); sc.do_search()
check('другой запрос выводит из режима и сбрасывает метку файла', not sc.browse_mode and sc.browse_index is None and sc.browse_file_label is None)
check('после выхода источник цитаты снова ищется по шапкам: метка файла режима не «прилипает» (без шапки — пусто)',
      win._get_conspect_source_label(w) == '', repr(win._get_conspect_source_label(w)))
sc.query_entry.set('**'); sc.index_manager.get_selected_indices_ordered = lambda: ['bibl']; sc.do_search(); first_label = sc.browse_file_label
sc.query_entry.set('  **  '); sc.do_search()
check('пробелы вокруг «**» не мешают (запрос обрезается)', sc.browse_mode)
sc.exit_browse_mode(); check('exit_browse_mode сбрасывает всё', not sc.browse_mode and sc.browse_file_label is None)

# ===== выход не оставляет блоки файла «результатами поиска» =====
sc, w, r, st, eng, entry, wp = make(['bibl']); sc.do_search(); sc.page_forward(); assert sc.browse_mode
sc.query_entry.set('x'); sc.do_search()
check('выход из режима коротким запросом: блоки файла убраны, страница сброшена', sc.all_filtered_topics == [] and sc.results_page == 0 and not sc.browse_mode)
sc.page_forward()
check('и «Вперёд» после выхода НЕ показывает блоки файла как «результаты поиска»', 'Первый блок' not in w.text and 'Пятый блок' not in w.text and 'Файл:' not in w.text)
sc, w, r, st, eng, entry, wp = make(['bibl']); sc.all_filtered_topics = [{'rowid': 1, 'content': 'обычный результат'}]; sc.results_page = 0
sc.exit_browse_mode()
check('вне режима exit_browse_mode обычные результаты поиска не трогает', sc.all_filtered_topics == [{'rowid': 1, 'content': 'обычный результат'}])

# ===== MainWindow._on_key_release =====
import ui.main_window as mwm
mw = mwm.MainWindow.__new__(mwm.MainWindow)
sc, w, r, st, eng, entry, wp = make(['bibl'])
mw.query_entry = entry; mw._prev_query_len = 0; mw._typing_timestamps = []; mw._after_id = None; mw._last_search_time = 0; mw._search_delay = 300
mw.root = types.SimpleNamespace(after_cancel=lambda i: None, after=lambda ms, fn: 1)
mw.search_controller = sc; mw.word_panel = wp
log = []; mw.do_search = lambda: (log.append('search'), sc.do_search()); mw._show_help_text = lambda: log.append('help')
entry.set('**'); mw._on_key_release(types.SimpleNamespace())
check('«**» по отпусканию клавиши: режим включается сразу, справка НЕ показывается', log == ['search'] and sc.browse_mode and 'Первый блок.' in w.text)
mw._on_key_release(types.SimpleNamespace()); mw._on_key_release(types.SimpleNamespace())
check('повторные отпускания клавиш на «**» (Enter, Shift…) блоков не стирают и не листают заново', 'help' not in log and 'Первый блок.' in w.text and len(eng.calls) == 1)
sc.page_forward(); mw._on_key_release(types.SimpleNamespace())
check('и страница, на которой вы были, сохраняется', sc.results_page == 1 and w.text.startswith('Пятый блок.'))
entry.set('*'); log.clear(); mw._on_key_release(types.SimpleNamespace())
check('удалена одна звёздочка («*», меньше 3 символов): режим закончен, показана справка, блоки очищены', log == ['help'] and not sc.browse_mode and sc.all_filtered_topics == [] and sc.browse_file_label is None)
entry.set(' ** '); log.clear(); mw._on_key_release(types.SimpleNamespace())
check('«**» с пробелами по краям тоже включает режим', 'search' in log and sc.browse_mode)
entry.set('бог'); log.clear(); mw.do_search = lambda: log.append('search'); mw._on_key_release(types.SimpleNamespace())
check('обычный запрос от 3 символов идёт прежним путём (поиск), режим не мешает', log == ['search'])

# ===== смена индекса через IndexManager и окно =====
from services.index_manager import IndexManager
im = IndexManager.__new__(IndexManager); im.engine = types.SimpleNamespace(engine_type='manticore'); im.selection_changed_callback = None
im._update_selected_indices_display = lambda: None; im._maybe_offer_vector_preload = lambda sel: None
im._on_selection_changed(['bibl'])
check('без обратного вызова смена индекса работает как раньше', im.selected_indices_names == ['bibl'])
got = []; im.selection_changed_callback = got.append; im._on_selection_changed(['gita'])
check('обратный вызов получает новый список отмеченных индексов', got == [['gita']])
check('IndexManager: атрибут задан по умолчанию (None)', 'self.selection_changed_callback = None' in open(os.path.join(env.ROOT, 'services/index_manager.py'), encoding='utf-8').read())
win2 = aw.AppWindow.__new__(aw.AppWindow); win2.search_controller = types.SimpleNamespace(BROWSE_QUERY='**'); win2.query_entry = FakeEntry('**'); calls = []; win2.do_search = lambda: calls.append(1)
win2._on_index_selection_changed(['gita'])
check('в режиме «**» смена индекса запускает показ нового файла', calls == [1])
win2.query_entry.set('бог'); win2._on_index_selection_changed(['gita'])
check('при обычном запросе смена индекса ничего не запускает (как раньше)', calls == [1])
src_app = open(os.path.join(env.ROOT, 'ui/app_window.py'), encoding='utf-8').read()
check('обратный вызов подключён после создания IndexManager', 'self.index_manager.selection_changed_callback = self._on_index_selection_changed' in src_app)

print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
