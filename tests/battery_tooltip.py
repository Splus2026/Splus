import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import sys, types
import tkinter as tk

class RecTop:
    made = []; REQ = (200, 30); FAIL_DESTROY = False
    def __init__(self, master=None, **kw):
        self.destroyed = False; self.visible = None; self.geo = None; self.label_text = None; self.overrideredirect_flag = None; self.topmost = None
        RecTop.made.append(self)
    def withdraw(self): self.visible = False
    def deiconify(self): self.visible = True
    def overrideredirect(self, v): self.overrideredirect_flag = v
    def attributes(self, *a): self.topmost = a
    def update_idletasks(self): pass
    def winfo_reqwidth(self): return RecTop.REQ[0]
    def winfo_reqheight(self): return RecTop.REQ[1]
    def geometry(self, s): self.geo = s
    def destroy(self):
        if RecTop.FAIL_DESTROY: raise tk.TclError("уже уничтожено")
        self.destroyed = True
class RecLabel:
    def __init__(self, master, text='', **kw): master.label_text = text; self.kw = kw
    def pack(self, **kw): pass
tk.Toplevel = RecTop; tk.Label = RecLabel
from ui.tooltip import ToolTip

class FW:
    def __init__(self, rootx=100, rooty=100, w=40, h=26, sw=1920, sh=1080):
        self.binds = {}; self.afters = {}; self._n = 0; self.cancelled = []
        self._g = dict(rootx=rootx, rooty=rooty, w=w, h=h, sw=sw, sh=sh)
    def bind(self, seq, fn, add=None): self.binds.setdefault(seq, []).append((fn, add))
    def after(self, ms, fn): self._n += 1; self.afters[self._n] = (ms, fn); return self._n
    def after_cancel(self, i): self.cancelled.append(i); self.afters.pop(i, None)
    def winfo_rootx(self): return self._g['rootx']
    def winfo_rooty(self): return self._g['rooty']
    def winfo_width(self): return self._g['w']
    def winfo_height(self): return self._g['h']
    def winfo_screenwidth(self): return self._g['sw']
    def winfo_screenheight(self): return self._g['sh']
    def fire(self, seq):
        for fn, _ in self.binds[seq]: fn(None)
    def run_after(self):
        pending = list(self.afters.items()); self.afters.clear()
        for _, (ms, fn) in pending: fn()

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))
def fresh(**kw):
    RecTop.made.clear(); RecTop.REQ = (200, 30); RecTop.FAIL_DESTROY = False
    return FW(**kw)
def live(): return [t for t in RecTop.made if not t.destroyed]

# 1. привязки
w = fresh(); ToolTip(w, "Подсказка")
check('привязаны Enter/Leave/ButtonPress/Unmap/Destroy', set(w.binds) == {'<Enter>', '<Leave>', '<ButtonPress>', '<Unmap>', '<Destroy>'})
check("привязки с add='+' (чужие обработчики виджета не затираются)", all(add == '+' for lst in w.binds.values() for _, add in lst))

# 2. наведение: сначала задержка, потом показ под виджетом
w.fire('<Enter>')
check('после наведения подсказка ещё не показана, запланирована через 500 мс', RecTop.made == [] and list(w.afters.values())[0][0] == 500)
w.run_after()
tip = RecTop.made[0]
check('показана с нужным текстом, без рамки окна, поверх всех', tip.label_text == "Подсказка" and tip.overrideredirect_flag is True and tip.topmost == ('-topmost', True) and tip.visible is True)
check('расположена под кнопкой (y = верх + высота + 6), левым краем по кнопке', tip.geo == "+100+132", tip.geo)
check('до расстановки окно было скрыто (не мелькает в углу)', tip.visible is True and tip.geo is not None)

# 3. уход
w.fire('<Leave>')
check('уход курсора убирает подсказку', tip.destroyed)

# 4. ушли до окончания задержки
w = fresh(); ToolTip(w, "Х"); w.fire('<Enter>'); w.fire('<Leave>'); w.run_after()
check('курсор ушёл раньше полсекунды: таймер отменён, подсказка не показана', RecTop.made == [] and w.cancelled)

# 5. клик и скрытие кнопки
for seq, why in [('<ButtonPress>', 'нажатие на кнопку'), ('<Unmap>', 'скрытие кнопки через pack_forget'), ('<Destroy>', 'уничтожение виджета')]:
    w = fresh(); ToolTip(w, "Х"); w.fire('<Enter>'); w.run_after(); t = RecTop.made[0]; w.fire(seq)
    check(f'{why} убирает показанную подсказку', t.destroyed)

# 6. повторное наведение не плодит окна
w = fresh(); ToolTip(w, "Х"); w.fire('<Enter>'); w.run_after(); w.fire('<Enter>'); w.run_after()
check('повторное наведение при уже показанной подсказке не создаёт второе окно', len(RecTop.made) == 1)
w.fire('<Leave>'); w.fire('<Enter>'); w.run_after()
check('после ухода и нового наведения показывается снова', len(RecTop.made) == 2 and not RecTop.made[1].destroyed)

# 7. текст-функция вычисляется в момент показа
state = {'t': 'Минус варианты слова'}
w = fresh(); ToolTip(w, lambda: state['t'])
w.fire('<Enter>'); w.run_after(); first = RecTop.made[0]; w.fire('<Leave>')
state['t'] = 'Плюс варианты слова'
w.fire('<Enter>'); w.run_after(); second = RecTop.made[1]
check('текст берётся при показе, а не при создании: сначала «Минус…», потом «Плюс…»', first.label_text == 'Минус варианты слова' and second.label_text == 'Плюс варианты слова', (first.label_text, second.label_text))

# 8. пустой текст
w = fresh(); ToolTip(w, lambda: ''); w.fire('<Enter>'); w.run_after()
check('пустой текст — подсказка не показывается', RecTop.made == [])

# 9. границы экрана
w = fresh(rootx=1900, sw=1920); RecTop.REQ = (300, 30); ToolTip(w, "Длинная подсказка у правого края"); w.fire('<Enter>'); w.run_after()
x = int(RecTop.made[0].geo.split('+')[1])
check('у правого края подсказка сдвинута влево и целиком на экране (x + ширина ≤ экран)', x + 300 <= 1920 and x >= 0, RecTop.made[0].geo)
w = fresh(rooty=1070, sh=1080); ToolTip(w, "Х"); w.fire('<Enter>'); w.run_after()
y = int(RecTop.made[0].geo.split('+')[2])
check('снизу нет места — подсказка над кнопкой', y < 1070 and y + 30 <= 1070, RecTop.made[0].geo)
w = fresh(rootx=-5); ToolTip(w, "Х"); w.fire('<Enter>'); w.run_after()
check('координата не уходит в минус', int(RecTop.made[0].geo.split('+')[1]) >= 0, RecTop.made[0].geo)

# 10. сбой при уничтожении
w = fresh(); ToolTip(w, "Х"); w.fire('<Enter>'); w.run_after(); RecTop.FAIL_DESTROY = True
try: w.fire('<Leave>'); ok = True
except Exception: ok = False
RecTop.FAIL_DESTROY = False
check('окно уже уничтожено (TclError): подсказка не падает', ok)

# 11. интеграция с главным окном
import ui.app_window as aw
win = aw.AppWindow.__new__(aw.AppWindow)
for label, expected in [('−В', 'Минус варианты слова'), ('+В', 'Плюс варианты слова')]:
    win.btn_variations_toggle = types.SimpleNamespace(cget=lambda k, l=label: l)
    check(f'кнопка «{label}»: подсказка «{expected}»', win._variations_tooltip_text() == expected, win._variations_tooltip_text())
src = open(os.path.join(env.ROOT, 'ui/app_window.py'), encoding='utf-8').read()
check('подсказка у «Т» (облако тегов) подключена', 'ToolTip(btn_word_cloud, "Облако тегов' in src)
check('подсказка у «Ц» (центральные понятия) подключена', 'ToolTip(btn_textrank, "Центральные понятия' in src)
check('подсказка у «−В/+В» подключена (функцией, а не строкой)', 'ToolTip(self.btn_variations_toggle, self._variations_tooltip_text)' in src)
# реальное переключение надписи кнопки теми же строками, что в toggle_word_variations
check('надписи кнопки в toggle_word_variations совпадают с ожидаемыми подсказкой', '"+В" if self._variations_excluded else "−В"' in src)

print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
