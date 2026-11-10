"""Дымовая проверка на НАСТОЯЩЕМ Tk — для вашего экрана (остальные батареи идут на подставном Tk и
   не видят ошибок, которые случаются только с настоящими виджетами).

       python tests/smoke_real_tk.py          # на экране на несколько секунд появится окно программы
       python tests/smoke_real_tk.py --fake   # прогон самого скрипта на подставном Tk (для разработки)

   Собирает настоящее окно AppWindow с настоящими виджетами (движок — заглушка без данных, все файлы
   пишутся во временную папку, ваши mconfig.ini, marks.db и key_concepts.txt не трогаются), нажимает
   основные кнопки, выполняет поиск и рисует все визуализации на настоящем Canvas, включая цепочку
   «клик по слову -> новый уровень -> Назад». Печатает итог «Проверок: N, провалено: M».

   Не входит в run_all.py: нужен экран. Если какой-то шаг упал — пришлите вывод целиком."""

import os
import sys
import tempfile
import traceback
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAKE = '--fake' in sys.argv
if FAKE:
    from tests import env  # noqa: F401  (подставной tkinter и заглушки)
    import tkinter as tk
    tk._GENERIC_FALLBACK = True
else:
    import tkinter as tk
import numpy as np

results, skipped = [], []


def check(name, cond, detail=''):
    results.append(bool(cond))
    print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''), flush=True)


def skip(name, why):
    skipped.append(name)
    print(f'SKIP {name}  ({why})', flush=True)


def step(name, fn):
    """Шаг не должен ронять весь прогон: ошибка печатается с трассировкой и считается провалом."""
    try:
        fn()
    except Exception as e:
        traceback.print_exc()
        check(name, False, repr(e))


# Всё, что окно пишет на диск, — во временную папку (до импорта окна: оно запоминает пути при импорте)
import config as cfgmod  # noqa: E402
WORK = tempfile.mkdtemp(prefix='smoke_')
os.chdir(WORK)
os.makedirs('DB', exist_ok=True)
cfgmod.CONFIG_FILE = os.path.join(WORK, 'mconfig.ini')
cfgmod.MARKS_DB_FILE = os.path.join(WORK, 'marks.db')
cfgmod.KEY_CONCEPTS_FILE = os.path.join(WORK, 'key_concepts.txt')
from settings import Settings  # noqa: E402
import ui.app_window as aw  # noqa: E402
import ui.visualization_controller as vc  # noqa: E402

shown = []


class RecordingMessageBox:
    """Вместо модальных окон — запись: проверка не должна ждать нажатий."""
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *a, **k: shown.append((name, a[:2])) or True


RECORDER = RecordingMessageBox()
aw.messagebox = RECORDER
vc.messagebox = RECORDER


class FakeEngine:
    """Движок без данных: любой вызов возвращает пустой список."""
    engine_type = 'manticore'

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *a, **k: []


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def get_buttons(root):
    out = {}
    if FAKE:
        for w in tk.CREATED:
            if isinstance(w, tk.Button) and w.options.get('text'):
                out[w.options['text']] = w
        return out
    for w in walk(root):
        if isinstance(w, tk.Button):
            try:
                out[str(w.cget('text'))] = w
            except Exception:
                pass
    return out


def press(button):
    if FAKE:
        return button.options['command']()
    return button.invoke()


def button_text(button):
    return button.options.get('text') if FAKE else str(button.cget('text'))


# ===================== окно =====================
root = tk.Tk()
if not FAKE:
    root.geometry('1100x720+40+40')
settings = Settings.load(cfgmod.CONFIG_FILE)
holder = {}


def build():
    holder['win'] = aw.AppWindow(root, FakeEngine(), settings)
    if not FAKE:
        root.update()
    check('настоящее окно AppWindow собирается целиком (виджеты, сервисы, список индексов)', True)


step('сборка окна', build)
if 'win' not in holder:
    print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
    sys.exit(1)
win = holder['win']

check('контроллер визуализаций создан и знает своё окно', isinstance(win.viz, vc.VisualizationController) and win.viz.app is win)
buttons = get_buttons(root)
expected = {'Т', 'Ц', 'Ч', 'КП', '−В', 'Кратко', '<< В начало', 'В конец >>', 'Вперед ▶', 'Редактировать', 'Собрать базу', '3D/2D', '▲ В индекс', '▲ Векторы'}
check('все основные кнопки созданы', expected <= set(buttons), str(sorted(expected - set(buttons))))

for label, title in (('Т', 'Облако тегов'), ('Ц', 'Центральные понятия')):
    def press_it(label=label, title=title):
        shown.clear()
        press(buttons[label])
        check(f'«{label}» без отмеченных индексов: просьба отметить индекс (окно «{title}»)',
              shown and shown[0][0] == 'showinfo' and shown[0][1][0] == title, str(shown))
    step(f'кнопка {label}', press_it)


def do_search():
    win.query_entry.insert(0, 'слово')
    win.search_controller.do_search()
    check('поиск по настоящим виджетам (пустой результат) выполнен без ошибок', True)


step('поиск', do_search)


def toggle():
    win.word_panel._last_query_word = 'слово'
    win.word_panel._last_vector_key = 'ft'
    win.word_panel._last_neighbors = [('сосед', .9)]
    before = win._variations_excluded
    win.toggle_word_variations()
    check('«−В/+В»: состояние переключилось, подпись кнопки сменилась',
          win._variations_excluded != before and button_text(buttons['−В']) == '+В')


step('−В/+В', toggle)

# ===================== визуализации на настоящем Canvas =====================
if FAKE:
    skip('визуализации на настоящем Canvas', 'режим --fake: у подставного Tk нет холста')
else:
    class FakeVMM:
        def get_word_vectors(self, key, words):
            return {w: np.random.RandomState(zlib.crc32(w.encode())).randn(20) for w in words}

    NEIGHBORS = {
        'альфа': [('бета', .9), ('гамма', .8), ('дельта', .7), ('омега', .6)],
        'бета': [('альфа', .9), ('гамма', .8), ('дельта', .7), ('эпсилон', .6)],
    }

    def fake_do_search():
        """Как настоящий поиск в векторном режиме: скрывает визуализацию и заполняет панель «Совпадения»."""
        text = win.query_entry.get()
        win.viz.hide_vector_visualization()
        nb = NEIGHBORS.get(text)
        wp = win.word_panel
        wp._last_neighbors, wp._last_query_word, wp._last_vector_key = nb, (text if nb else None), ('ft' if nb else None)

    win.vector_model_manager = FakeVMM()
    win.search_controller.do_search = fake_do_search
    root.deiconify()
    root.update()
    vectors = win.vector_model_manager.get_word_vectors('ft', ['альфа'] + [w for w, _ in NEIGHBORS['альфа']])
    canvas = win.vector_viz_canvas

    def items():
        root.update()
        return len(canvas.find_all())

    def draw(name, fn, needs=None):
        def run():
            win.query_entry.delete(0, tk.END)
            win.query_entry.insert(0, 'альфа')
            win.viz.hide_vector_visualization()
            try:
                fn()
            except ImportError as e:
                skip(name, f'нужна библиотека: {e}')
                return
            n = items()
            check(f'{name}: на холсте нарисовано', n > 0, f'элементов {n}')
        step(name, run)

    draw('2D (PCA)', lambda: win.viz._do_visualize(vectors, 'альфа', dims=2, vector_key='ft'))

    def chain():
        win.query_entry.delete(0, tk.END)
        win.query_entry.insert(0, 'альфа')
        win.viz._do_visualize(vectors, 'альфа', dims=2, vector_key='ft')
        win.viz._on_viz_word_click('бета', 'ft')          # то же, что делает клик по слову на холсте
        root.update()
        back = win.viz.btn_viz_back
        check('клик по слову: запрос «бета», в истории 1 уровень', win.query_entry.get() == 'бета' and len(win.viz._viz_history) == 1)
        check('кнопка «Назад» — настоящий виджет на холсте, показана и называет «альфа»',
              back is not None and bool(back.winfo_ismapped()) and 'альфа' in str(back.cget('text')), str(back.cget('text')) if back is not None else 'нет кнопки')
        back.invoke()
        root.update()
        check('«Назад»: запрос «альфа», история пуста, кнопка скрыта', win.query_entry.get() == 'альфа' and win.viz._viz_history == [] and not back.winfo_ismapped())
    step('цепочка клик -> Назад', chain)

    draw('t-SNE', lambda: win.viz._do_visualize_tsne(vectors, 'альфа', dims=2, vector_key='ft'))
    draw('граф-сеть', lambda: win.viz.show_network_graph(vectors, 'альфа', 'ft', threshold=0.3))
    draw('радиальная', lambda: win.viz.show_radial_layout(vectors, 'альфа', 'ft'))
    draw('столбцы', lambda: win.viz.show_bar_chart(NEIGHBORS['альфа'], 'альфа'))
    draw('тепловая карта', lambda: win.viz.show_heatmap(vectors, 'альфа'))
    draw('дендрограмма', lambda: win.viz.show_dendrogram_viz(vectors, 'альфа'))
    draw('облако тегов', lambda: win.viz.show_word_cloud([('слово', 9), ('другое', 5), ('третье', 3), ('ещё', 2)]))
    many = win.vector_model_manager.get_word_vectors('ft', [f'слово{i}' for i in range(40)])
    draw('всё пространство', lambda: win.viz.show_full_space_cloud(many, 'ft'))

    def hide():
        win.viz.hide_vector_visualization()
        root.update()
        check('скрытие визуализации: холст не показан', not canvas.winfo_ismapped())
    step('скрытие', hide)

# ===================== завершение =====================
try:
    win.marks_store.close()
except Exception:
    pass
try:
    root.destroy()
except Exception:
    pass
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}" + (f", пропущено: {len(skipped)}" if skipped else ''))
sys.exit(0 if all(results) else 1)
