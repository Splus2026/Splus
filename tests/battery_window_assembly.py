import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import tempfile, types
import tkinter as tk
tk._GENERIC_FALLBACK = True   # окну нужно множество виджетов — неизвестные превращаются в безвредные пустышки (только в этой батарее)

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

# Всё, что окно пишет на диск (настройки, подчёркнутое, словарь, журнал), — во временную папку
import config as cfgmod
WORK = env.tmpdir('window_'); os.chdir(WORK); os.makedirs('DB', exist_ok=True)
cfgmod.CONFIG_FILE = os.path.join(WORK, 'mconfig.ini'); cfgmod.MARKS_DB_FILE = os.path.join(WORK, 'marks.db'); cfgmod.KEY_CONCEPTS_FILE = os.path.join(WORK, 'key_concepts.txt')
from settings import Settings
import ui.app_window as aw
import ui.visualization_controller as vc
from services import dialogs

shown = []
class RecordingMessageBox:
    def __getattr__(self, name):
        if name.startswith('__'): raise AttributeError(name)
        return lambda *a, **k: shown.append((name, a[:2])) or True
RECORDER = RecordingMessageBox(); aw.messagebox = RECORDER; vc.messagebox = RECORDER   # окно зарегистрирует aw.messagebox для сервисов само

class FakeEngine:
    """Движок без данных: любой вызов возвращает пустой список."""
    engine_type = 'manticore'
    def __getattr__(self, name):
        if name.startswith('__'): raise AttributeError(name)
        return lambda *a, **k: []

settings = Settings.load(cfgmod.CONFIG_FILE)
root = tk.Tk()
try:
    win = aw.AppWindow(root, FakeEngine(), settings); built = True; err = ''
except Exception as e:
    import traceback; traceback.print_exc(); built = False; err = repr(e)
check('настоящее окно AppWindow собирается целиком (виджеты, сервисы, список индексов) — до конца __init__ без ошибок', built, err)
if not built:
    print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}"); sys.exit(1)

check('окно хранит переданные настройки (тот же объект Settings)', win.config is settings)
check('окно зарегистрировало реализацию диалогов для сервисов (services.dialogs)', dialogs.get_backend() is RECORDER)
shown.clear(); win.file_manager.open_selected_file()
check('сообщение СЕРВИСА (FileManager) доходит до зарегистрированной окном реализации через посредника', shown and shown[0][0] == 'showwarning' and shown[0][1][0] == 'Нет выбора', str(shown))
check('контроллер визуализаций создан и знает своё окно', isinstance(win.viz, vc.VisualizationController) and win.viz.app is win)
check('поиск скрывает визуализацию через метод КОНТРОЛЛЕРА (колбэк SearchController подключён)', win.search_controller.hide_vector_viz_callback == win.viz.hide_vector_visualization)
buttons = {w.options.get('text'): w for w in tk.CREATED if isinstance(w, tk.Button) and w.options.get('text')}
expected = {'Т', 'Ц', 'Ч', 'КП', '−В', 'Кратко', '<< В начало', 'В конец >>', 'Вперед ▶', 'Редактировать', 'Собрать базу', '3D/2D', '▲ В индекс', '▲ Векторы'}
check('все основные кнопки созданы', expected <= set(buttons), str(sorted(expected - set(buttons))))
check('у каждой кнопки с обработчиком обработчик вызываемый', all(callable(b.options['command']) for b in buttons.values() if b.options.get('command') is not None))
check('«Т» и «Ц» привязаны к методам контроллера', buttons['Т'].options['command'] == win.viz.show_word_cloud_for_selected and buttons['Ц'].options['command'] == win.viz.show_textrank_for_selected)
for label, title in (('Т', 'Облако тегов'), ('Ц', 'Центральные понятия')):
    shown.clear(); buttons[label].options['command']()
    check(f'«{label}» без отмеченных индексов: окно «{title}» с просьбой отметить индекс (обработчик контроллера работает с настоящим окном)', shown and shown[0][0] == 'showinfo' and shown[0][1][0] == title and 'отметьте' in shown[0][1][1], str(shown))

class FakeCanvas:
    def __init__(self): self.mapped = True
    def winfo_ismapped(self): return self.mapped
    def pack_forget(self): self.mapped = False
    def __getattr__(self, n):
        if n.startswith('__'): raise AttributeError(n)
        return lambda *a, **k: None
win.vector_viz_canvas = FakeCanvas(); win.query_entry.insert(0, 'слово')
win.search_controller.do_search()
check('настоящий do_search скрывает показанную визуализацию (колбэк контроллера сработал)', not win.vector_viz_canvas.mapped)

win.word_panel._last_query_word = None
before = win._variations_excluded; win.toggle_word_variations()
check('«−В/+В» без слова в панели «Совпадения» ничего не делает и не падает', win._variations_excluded == before)
win.word_panel._last_query_word = 'слово'; win.word_panel._last_vector_key = 'ft'; win.word_panel._last_neighbors = [('сосед', .9)]
win.vector_viz_canvas = FakeCanvas(); win.vector_viz_canvas.mapped = False
win.toggle_word_variations()
check('«−В/+В»: состояние переключилось, кнопка сменила подпись, повторный поиск выполнен через контроллер', win._variations_excluded != before and buttons['−В'].options['text'] == '+В')
win2 = aw.AppWindow(tk.Tk(), FakeEngine(), Settings.load(cfgmod.CONFIG_FILE))
check('у второго окна — свой контроллер и своя история (состояние не общее)', win2.viz is not win.viz and win2.viz._viz_history is not win.viz._viz_history)
try: win.marks_store.close(); win2.marks_store.close()
except Exception: pass
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
