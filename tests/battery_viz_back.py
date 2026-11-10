import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import sys, types, zlib
import numpy as np
import tkinter as tk

# Кнопка, запоминающая place()/place_forget() — по ним видно, показана ли «Назад»
class TrackingButton(tk.Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw); self.placed = False
    def place(self, **kw): self.placed = True; self.place_kw = kw
    def place_forget(self): self.placed = False
tk.Button = TrackingButton

import ui.app_window as aw
from ui.visualization_controller import VisualizationController
from ui import vector_visualization as vv

try:
    import sklearn; HAVE_SK = True
except ImportError:
    HAVE_SK = False
    # без sklearn подставляем детерминированные раскладки — проверяется навигация, а не математика
    def _fake_reduce(vectors, n):
        words = list(vectors); return words, [(i * 1.0, (i * 7 % 5) * 1.0) for i in range(len(words))]
    vv.reduce_to_dims = _fake_reduce; vv.reduce_to_dims_tsne = _fake_reduce
    vv.compute_radial_layout = lambda vectors, q, n_sectors=None: (list(vectors), [(0.1 * i, 0.05 * i) for i in range(len(vectors))])
print("sklearn:", "есть (настоящие PCA/t-SNE/KMeans)" if HAVE_SK else "нет (подставные раскладки)")

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

# ---------------- подставные виджеты ----------------
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
    def title(self):
        for text, _ in self.items:
            if any(m in text for m in ('колесо мыши', 'в центре', 'Граф связей')): return text
        return ''
    def click(self, word):
        for text, tags in self.items:
            if text == word:
                for tag in tags:
                    if (tag, '<Button-1>') in self.tag_binds:
                        return self.tag_binds[(tag, '<Button-1>')](None)
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
    def __init__(self): self._last_neighbors = None; self._last_query_word = None; self._last_vector_key = None; self.cleared = 0
    def clear(self): self.cleared += 1; self._last_neighbors = None
class FakeVMM:
    def get_word_vectors(self, key, words):
        return {w: np.random.RandomState(zlib.crc32(w.encode())).randn(20) for w in words}

NEIGHBORS = {
    'альфа': [('бета', .9), ('гамма', .8), ('дельта', .7), ('омега', .6)],
    'бета': [('альфа', .9), ('гамма', .8), ('дельта', .7), ('эпсилон', .6)],
    'гамма': [('альфа', .9), ('бета', .8), ('дельта', .7), ('эпсилон', .6)],
    'дельта': [('альфа', .9), ('бета', .8), ('гамма', .7), ('эпсилон', .6)],
}
for i in range(10):   # кольцо для проверки предела глубины
    NEIGHBORS[f'w{i}'] = [(f'w{(i+1)%10}', .9), (f'w{(i+2)%10}', .8), (f'w{(i+3)%10}', .7), (f'w{(i-1)%10}', .6)]

class FakeSC:
    def __init__(self, app): self.app = app; self.calls = []
    def do_search(self):
        text = self.app.query_entry.get(); self.calls.append(text)
        self.app.viz.hide_vector_visualization()      # как настоящий do_search в начале
        wp = self.app.word_panel; nb = NEIGHBORS.get(text)
        if nb is None: wp._last_neighbors = None; return
        wp._last_neighbors, wp._last_query_word, wp._last_vector_key = nb, text, 'ft'

def make(query='альфа'):
    w = aw.AppWindow.__new__(aw.AppWindow)
    w.result_text = FakeText(); w.vector_viz_canvas = FakeCanvas(); w.query_entry = FakeEntry()
    w.word_panel = FakeWordPanel(); w.search_controller = FakeSC(w); w.vector_model_manager = FakeVMM()
    w.viz = VisualizationController(w)   # визуализации и навигация «Назад» — отдельный объект; окно — владелец виджетов
    w._variations_excluded = False
    w.btn_variations_toggle = tk.Widget()
    if query:
        w.query_entry.insert(0, query); w.search_controller.do_search()
    return w

def vecs(w, q): return w.vector_model_manager.get_word_vectors('ft', [q] + [x for x, _ in NEIGHBORS[q]])
def back_shown(w): return w.viz.btn_viz_back is not None and w.viz.btn_viz_back.placed
def title(w): return w.vector_viz_canvas.title()

# ===== S1: цепочка 2D: альфа -> бета -> гамма, затем Назад, Назад =====
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft')
check('исходная визуализация: кнопки «Назад» нет, истории нет', not back_shown(w) and w.viz._viz_history == [])
check('исходная визуализация показана', '«альфа»' in title(w) and w.vector_viz_canvas.mapped)
w.vector_viz_canvas.click('бета')
check('клик: запрос стал «бета», уровень «бета» показан, в истории 1', w.query_entry.get() == 'бета' and '«бета»' in title(w) and len(w.viz._viz_history) == 1)
check('кнопка «Назад» появилась и называет уровень, куда вернёт', back_shown(w) and 'альфа' in w.viz.btn_viz_back.options['text'], w.viz.btn_viz_back.options['text'] if w.viz.btn_viz_back else '')
check('кнопка внизу слева (не закрывает заголовок вверху)', w.viz.btn_viz_back.place_kw.get('anchor') == 'sw' and w.viz.btn_viz_back.place_kw.get('rely') == 1.0)
w.vector_viz_canvas.click('гамма')
check('второй клик: уровень «гамма», в истории 2, на кнопке счётчик уровней', '«гамма»' in title(w) and len(w.viz._viz_history) == 2 and '(2)' in w.viz.btn_viz_back.options['text'] and 'бета' in w.viz.btn_viz_back.options['text'], w.viz.btn_viz_back.options['text'])
n_calls = len(w.search_controller.calls)
w.viz.btn_viz_back.options['command']()
check('Назад -> уровень «бета»: запрос и результаты восстановлены (поиск выполнен заново)', w.query_entry.get() == 'бета' and w.search_controller.calls[-1] == 'бета' and len(w.search_controller.calls) == n_calls + 1 and '«бета»' in title(w))
check('после первого Назад в истории 1, кнопка на месте и ведёт к «альфа»', len(w.viz._viz_history) == 1 and back_shown(w) and 'альфа' in w.viz.btn_viz_back.options['text'])
w.viz.btn_viz_back.options['command']()
check('Назад -> исходная визуализация «альфа»', w.query_entry.get() == 'альфа' and '«альфа»' in title(w) and w.search_controller.calls[-1] == 'альфа')
check('вернулись к исходной: история пуста и кнопка скрыта', w.viz._viz_history == [] and not back_shown(w))
w.vector_viz_canvas.click('дельта')
check('из исходной можно снова пойти вперёд (цепочка начинается заново)', '«дельта»' in title(w) and len(w.viz._viz_history) == 1 and back_shown(w))

# ===== S2: масштаб и сдвиг сохраняются =====
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft')
st = w.viz._current_viz['view_state']; st['zoom'] = 3.0; st['pan_x'] = -50.0; st['pan_y'] = 20.0
w.vector_viz_canvas.click('бета')
check('новый уровень открывается с видом по умолчанию', w.viz._current_viz['view_state']['zoom'] == 1.0 and w.viz._current_viz['view_state']['pan_x'] == 0.0)
w.viz.btn_viz_back.options['command']()
st = w.viz._current_viz['view_state']
check('после Назад масштаб и сдвиг те же, что были (3.0 / -50 / 20)', (st['zoom'], st['pan_x'], st['pan_y']) == (3.0, -50.0, 20.0), str(st))

# ===== S3: t-SNE: Назад возвращает именно t-SNE, хотя клик открывал PCA =====
w = make(); w.viz._do_visualize_tsne(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft')
check('исходная — t-SNE', 't-SNE' in title(w), title(w))
w.vector_viz_canvas.click('бета')
check('уровень после клика — PCA (как и раньше)', 'PCA' in title(w), title(w))
w.viz.btn_viz_back.options['command']()
check('Назад вернул именно t-SNE', 't-SNE' in title(w) and '«альфа»' in title(w), title(w))

# ===== S4: граф-сеть: тот же тип и порог туда и обратно =====
w = make(); w.viz.show_network_graph(vecs(w, 'альфа'), 'альфа', 'ft', threshold=0.3)
w.vector_viz_canvas.click('бета')
check('клик в графе остаётся в графе с тем же порогом 0.3', 'Граф связей' in title(w) and '«бета»' in title(w) and '0.3' in title(w), title(w))
w.viz.btn_viz_back.options['command']()
check('Назад -> граф «альфа», порог 0.3', 'Граф связей' in title(w) and '«альфа»' in title(w) and '0.3' in title(w), title(w))

# ===== S5: радиальная =====
w = make(); w.viz.show_radial_layout(vecs(w, 'альфа'), 'альфа', 'ft')
w.vector_viz_canvas.click('бета')
check('клик в радиальной остаётся в радиальной', 'в центре' in title(w) and '«бета»' in title(w), title(w))
w.viz.btn_viz_back.options['command']()
check('Назад -> радиальная «альфа»', 'в центре' in title(w) and '«альфа»' in title(w), title(w))

# ===== S6: новая визуализация из меню начинает цепочку заново =====
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft'); w.vector_viz_canvas.click('бета')
check('предпосылка: цепочка есть', len(w.viz._viz_history) == 1 and back_shown(w))
w.viz.show_bar_chart(NEIGHBORS['бета'], 'бета')
check('столбчатая из меню: история сброшена, «Назад» скрыта', w.viz._viz_history == [] and not back_shown(w))
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft'); w.vector_viz_canvas.click('бета')
w.viz.show_heatmap(vecs(w, 'бета'), 'бета')
check('тепловая карта из меню: история сброшена, «Назад» скрыта', w.viz._viz_history == [] and not back_shown(w))
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft'); w.vector_viz_canvas.click('бета')
w.viz.show_network_graph(vecs(w, 'бета'), 'бета', 'ft')
check('другая кликабельная визуализация из меню — тоже новое начало (история пуста)', w.viz._viz_history == [] and not back_shown(w))

# ===== S7: обычный поиск обрывает цепочку =====
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft'); w.vector_viz_canvas.click('бета')
w.query_entry.insert(0, 'гамма'); w.search_controller.do_search()
check('обычный поиск: визуализация скрыта, история сброшена, кнопка скрыта', not w.vector_viz_canvas.mapped and w.viz._viz_history == [] and not back_shown(w))
check('и «Назад» ничего не делает без истории', (w.viz._viz_go_back(), True)[1] and not w.vector_viz_canvas.mapped)

# ===== S8: пересчёт словоформ не рвёт цепочку =====
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft'); w.vector_viz_canvas.click('бета')
w.viz._last_viz_revisualize = w.viz._visualize_2d_for
w.toggle_word_variations()
check('«−В/+В» посреди цепочки: история цела, «Назад» на месте, визуализация показана',
      len(w.viz._viz_history) == 1 and back_shown(w) and w.vector_viz_canvas.mapped and '«бета»' in title(w))
w.viz.btn_viz_back.options['command']()
check('и «Назад» после этого ведёт на прежний уровень', '«альфа»' in title(w) and w.viz._viz_history == [])
check('режим перехода сброшен', w.viz._viz_nav_mode is None)

# ===== S9: клик по слову без соседей =====
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft')
w.vector_viz_canvas.click('омега')
check('у слова нет соседей: на экране обычный текст, цепочка оборвана, «Назад» скрыта', not w.vector_viz_canvas.mapped and w.viz._viz_history == [] and not back_shown(w) and w.viz._viz_nav_mode is None)

# ===== S10: «Всё пространство» без запроса =====
w = make(query='')
vd = {x: np.random.RandomState(zlib.crc32(x.encode())).randn(20) for x in ['альфа', 'бета', 'гамма', 'дельта', 'эпсилон']}
w.viz.show_full_space_cloud(vd, 'ft', label_zoom_threshold=1.0)
check('облако показано', 'Всё пространство' in title(w) or any('Всё пространство' in t for t, _ in w.vector_viz_canvas.items))
w.vector_viz_canvas.click('альфа')
check('клик в облаке открывает обычный уровень по слову', w.query_entry.get() == 'альфа' and '«альфа»' in title(w) and len(w.viz._viz_history) == 1)
check('кнопка называет облако', 'всё пространство' in w.viz.btn_viz_back.options['text'], w.viz.btn_viz_back.options['text'])
calls = len(w.search_controller.calls); cleared = w.word_panel.cleared
w.viz.btn_viz_back.options['command']()
check('Назад в облако: запрос снова пуст, поиск НЕ запускался, окно «Совпадения» очищено',
      w.query_entry.get() == '' and len(w.search_controller.calls) == calls and w.word_panel.cleared == cleared + 1)
check('облако показано снова, история пуста', any('Всё пространство' in t for t, _ in w.vector_viz_canvas.items) and w.viz._viz_history == [])

# ===== S11: предел глубины =====
w = make(query='w0'); w.viz._VIZ_HISTORY_LIMIT = 3
w.viz._do_visualize(vecs(w, 'w0'), 'w0', dims=2, vector_key='ft')
cur = 'w0'
for _ in range(7):
    nxt = NEIGHBORS[cur][0][0]; w.vector_viz_canvas.click(nxt); cur = nxt
check('история не растёт без предела (лимит 3 после 7 переходов)', len(w.viz._viz_history) == 3, str(len(w.viz._viz_history)))
for _ in range(3): w.viz.btn_viz_back.options['command']()
check('после трёх «Назад» кнопка исчезла (старые уровни за пределом отброшены)', w.viz._viz_history == [] and not back_shown(w))

# ===== S12: сбой перерисовки при «Назад» =====
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft'); w.vector_viz_canvas.click('бета')
def boom(view): raise RuntimeError("перерисовка упала")
w.viz._viz_history[-1]['render'] = boom
try: w.viz._viz_go_back(); raised = False
except RuntimeError: raised = True
check('сбой render при «Назад»: режим перехода сброшен, цепочка очищена, программа не зависла в режиме "back"', raised and w.viz._viz_nav_mode is None and w.viz._viz_history == [])
w.vector_viz_canvas.pack(); w.query_entry.insert(0, 'гамма'); w.search_controller.do_search()
check('после сбоя обычный поиск работает как обычно', w.viz._viz_nav_mode is None and w.query_entry.get() == 'гамма')

# ===== S13: кнопка создаётся один раз =====
w = make(); w.viz._do_visualize(vecs(w, 'альфа'), 'альфа', dims=2, vector_key='ft'); w.vector_viz_canvas.click('бета'); first = w.viz.btn_viz_back
w.vector_viz_canvas.click('гамма'); w.viz.btn_viz_back.options['command'](); w.viz.btn_viz_back.options['command']()
check('одна и та же кнопка переиспользуется (не плодятся виджеты)', w.viz.btn_viz_back is first)
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
