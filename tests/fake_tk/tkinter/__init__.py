"""Заглушка tkinter для проверки логики окон без графики. Состояние,
которое влияет на логику (Var, Listbox, Text, after), ведёт себя как настоящее;
остальное — no-op."""
import types

END = 'end'
EXTENDED = 'extended'
BOTH = 'both'
WORD = 'word'
_default_root = None

class TclError(Exception):
    pass

AFTER_QUEUE = []   # (callback, args) — тестовый "насос" событий выполняет их

class _Var:
    def __init__(self, master=None, value=None, name=None):
        self._v = value
    def get(self): return self._v
    def set(self, v):
        self._v = v
        for cb in getattr(self, '_traces', []):
            cb('PY_VAR', '', 'write')
    def trace_add(self, mode, cb):
        if not hasattr(self, '_traces'): self._traces = []
        self._traces.append(cb)
        return 'trace%d' % len(self._traces)

class StringVar(_Var):
    def __init__(self, master=None, value='', name=None): self._v = value
class BooleanVar(_Var):
    def __init__(self, master=None, value=False, name=None): self._v = value
class DoubleVar(_Var):
    def __init__(self, master=None, value=0.0, name=None): self._v = value

CREATED = []        # все созданные виджеты (тесты ищут кнопки/метки по тексту)
AFTER_IDS = {}
_after_counter = [0]

class Widget:
    def __init__(self, master=None, **kw):
        CREATED.append(self)
        self.master = master
        self.options = dict(kw)
        self.destroyed = False
        self.grab_calls = 0
        self.tk = types.SimpleNamespace(splitlist=lambda s: tuple(str(s).split('|')))
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *a, **k: None          # pack/grid/bind/title/geometry/... — no-op
    def config(self, **kw): self.options.update(kw)
    configure = config
    def cget(self, k): return self.options.get(k)
    def winfo_screenwidth(self): return 1920
    def winfo_screenheight(self): return 1080
    def winfo_rootx(self): return 100
    def winfo_rooty(self): return 100
    def winfo_width(self): return 1200
    def winfo_height(self): return 800
    def winfo_exists(self): return not self.destroyed
    def winfo_children(self): return [w for w in CREATED if w.master is self and not w.destroyed]
    def winfo_reqwidth(self): return 40
    def winfo_reqheight(self): return 24
    def grab_set(self): self.grab_calls += 1
    def after(self, ms, func=None, *args):
        entry = (func, args)
        AFTER_QUEUE.append(entry)
        _after_counter[0] += 1
        AFTER_IDS[_after_counter[0]] = entry
        return _after_counter[0]
    def after_cancel(self, ident):
        entry = AFTER_IDS.pop(ident, None)
        if entry is not None and entry in AFTER_QUEUE:
            AFTER_QUEUE.remove(entry)
    def destroy(self): self.destroyed = True

class Toplevel(Widget): pass
class Frame(Widget): pass
class LabelFrame(Widget): pass
class Label(Widget): pass
class Button(Widget): pass
class Entry(Widget):
    """Поле ввода с настоящим текстом (get/insert/delete): без него код вида entry.get().strip() получал бы None."""
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw); self._text = ''
    def get(self): return self._text
    def insert(self, index, text): self._text = (str(text) + self._text) if index in (0, '0') else (self._text + str(text))
    def delete(self, a, b=None): self._text = ''
class Scrollbar(Widget): pass
class Radiobutton(Widget): pass
class Checkbutton(Widget): pass

class Listbox(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self.items = []
        self._sel = []
    def insert(self, index, text): self.items.append(text)
    def delete(self, a, b=None):
        if b is None:
            del self.items[a]
        else:
            self.items.clear()
        self._sel = []
    def curselection(self): return tuple(self._sel)
    def selection_set(self, a, b=None):
        if isinstance(a, int) and b is None: self._sel.append(a)
        else: self._sel = list(range(len(self.items)))
    def size(self): return len(self.items)
    def get(self, a, b=None): return self.items[a]


# Необязательный универсальный режим (включается ТОЛЬКО в батарее, которой нужно собрать окно целиком —
# tests/battery_window_assembly.py): любое неизвестное имя tkinter превращается в безвредный виджет, а
# имена-константы (LEFT, NSEW, DISABLED...) — в строки. Остальные батареи остаются строгими: неизвестный
# виджет у них по-прежнему AttributeError, а не молчаливая пустышка.
_GENERIC_FALLBACK = False
_generic_classes = {}

def __getattr__(name):
    if name.startswith('__') or not _GENERIC_FALLBACK:
        raise AttributeError(f"module 'tkinter' has no attribute {name!r}")
    if name.isupper():
        return name.lower()
    if name[:1].isupper():
        return _generic_classes.setdefault(name, type(name, (Widget,), {}))
    raise AttributeError(f"module 'tkinter' has no attribute {name!r}")
