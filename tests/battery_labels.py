import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import sys, re, types
import tkinter as tk
results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

# --- записывающий Toplevel/Label для настоящего ToolTip ---
class RecTop:
    made = []
    def __init__(self, master=None, **kw): self.destroyed = False; self.text = None; RecTop.made.append(self)
    def withdraw(self): pass
    def deiconify(self): pass
    def overrideredirect(self, v): pass
    def attributes(self, *a): pass
    def update_idletasks(self): pass
    def winfo_reqwidth(self): return 120
    def winfo_reqheight(self): return 24
    def geometry(self, s): pass
    def destroy(self): self.destroyed = True
class RecLabel:
    def __init__(self, master, text='', **kw): master.text = text
    def pack(self, **kw): pass
tk.Toplevel = RecTop; tk.Label = RecLabel
from ui.tooltip import ToolTip
import ui.app_window as aw

class FakeButton:
    """Кнопка: текст + события + отложенные вызовы — как нужно ToolTip."""
    def __init__(self, text): self.opts = {'text': text}; self.binds = {}; self.afters = {}; self.n = 0
    def config(self, **k): self.opts.update(k)
    def cget(self, k): return self.opts[k]
    def bind(self, seq, fn, add=None): self.binds.setdefault(seq, []).append(fn)
    def after(self, ms, fn): self.n += 1; self.afters[self.n] = fn; return self.n
    def after_cancel(self, i): self.afters.pop(i, None)
    def winfo_rootx(self): return 400
    def winfo_rooty(self): return 60
    def winfo_width(self): return 40
    def winfo_height(self): return 26
    def winfo_screenwidth(self): return 1920
    def winfo_screenheight(self): return 1080
    def fire(self, seq):
        for fn in self.binds.get(seq, []): fn(None)
    def hover(self):
        RecTop.made.clear(); self.fire('<Enter>')
        for fn in list(self.afters.values()): fn()
        self.afters.clear()
        return RecTop.made[-1].text if RecTop.made else None

win = aw.AppWindow.__new__(aw.AppWindow)
btn = FakeButton("Кратко"); win.btn_brief_toggle = btn
state = {'brief': False}
win.search_controller = types.SimpleNamespace(toggle_brief_mode=lambda: state.update(brief=not state['brief']) or state['brief'])

# --- переключатель «Кратко» / «Всё» ---
win.toggle_brief_mode()
check('краткий режим включён -> на кнопке «Всё» (то, во что она переключит)', btn.cget('text') == 'Всё')
win.toggle_brief_mode()
check('краткий режим выключен -> на кнопке снова «Кратко»', btn.cget('text') == 'Кратко')
check('слова «Развёрнуто» на кнопке больше нет', 'Развёрнуто' not in aw.AppWindow.toggle_brief_mode.__code__.co_consts)

# --- подсказка ---
btn.config(text='Всё'); check('_brief_tooltip_text: у «Всё» — «Полный текст»', win._brief_tooltip_text() == 'Полный текст')
btn.config(text='Кратко'); check('_brief_tooltip_text: у «Кратко» подсказки нет (пустая строка)', win._brief_tooltip_text() == '')
tip = ToolTip(btn, win._brief_tooltip_text)
btn.config(text='Всё'); shown = btn.hover()
check('наведение на «Всё» показывает «Полный текст»', shown == 'Полный текст', str(shown))
btn.fire('<Leave>'); btn.config(text='Кратко'); shown = btn.hover()
check('наведение на «Кратко» ничего не показывает', shown is None, str(shown))
btn.fire('<Leave>'); win.toggle_brief_mode(); win.toggle_brief_mode()  # снова «Кратко» -> «Всё» через реальную логику
state['brief'] = False; win.toggle_brief_mode(); shown = btn.hover()
check('после реального переключения подсказка следует за надписью (стало «Всё» -> «Полный текст»)', btn.cget('text') == 'Всё' and shown == 'Полный текст', (btn.cget('text'), shown))

# --- исходник: надписи и порядок кнопок ---
src = open(os.path.join(env.ROOT, 'ui/app_window.py'), encoding='utf-8').read()
check('надпись «Индексы:» вместо «Выбор индекса:»', 'tk.Label(header_frame, text="Индексы:"' in src and 'Выбор индекса' not in src)
check('в коде интерфейса нет «Развёрнуто»/«Развернуто»', 'Развёрнуто' not in src and 'Развернуто' not in src)
check('подсказка к переключателю подключена функцией', 'ToolTip(self.btn_brief_toggle, self._brief_tooltip_text)' in src)
section = src[src.index('nav_frame = tk.Frame(center_frame'):src.index('# Верхнее и нижнее окно результатов')]
order = re.findall(r'self\.(btn_\w+)\.pack\(', section)
check('порядок слева направо: первая, назад, вперёд, в конец, «Ч», «КП», «Кратко/Всё»',
      order == ['btn_first', 'btn_back', 'btn_forward', 'btn_last', 'btn_underline', 'btn_key_concepts', 'btn_brief_toggle'], str(order))
check('отступы «Ч» и «Кратко/Всё» теперь считаются по шрифту (nav_toggle_layout), а не числами',
      "padx=toggle_layout['underline_padx']" in section and "padx=toggle_layout['brief_padx']" in section)
check('у переключателя постоянная ширина (не прыгает между «Кратко» и «Всё»)', "width=toggle_layout['brief_width']" in section)
check("«Ч» больше не пакуется справа", "btn_underline.pack(side='right'" not in src)
check("«−В/+В» по-прежнему пакуется справа (show_variations_button)", re.search(r"btn_variations_toggle\.pack\(side='right'", src) is not None)
check('подсказка «Подчеркнуть» у «Ч» на месте', 'ToolTip(self.btn_underline, "Подчеркнуть")' in src)
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
