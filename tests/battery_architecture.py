import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import ast, re, types, zlib
import numpy as np
import tkinter as tk

# Кнопка, запоминающая place()/place_forget()
class TrackingButton(tk.Widget):
    def __init__(self, master=None, **kw): super().__init__(master, **kw); self.placed = False
    def place(self, **kw): self.placed = True; self.place_kw = kw
    def place_forget(self): self.placed = False
tk.Button = TrackingButton

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))
def known_issue(name, fixed, detail=''):
    """Долг, о котором известно: пока он есть — строка «ИЗВЕСТНАЯ ОШИБКА» (прогон не ломает); когда исправят, проверка становится обычной."""
    if fixed: check(name + ' (исправлено)', True)
    else: print(f'ИЗВЕСТНАЯ ОШИБКА {name}  -> {detail}')

import ui.app_window as aw
from ui import visualization_controller as vc
ROOT = env.ROOT
def read(rel): return open(os.path.join(ROOT, rel), encoding='utf-8').read()

# Что переехало из окна в контроллер (имена в контроллере) и что осталось его СОСТОЯНИЕМ
MOVED = ['_revisualize_bar', '_revisualize_heatmap', '_revisualize_dendrogram', 'show_vector_viz_menu', 'show_textrank_for_selected', 'show_word_cloud_for_selected',
         'show_word_cloud', 'show_full_space_cloud', '_get_density_cluster_data', '_do_visualize_tsne', '_do_visualize', '_visualize_2d_for', '_on_viz_word_click',
         '_revisualize_network', '_setup_viz_zoom_pan', 'show_vector_visualization_2d', 'show_bar_chart', 'show_heatmap', 'show_dendrogram_viz', 'show_network_graph',
         'show_radial_layout', '_revisualize_radial', '_new_viz_state', '_prepare_viz_canvas', '_register_viz', '_clear_viz_history', '_push_current_viz', '_viz_go_back',
         '_update_viz_back_button', 'hide_vector_visualization']
STATE = ['_last_viz_revisualize', '_viz_history', '_current_viz', '_viz_nav_mode', '_viz_registered', 'btn_viz_back', '_VIZ_HISTORY_LIMIT']
# Граница с окном — ровно то, что написано в docstring VisualizationController
CONTRACT = {'result_text', 'vector_viz_canvas', 'query_entry', 'root', 'word_panel', 'search_controller', 'vector_model_manager', 'index_manager',
            '_key_concept_words', '_warn_key_concepts_empty', '_update_log_field'}

# ===================== A. структура =====================
win_src = read('ui/app_window.py'); win_tree = ast.parse(win_src)
win_cls = next(n for n in win_tree.body if isinstance(n, ast.ClassDef) and n.name == 'AppWindow')
win_methods = {m.name for m in win_cls.body if isinstance(m, ast.FunctionDef)}
ctl_src = read('ui/visualization_controller.py'); ctl_tree = ast.parse(ctl_src)
ctl_cls = next(n for n in ctl_tree.body if isinstance(n, ast.ClassDef) and n.name == 'VisualizationController')
ctl_methods = {m.name for m in ctl_cls.body if isinstance(m, ast.FunctionDef)}
ctl_class_attrs = {t.id for n in ctl_cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
check('все 30 визуализационных методов — в контроллере', set(MOVED) <= ctl_methods, str(sorted(set(MOVED) - ctl_methods)))
check('в окне (AppWindow) таких методов больше нет', not (win_methods & set(MOVED)), str(sorted(win_methods & set(MOVED))))
check('в окне не осталось ссылок на переехавшее состояние (self._viz_history, self.btn_viz_back, ...)', not re.search(r'self\.(_viz_|_current_viz|btn_viz_back|_last_viz_revisualize|_VIZ_HISTORY_LIMIT)', win_src))
check('окно создаёт контроллер в __init__ РАНЬШЕ, чем строит виджеты и сервисы (они ссылаются на self.viz)',
      0 < win_src.index('self.viz = VisualizationController(self)') < win_src.index('self._create_widgets()') < win_src.index('self._init_services()'))
check('(фитнес-проверка) AppWindow не разрастается заново: не больше 1800 строк (сейчас около 1560); новое поведение — в отдельные классы', len(win_src.splitlines()) <= 1800, str(len(win_src.splitlines())))

# каждое self.X в контроллере — его собственный член или app (ловит забытые обращения к окну, в том числе через getattr(self, 'имя'))
own = ctl_methods | ctl_class_attrs | set(STATE) | {'app'}
used_self = {n.attr for n in ast.walk(ctl_cls) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'self'}
indirect = {a.args[1].value for a in ast.walk(ctl_cls) if isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id in ('getattr', 'hasattr', 'setattr')
            and len(a.args) >= 2 and isinstance(a.args[0], ast.Name) and a.args[0].id == 'self' and isinstance(a.args[1], ast.Constant)}
check('каждое self.X в контроллере — собственный метод/состояние или self.app (чужие члены окна без app — ошибка)', not (used_self - own), str(sorted(used_self - own)))
check('getattr/hasattr(self, "имя") в контроллере тоже только про собственные члены (ошибка, которую уже ловили: getattr(self, "vector_viz_canvas"))', not (indirect - own), str(sorted(indirect - own)))
imports = set()
for n in ast.walk(ctl_tree):
    if isinstance(n, ast.Import): imports |= {a.name for a in n.names}
    elif isinstance(n, ast.ImportFrom): imports |= {(n.module or '') + '.' + a.name for a in n.names}
forbidden = sorted(m for m in imports if m.startswith(('ui.app_window', 'ui.main_window', 'ui.word_panel', 'services', 'engines', 'vector_engines', 'config', 'settings', 'sp')))
check('контроллер не импортирует окно, сервисы, движки и настройки (никаких циклов; зависит от диалогов, алгоритмов визуализации, словаря ключевых понятий и библиотек)', not forbidden, str(forbidden))
check('из проекта он использует только ui.custom_dialogs, ui.vector_visualization и utils.key_concepts', {m for m in imports if m.startswith(('ui', 'utils'))} == {'ui.custom_dialogs.messagebox', 'ui.vector_visualization', 'utils.key_concepts'}, str(sorted(imports)))
check('окно импортирует контроллер, а не наоборот', 'from ui.visualization_controller import VisualizationController' in win_src and 'app_window' not in ctl_src.split('class VisualizationController')[0])

# Все обращения к контроллеру во всём проекте (self.viz.имя, main_app.viz.имя, win.viz.имя) обязаны указывать на существующие члены:
# _create_widgets и _init_services тестами не запускаются, а опечатка в имени обработчика кнопки уронила бы запуск программы.
from tests.sources import project_sources
members = ctl_methods | set(STATE) | {'app'}; bad_refs = []; total_refs = 0
for rel in project_sources(ROOT):
    text = read(rel)
    for m in re.finditer(r'\b(?:self|main_app|app|win)\.viz\.(\w+)', text):
        total_refs += 1
        if m.group(1) not in members: bad_refs.append(f'{rel}: .viz.{m.group(1)}')
check(f'каждое обращение .viz.имя в проекте ({total_refs} шт.) указывает на существующий член контроллера', not bad_refs and total_refs >= 5, str(bad_refs))
check('кнопки «Т» и «Ц» и колбэк скрытия подключены к контроллеру',
      'command=self.viz.show_word_cloud_for_selected' in win_src and 'command=self.viz.show_textrank_for_selected' in win_src and 'hide_vector_viz_callback=self.viz.hide_vector_visualization' in win_src)

# ===================== B. контракт с окном — на живых визуализациях =====================
class FakeCanvas:
    def __init__(self): self.items = []; self.mapped = False; self.tag_binds = {}
    def pack(self, **kw): self.mapped = True
    def pack_forget(self): self.mapped = False
    def winfo_ismapped(self): return self.mapped
    def winfo_width(self): return 900
    def winfo_height(self): return 600
    def delete(self, *a): self.items.clear(); self.tag_binds.clear()
    def create_text(self, x, y, text='', tags=(), **kw): self.items.append((text, tuple(tags)))
    def tag_bind(self, tag, seq, fn): self.tag_binds[(tag, seq)] = fn
    def __getattr__(self, n):
        if n.startswith('__'): raise AttributeError(n)
        return lambda *a, **k: None
    def click(self, word):
        for text, tags in self.items:
            if text == word:
                for tag in tags:
                    if (tag, '<Button-1>') in self.tag_binds: return self.tag_binds[(tag, '<Button-1>')](None)
        raise AssertionError(f"на холсте нет кликабельного слова {word!r}")
class FakeText:
    def pack(self, **k): pass
    def pack_forget(self): pass
class FakeEntry:
    def __init__(self): self.v = ''
    def get(self): return self.v
    def delete(self, a, b=None): self.v = ''
    def insert(self, i, text): self.v = text
class FakeWordPanel:
    def __init__(self): self._last_neighbors = None; self._last_query_word = None; self._last_vector_key = None
    def clear(self): self._last_neighbors = None
class FakeVMM:
    def get_word_vectors(self, key, words): return {w: np.random.RandomState(zlib.crc32(w.encode())).randn(20) for w in words}
NEIGHBORS = {'альфа': [('бета', .9), ('гамма', .8), ('дельта', .7), ('омега', .6)], 'бета': [('альфа', .9), ('гамма', .8), ('дельта', .7), ('эпсилон', .6)],
             'гамма': [('альфа', .9), ('бета', .8), ('дельта', .7), ('эпсилон', .6)], 'дельта': [('альфа', .9), ('бета', .8), ('гамма', .7), ('эпсилон', .6)]}

class RecordingApp:
    """Окно-самописец: настоящие виджеты не нужны — записывается, к чему контроллер обращается и что в окне пытается записать."""
    def __init__(self):
        object.__setattr__(self, '_log', {'reads': set(), 'writes': []})
        for name, value in (('result_text', FakeText()), ('vector_viz_canvas', FakeCanvas()), ('query_entry', FakeEntry()), ('word_panel', FakeWordPanel()),
                            ('vector_model_manager', FakeVMM()), ('root', types.SimpleNamespace()), ('index_manager', types.SimpleNamespace()),
                            ('_key_concept_words', lambda: []), ('_warn_key_concepts_empty', lambda title: None), ('_update_log_field', lambda text: None)):
            object.__setattr__(self, name, value)
    def __getattribute__(self, name):
        if not name.startswith('_log') and not name.startswith('__'): object.__getattribute__(self, '_log')['reads'].add(name)
        return object.__getattribute__(self, name)
    def __setattr__(self, name, value):
        object.__getattribute__(self, '_log')['writes'].append(name); object.__setattr__(self, name, value)

class FakeSC:
    def __init__(self, app, ctl): object.__setattr__(app, 'search_controller', self); self.app = app; self.ctl = ctl
    def do_search(self):
        text = self.app.query_entry.get(); self.ctl.hide_vector_visualization()
        nb = NEIGHBORS.get(text); wp = self.app.word_panel
        if nb is None: wp._last_neighbors = None; return
        wp._last_neighbors, wp._last_query_word, wp._last_vector_key = nb, text, 'ft'

def build():
    app = RecordingApp(); ctl = vc.VisualizationController(app); FakeSC(app, ctl); app.query_entry.insert(0, 'альфа'); app.search_controller.do_search()
    return app, ctl
def vecs(app, q): return app.vector_model_manager.get_word_vectors('ft', [q] + [x for x, _ in NEIGHBORS[q]])

app, ctl = build()
ctl._do_visualize(vecs(app, 'альфа'), 'альфа', dims=2, vector_key='ft'); app.vector_viz_canvas.click('бета'); app.vector_viz_canvas.click('гамма')
check('2D: два клика вглубь — история 2, кнопка «Назад» создана контроллером без настоящего окна', len(ctl._viz_history) == 2 and ctl.btn_viz_back is not None and ctl.btn_viz_back.placed)
ctl.btn_viz_back.options['command'](); ctl.btn_viz_back.options['command']()
check('Назад, Назад — вернулись к исходной, история пуста, кнопка скрыта', ctl._viz_history == [] and not ctl.btn_viz_back.placed and app.query_entry.get() == 'альфа')
ctl._do_visualize_tsne(vecs(app, 'альфа'), 'альфа', dims=2, vector_key='ft')
ctl.show_network_graph(vecs(app, 'альфа'), 'альфа', 'ft', threshold=0.3); app.vector_viz_canvas.click('бета')
ctl.show_radial_layout(vecs(app, 'альфа'), 'альфа', 'ft')
ctl.show_bar_chart(NEIGHBORS['бета'], 'бета'); ctl.show_heatmap(vecs(app, 'бета'), 'бета')
vd = {x: np.random.RandomState(zlib.crc32(x.encode())).randn(20) for x in ['альфа', 'бета', 'гамма', 'дельта', 'эпсилон']}
ctl.show_full_space_cloud(vd, 'ft', label_zoom_threshold=1.0); app.vector_viz_canvas.click('альфа')
reads = app._log['reads']
check('ГРАНИЦА: за прогон 2D/t-SNE/граф/радиальная/столбцы/тепловая карта/«всё пространство» контроллер обратился к окну ТОЛЬКО к документированным членам', reads <= CONTRACT | {'search_controller'}, str(sorted(reads - CONTRACT)))
check('и прогон действительно использовал основные из них (иначе проверка пустая)', {'result_text', 'vector_viz_canvas', 'query_entry', 'word_panel', 'search_controller', 'vector_model_manager'} <= reads, str(sorted(reads)))
check('контроллер ничего не ЗАПИСЫВАЕТ в окно (всё его состояние — у него самого)', app._log['writes'] == [], str(app._log['writes']))
check('второй независимый контроллер имеет своё состояние (не общее между экземплярами)', vc.VisualizationController(app)._viz_history == [] and vc.VisualizationController(app)._viz_history is not ctl._viz_history)

# ===================== C. внешний вызов: панель слов зовёт контроллер =====================
import ui.word_panel as wpm
calls = []
wp = wpm.WordPanel.__new__(wpm.WordPanel); wp.main_app = types.SimpleNamespace(viz=types.SimpleNamespace(show_vector_viz_menu=lambda *a: calls.append(a)))
wp._last_neighbors = [('бета', .9)]; wp._last_query_word = 'альфа'; wp._last_vector_key = 'ft'
wp._on_viz_button_click()
check('кнопка визуализаций в панели слов открывает меню контроллера (main_app.viz.show_vector_viz_menu)', calls == [('альфа', [('бета', .9)], 'ft')], str(calls))
wp._last_neighbors = None; calls.clear(); wp._on_viz_button_click()
check('без соседей меню не открывается', calls == [])
# ===================== D. слои и алгоритмы =====================
def imports_of(rel):
    """Модули, которые файл импортирует при работе (импорты под `if TYPE_CHECKING:` — только для аннотаций — не считаются)."""
    tree = ast.parse(read(rel)); typing_only = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == 'TYPE_CHECKING':
            typing_only |= {id(sub) for sub in ast.walk(n)}
    names = set()
    for n in ast.walk(tree):
        if id(n) in typing_only: continue
        if isinstance(n, ast.Import): names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0: names.add(n.module or '')
    return names
is_ui = lambda m: m == 'ui' or m.startswith('ui.')
utils_ui = [rel for rel in project_sources(ROOT) if rel.startswith('utils/') and any(is_ui(m) for m in imports_of(rel))]
check('слой utils не зависит от ui (алгоритмы не знают про окна)', not utils_ui, str(utils_ui))
services_ui = {rel: sorted(m for m in imports_of(rel) if is_ui(m)) for rel in project_sources(ROOT) if rel.startswith('services/')}
services_ui = {k: v for k, v in services_ui.items() if v}
check('слой services не зависит от ui: сообщения показываются через services.dialogs, виджеты передаёт окно', not services_ui, str(services_ui))
vv_src = read('ui/vector_visualization.py')
check('алгоритмы анализа текста и векторов живут в utils/ (ui/vector_visualization.py — только 3D-страница и реэкспорт под прежними именами)',
      len(vv_src.splitlines()) <= 120 and 'def reduce_to_dims' not in vv_src and 'def build_cooccurrence_graph' not in vv_src
      and 'def reduce_to_dims' in read('utils/vector_analytics.py') and 'def build_cooccurrence_graph' in read('utils/text_analytics.py'))
import ui.vector_visualization as vvmod
used = set()
for rel in project_sources(ROOT):
    used |= set(re.findall(r'\bvector_visualization\.([A-Za-z_]\w*)', read(rel))) - {'py'}
check(f'каждое vector_visualization.имя, которым пользуется проект ({len(used)} шт.), существует (реэкспорт ничего не потерял)', all(hasattr(vvmod, n) for n in used), str(sorted(n for n in used if not hasattr(vvmod, n))))
# ===================== E. диалоги сервисов =====================
import contextlib, io
from services import dialogs
import services.file_manager as fmm, services.index_manager as imm, services.search_controller as scm
err = io.StringIO()
with contextlib.redirect_stderr(err):
    console = dialogs.ConsoleDialogs(); r = (console.showinfo('Заг', 'Текст'), console.showerror('E', 'ошибка'), console.askyesno('В', 'Да?'), console.askokcancel('В', 'ОК?'), console.ask_choice('В', 'Выбор'))
check('запасная реализация: сообщения идут в stderr (не пропадают), на вопросы отвечает «нет», ничего не падает', r == (None, None, False, False, None) and 'Заг' in err.getvalue() and 'ошибка' in err.getvalue())
calls = []
class Recorder:
    def showerror(self, *a, **k): calls.append(('showerror', a, k)); return True
    def askyesno(self, *a, **k): calls.append(('askyesno', a, k)); return True
saved = dialogs.get_backend(); dialogs.set_backend(Recorder())
try: r1 = dialogs.messagebox.showerror('T', 'M', parent='P'); r2 = dialogs.messagebox.askyesno('Q', 'M?')
finally: dialogs.set_backend(saved)
check('посредник передаёт вызов ТЕКУЩЕЙ реализации со всеми аргументами и возвращает её ответ (реализацию можно сменить после импорта)',
      calls == [('showerror', ('T', 'M'), {'parent': 'P'}), ('askyesno', ('Q', 'M?'), {})] and (r1, r2) == (True, True))
check('сервисы берут messagebox из services.dialogs (FileManager, IndexManager, SearchController)', fmm.messagebox is dialogs.messagebox and imm.messagebox is dialogs.messagebox and scm.messagebox is dialogs.messagebox)
check('по умолчанию зарегистрирована запасная реализация (сервисы работают и без окна)', isinstance(dialogs.get_backend(), dialogs.ConsoleDialogs))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
