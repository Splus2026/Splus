"""Запись построения окна под подставным tkinter: каждое создание виджета, config и вызов (pack, grid, bind, add, menu...) попадает
   в трассу по порядку. По ней можно проверять СТРУКТУРУ интерфейса (что в какой зоне, в каком порядке упаковано, какие команды
   привязаны), не открывая настоящее окно, и сравнивать две версии кода построения (до и после рефакторинга).
   Виджеты нумеруются по порядку создания (корень — 0); команды записываются именем («AppWindow.do_search»), лямбды — «<lambda>»."""
import os, sys, types, importlib.machinery

class UITrace:
    def __init__(self, win, events, ids): self.win = win; self.events = events; self.ids = ids
    def id(self, widget): return self.ids[id(widget)]
    def new(self, wid):
        for e in self.events:
            if e[0] == 'new' and e[1] == wid: return e[2], e[3], dict(e[4])
    def calls(self, wid, method=None):
        return [(e[2], e[3], dict(e[4])) for e in self.events if e[0] == 'call' and e[1] == wid and (method is None or e[2] == method)]
    def configs(self, wid): return [dict(e[2]) for e in self.events if e[0] == 'config' and e[1] == wid]
    def layout(self, wid):
        for m, a, k in self.calls(wid):
            if m in ('pack', 'grid', 'place'): return m, k
        return None
    def position(self, wid):
        """Номер первого обращения к раскладке (pack/grid/add родителя) — для проверки порядка упаковки."""
        for i, e in enumerate(self.events):
            if e[0] == 'call' and e[1] == wid and e[2] in ('pack', 'grid', 'place'): return i
            if e[0] == 'call' and e[2] == 'add' and e[3] and e[3][0] == ('w', wid): return i
        return None
    def find(self, cls=None, **opts):
        out = []
        for e in self.events:
            if e[0] != 'new' or (cls and e[2] != cls): continue
            o = dict(e[4])
            if all(o.get(k) == norm(v) for k, v in opts.items()): out.append(e[1])
        return out
    def children(self, wid): return [e[1] for e in self.events if e[0] == 'new' and e[3] == ('w', wid)]

def norm(v, ids=None):
    import tkinter as tk
    ids = ids if ids is not None else _STATE['ids']
    if isinstance(v, tk.Widget): return ('w', ids.get(id(v), '?'))
    if isinstance(v, (str, int, float, bool, type(None))): return v
    if isinstance(v, (tuple, list)): return tuple(norm(x, ids) for x in v)
    if isinstance(v, dict): return tuple(sorted((k, norm(x, ids)) for k, x in v.items()))
    if callable(v):
        owner = getattr(v, '__self__', None); name = getattr(v, '__name__', '?')
        if name == '<lambda>': return ('fn', '<lambda>')
        return ('fn', (type(owner).__name__ + '.' if owner is not None else '') + name)
    return ('obj', type(v).__name__)

_STATE = {'ids': {}}

class _Box:
    def __getattr__(self, n):
        if n.startswith('__'): raise AttributeError(n)
        return lambda *a, **k: True
class _FakeEngine:
    def __init__(self, engine_type): self.engine_type = engine_type
    def __getattr__(self, n):
        if n.startswith('__'): raise AttributeError(n)
        return lambda *a, **k: []

def load_module_as_ui(name, path):
    """Загружает файл (например, прежнюю версию окна) как часть пакета ui — чтобы работали относительные импорты."""
    m = types.ModuleType('ui.' + name); m.__file__ = path; m.__package__ = 'ui'; sys.modules['ui.' + name] = m
    importlib.machinery.SourceFileLoader('ui.' + name, path).exec_module(m); return m

def build(module, engine_type='manticore', workdir=None):
    """Строит настоящее окно AppWindow из module под подставным tkinter и возвращает UITrace. Всё, что окно пишет на диск —
       во временную папку."""
    import tkinter as tk
    tk._GENERIC_FALLBACK = True
    from tests import env
    import config as cfgmod
    import ui.visualization_controller as vc
    from settings import Settings
    work = workdir or env.tmpdir('uitrace_'); os.chdir(work); os.makedirs('DB', exist_ok=True)
    cfgmod.CONFIG_FILE = os.path.join(work, 'mconfig.ini'); cfgmod.MARKS_DB_FILE = os.path.join(work, 'marks.db'); cfgmod.KEY_CONCEPTS_FILE = os.path.join(work, 'key_concepts.txt')
    events = []; ids = {}; _STATE['ids'] = ids
    orig_init, orig_config, orig_getattr = tk.Widget.__init__, tk.Widget.config, tk.Widget.__getattr__
    def traced_init(self, master=None, **kw):
        orig_init(self, master, **kw); ids[id(self)] = len(ids)
        events.append(('new', ids[id(self)], type(self).__name__, norm(master), norm(kw)))
    def traced_config(self, **kw):
        events.append(('config', ids.get(id(self), '?'), norm(kw))); orig_config(self, **kw)
    def traced_getattr(self, name):
        if name.startswith('__'): raise AttributeError(name)
        def call(*a, **k):
            if not name.startswith('winfo') and name not in ('after', 'after_cancel'): events.append(('call', ids.get(id(self), '?'), name, norm(a), norm(k)))
        return call
    tk.CREATED.clear(); tk.AFTER_QUEUE.clear()
    tk.Widget.__init__ = traced_init; tk.Widget.config = traced_config; tk.Widget.configure = traced_config; tk.Widget.__getattr__ = traced_getattr
    try:
        module.messagebox = _Box(); vc.messagebox = _Box()
        settings = Settings.load(cfgmod.CONFIG_FILE); root = tk.Tk()
        win = module.AppWindow(root, _FakeEngine(engine_type), settings)
    finally:
        tk.Widget.__init__, tk.Widget.config, tk.Widget.configure, tk.Widget.__getattr__ = orig_init, orig_config, orig_config, orig_getattr
    return UITrace(win, events, ids)
