import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import ast, types

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

# Драйвер pymysql нужен только как имя в модуле движка: настоящее соединение в проверках не создаётся (connect подменяется).
# Если драйвера нет в окружении — подставляется пустой модуль; если есть — используется настоящий.
try:
    import pymysql
except ImportError:
    pymysql = types.ModuleType('pymysql'); pymysql.connect = lambda **k: (_ for _ in ()).throw(RuntimeError('нет pymysql')); sys.modules['pymysql'] = pymysql
import engines.manticore_engine as me
import config as cfg_module

# Запуск и подключение Manticore: поиск программы, запуск и восстановление, сообщение о неудаче через колбэк (движок окон не
# создаёт), пауза после неудачи, подключение, закрытие. Время и запуск процессов подменены; файлы — во временной папке.
WORK = env.tmpdir('manticore_'); LOG = []
ns = types.SimpleNamespace
class Clock:
    def __init__(self): self.now = 1000.0
    def time(self): return self.now
    def sleep(self, s): LOG.append(('sleep', s)); self.now += s
CLOCK = Clock(); me.time = CLOCK
class FakeProc:
    def __init__(self, fail=None): self.calls = []; self.fail = fail
    def Popen(self, *a, **k):
        self.calls.append(('Popen', a, k))
        if self.fail == 'popen': raise OSError('нет файла')
    def run(self, *a, **k):
        self.calls.append(('run', a, k))
        if self.fail == 'run': raise OSError('нет прав')
    DEVNULL = -3; CREATE_NO_WINDOW = 0x08000000; STARTF_USESHOWWINDOW = 1; SW_HIDE = 0
    class STARTUPINFO:
        def __init__(self): self.dwFlags = 0; self.wShowWindow = None
def rec(name, ret=None): return lambda *a, **k: (LOG.append((name,) + a + (tuple(sorted(k.items())) if k else ())), ret)[1]

def bare(**attrs):
    """Движок без __init__ (чтобы не трогать диск и сеть): задаются только нужные атрибуты."""
    e = me.ManticoreEngine.__new__(me.ManticoreEngine)
    base = dict(host='localhost', port=9306, index='documents', conn=None, cursor=None, _current_index=None, _started_by_us=False, searchd_exe=os.path.join(WORK, 'searchd.exe'),
                conf_path=os.path.join(WORK, 'manticore.conf'), pid_file=os.path.join(WORK, 'searchd.pid'), conf_dir=WORK, manticore_log=os.path.join(WORK, 'log'), data_dir=os.path.join(WORK, 'data'))
    base.update(attrs)
    for k, v in base.items(): setattr(e, k, v)
    return e
def flow(e, running=False, launches=(False, False), exe=True):
    """Подменяет шаги запуска; launches — результаты первой и второй попыток запуска searchd."""
    seq = list(launches); LOG.clear(); CLOCK.now = 1000.0
    open(e.searchd_exe, 'w').close() if exe else (os.path.exists(e.searchd_exe) and os.remove(e.searchd_exe))
    e._is_running = lambda: running
    e._try_launch_searchd = lambda: (LOG.append(('launch',)), seq.pop(0) if seq else False)[1]
    e._kill_existing_searchd = rec('kill'); e._clear_stale_pid_file = rec('clear_pid')
    notes = []; e.on_startup_failure = lambda title, text: notes.append((title, text)); return notes
def names(): return [c[0] for c in LOG]
import io, contextlib
def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()) as out: r = fn(*a, **k)
    return r, out.getvalue()

# ===================== A. старт без searchd.exe и успешные пути =====================
e = bare(); notes = flow(e, exe=False); r, out = quiet(e._start_manticore)
check('нет searchd.exe: запуск не удался, пользователю сообщают с путём к файлу (раньше — молчаливое «False»)', r is False and len(notes) == 1 and notes[0][0] == me.MISSING_SEARCHD_TITLE and e.searchd_exe in notes[0][1] and 'launch' not in names(), str(notes))
e = bare(); notes = flow(e, running=True); r, _ = quiet(e._start_manticore)
check('Manticore уже работает: True, ничего не запускается, сообщений нет', r is True and not notes and not names())
e = bare(); notes = flow(e, launches=(True,)); r, _ = quiet(e._start_manticore)
check('запуск с первой попытки: True, без восстановления и сообщений', r is True and names() == ['launch'] and not notes and e._last_start_failure is None)
e = bare(); notes = flow(e, launches=(False, True)); r, _ = quiet(e._start_manticore)
check('не запустился с первой попытки, после восстановления запустился: порядок — запуск, снятие процесса, очистка pid, пауза 1 с, запуск; сообщений нет',
      r is True and names() == ['launch', 'kill', 'clear_pid', 'sleep', 'launch'] and ('sleep', 1) in LOG and not notes and e._last_start_failure is None, str(LOG))
# ===================== B. неудача и колбэк =====================
e = bare(); notes = flow(e, launches=(False, False)); r, out = quiet(e._start_manticore)
check('не запустился даже после восстановления: False, колбэк получает (заголовок, текст) ровно один раз; движок запоминает время неудачи', r is False and notes == [(me.STARTUP_FAILURE_TITLE, me.STARTUP_FAILURE_MESSAGE)] and e._last_start_failure == 1001.0, str(notes))
check('текст сообщения сохранён: про searchd.exe, searchd.pid и перезапуск программы', all(w in me.STARTUP_FAILURE_MESSAGE for w in ('searchd.exe', 'searchd.pid', 'перезапустите Синева+')) and me.STARTUP_FAILURE_TITLE == 'Manticore не запускается')
e = bare(); flow(e, launches=(False, False)); e.on_startup_failure = None; r, out = quiet(e._start_manticore)
check('обработчика нет (например, консольный запуск или тесты): окон нет, сообщение печатается в консоль, без исключений', r is False and 'Manticore не запускается' in out and 'searchd.pid' in out, out[-200:])
e = bare(); flow(e, launches=(False, False)); e.on_startup_failure = lambda t, m: (_ for _ in ()).throw(RuntimeError('окно не создалось')); r, out = quiet(e._start_manticore)
check('обработчик сам упал: исключение не выходит наружу (запуск программы не ломается), причина печатается', r is False and 'Не удалось показать сообщение об ошибке запуска: окно не создалось' in out, out[-200:])
# ===================== C. пауза после неудачи =====================
e = bare(); notes = flow(e, launches=(False, False)); quiet(e._start_manticore); LOG.clear(); CLOCK.now += 10
r, out = quiet(e._start_manticore)
check('повторный запуск сразу после неудачи (через 10 с): пропускается — без попыток запуска, снятия процесса и второго окна', r is False and not names() and len(notes) == 1 and 'повторно не пробуем' in out, str(LOG))
CLOCK.now += 60; seq = [False, False]; e._try_launch_searchd = lambda: (LOG.append(('launch',)), seq.pop(0))[1]; r, _ = quiet(e._start_manticore)
check('через 60 секунд после неудачи пробует снова (и сообщает снова, если опять не вышло)', r is False and names().count('launch') == 2 and len(notes) == 2, str(LOG))
e = bare(); notes = flow(e, launches=(False, False)); quiet(e._start_manticore); CLOCK.now += 61; e._try_launch_searchd = lambda: True; r, _ = quiet(e._start_manticore)
check('удачный запуск после паузы сбрасывает пометку неудачи', r is True and e._last_start_failure is None)
e = bare(); notes = flow(e, launches=(False, False)); quiet(e._start_manticore); CLOCK.now += 61; seq2 = [False, True]; e._try_launch_searchd = lambda: seq2.pop(0); r, _ = quiet(e._start_manticore)
check('удачное ВОССТАНОВЛЕНИЕ после паузы (первый запуск не вышел, второй после снятия процесса вышел) тоже сбрасывает пометку неудачи', r is True and e._last_start_failure is None, str(e._last_start_failure))
e = bare(); notes = flow(e, exe=False); quiet(e._start_manticore); LOG.clear(); CLOCK.now += 5; quiet(e._start_manticore)
check('нет searchd.exe: повторный вызов в течение минуты второго окна не показывает', len(notes) == 1)
# сценарий запуска программы: движок создаётся (конструктор подключается), затем sp.py вызывает connect(last_db)
class Starting(me.ManticoreEngine):
    searchd_exe = property(lambda self: os.path.join(WORK, 'searchd.exe'), lambda self, value: None)   # настоящий __init__ задал бы путь внутри проекта
    def _prepare_environment(self): pass
    def _is_running(self): return False
    def _try_launch_searchd(self): LOG.append(('launch',)); return False
    def _kill_existing_searchd(self): LOG.append(('kill',))
    def _clear_stale_pid_file(self): pass
LOG.clear(); CLOCK.now = 1000.0; open(os.path.join(WORK, 'searchd.exe'), 'w').close(); notes = []
eng, _ = quiet(Starting, {}, on_startup_failure=lambda t, m: notes.append((t, m)))     # как создаёт config.create_engine
quiet(eng.connect, 'last_db')                                                           # как делает sp.py сразу после создания
check('весь запуск программы при неработающем Manticore (создание движка + connect из sp.py): одно восстановление и ОДНО окно, а не две процедуры и два окна', names().count('launch') == 2 and names().count('kill') == 1 and len(notes) == 1, f'запусков {names().count("launch")}, снятий {names().count("kill")}, окон {len(notes)}')

# ===================== D. конструктор =====================
class Light(me.ManticoreEngine):
    def _prepare_environment(self): LOG.append(('prepare',))
    def connect(self, source=None): LOG.append(('connect', self.host, self.port, self.on_startup_failure is not None)); return True
LOG.clear(); cb = lambda t, m: None
e, _ = quiet(Light, {'host': 'h', 'port': '9999', 'index': 'idx', 'default_separator': 'N5', 'manticore_search_limit': 50}, cb)
check('конструктор: параметры из настроек (порт приводится к числу), колбэк запомнен ДО подключения, окружение готовится раньше подключения', (e.host, e.port, e.index, e.default_separator, e.search_limit) == ('h', 9999, 'idx', 'N5', 50) and e.on_startup_failure is cb and names() == ['prepare', 'connect'] and LOG[1][3] is True, str(LOG))
e, _ = quiet(Light, {}); check('конструктор: значения по умолчанию; колбэка нет — None', (e.host, e.port, e.index, e.default_separator, e.search_limit, e.on_startup_failure, e.engine_type) == ('localhost', 9306, 'documents', 'N1000', 200, None, 'manticore'))
root = os.path.dirname(os.path.dirname(os.path.abspath(me.__file__)))
check('пути запуска из исходников: рядом с проектом (Manticore/bin, Manticore/log, indicies_mc); searchd.exe, конфиг и pid лежат в Manticore/bin', e.project_root == root and e.internal_root == root and e.manticore_bin == os.path.join(root, 'Manticore', 'bin') and e.data_dir == os.path.join(root, 'indicies_mc')
      and e.searchd_exe == os.path.join(root, 'Manticore', 'bin', 'searchd.exe') and e.conf_path == os.path.join(root, 'Manticore', 'bin', 'manticore.conf') and e.pid_file == os.path.join(root, 'Manticore', 'bin', 'searchd.pid'))
real_sys = me.sys; me.sys = ns(frozen=True, executable=os.path.join(WORK, 'prog', 'sineva.exe'), _MEIPASS=os.path.join(WORK, 'prog', '_internal'), platform='win32')
e, _ = quiet(Light, {}); me.sys = real_sys
check('пути в собранной программе: данные и конфиг — рядом с exe, сам searchd.exe — внутри _internal', e.project_root == os.path.join(WORK, 'prog') and e.internal_root == os.path.join(WORK, 'prog', '_internal') and e.searchd_exe == os.path.join(WORK, 'prog', '_internal', 'Manticore', 'bin', 'searchd.exe') and e.conf_path == os.path.join(WORK, 'prog', 'Manticore', 'bin', 'manticore.conf'))
# ===================== E. подготовка окружения =====================
e = bare(host='127.0.0.1', port=9400, conf_dir=os.path.join(WORK, 'env', 'bin'), manticore_log=os.path.join(WORK, 'env', 'log'), data_dir=os.path.join(WORK, 'env', 'data'), conf_path=os.path.join(WORK, 'env', 'bin', 'manticore.conf'))
quiet(e._prepare_environment); text = open(e.conf_path, encoding='utf-8').read()
check('окружение: папки созданы; конфиг записан с адресом и портом из настроек, HTTP-порт 9308, папка данных indicies_mc', all(os.path.isdir(p) for p in (e.conf_dir, e.manticore_log, e.data_dir)) and 'listen = 127.0.0.1:9400:mysql' in text and 'listen = 127.0.0.1:9308:http' in text and 'data_dir = indicies_mc' in text and 'pid_file = Manticore/bin/searchd.pid' in text, text[:200])
open(e.conf_path, 'w', encoding='utf-8').write('мой конфиг'); quiet(e._prepare_environment)
check('существующий конфиг не перезаписывается', open(e.conf_path, encoding='utf-8').read() == 'мой конфиг')
# ===================== F. сервер запущен? =====================
conns = []
class Conn:
    def close(self): conns.append('closed')
real_connect = pymysql.connect
pymysql.connect = lambda **k: (LOG.append(('pymysql.connect', tuple(sorted(k.items())))), Conn())[1]
e = bare(host='h', port=1234); LOG.clear(); r = e._is_running()
check('_is_running: удалось подключиться — True, соединение закрывается; проверка быстрая (таймаут 1 с)', r is True and conns == ['closed'] and dict(LOG[0][1])['connect_timeout'] == 1 and dict(LOG[0][1])['host'] == 'h' and dict(LOG[0][1])['port'] == 1234, str(LOG))
pymysql.connect = lambda **k: (_ for _ in ()).throw(RuntimeError('отказ')); check('_is_running: подключиться нельзя — False', bare()._is_running() is False)
# ===================== G. запуск searchd =====================
def launch(proc, running_after=3, win=False):
    real_p, real_s = me.subprocess, me.sys; me.subprocess = proc; me.sys = ns(platform='win32' if win else 'linux'); LOG.clear(); CLOCK.now = 1000.0
    e = bare(); n = [0]; e._is_running = lambda: (n.__setitem__(0, n[0] + 1), n[0] >= running_after)[1]
    try: r, out = quiet(e._try_launch_searchd)
    finally: me.subprocess, me.sys = real_p, real_s
    return e, r, out
p = FakeProc(); e, r, _ = launch(p, running_after=3)
check('запуск searchd: процесс стартует с конфигом, ждём готовности по 0,5 с до первого успешного ответа; помечается «запущен нами» (чтобы закрыть при выходе)', r is True and e._started_by_us is True and [c for c in LOG if c[0] == 'sleep'] == [('sleep', 0.5)] * 3 and p.calls[0][1][0] == [e.searchd_exe, '--config', e.conf_path], str(LOG))
p = FakeProc(); e, r, out = launch(p, running_after=99)
check('сервер так и не ответил за 10 проверок: False, не помечается «запущен нами»', r is False and e._started_by_us is False and [c for c in LOG if c[0] == 'sleep'] == [('sleep', 0.5)] * 10 and 'таймаут' in out)
p = FakeProc(fail='popen'); e, r, out = launch(p)
check('процесс не стартует (нет файла/прав): False с причиной в консоли, исключения нет', r is False and 'Ошибка запуска Manticore: нет файла' in out)
p = FakeProc(); launch(p, win=True); kw = p.calls[0][2]
check('Windows: окно консоли скрыто (STARTUPINFO + CREATE_NO_WINDOW); вывод процесса отбрасывается', kw['startupinfo'].dwFlags == FakeProc.STARTF_USESHOWWINDOW and kw['startupinfo'].wShowWindow == FakeProc.SW_HIDE and kw['creationflags'] == FakeProc.CREATE_NO_WINDOW and kw['stdout'] == FakeProc.DEVNULL and kw['stderr'] == FakeProc.DEVNULL)
p = FakeProc(); launch(p, win=False); kw = p.calls[0][2]
check('не Windows: без особых флагов', kw['startupinfo'] is None and kw['creationflags'] == 0)
# ===================== H. восстановление =====================
def kill(win, fail=None):
    real_p, real_s = me.subprocess, me.sys; p = FakeProc(fail=fail); me.subprocess = p; me.sys = ns(platform='win32' if win else 'linux')
    try: _, out = quiet(bare()._kill_existing_searchd)
    finally: me.subprocess, me.sys = real_p, real_s
    return p, out
p, _ = kill(False); check('снятие процесса: не Windows — ничего не делает', not p.calls)
p, _ = kill(True); check('снятие процесса: Windows — taskkill /F /IM searchd.exe без окна консоли', p.calls[0][1][0] == ['taskkill', '/F', '/IM', 'searchd.exe'] and p.calls[0][2]['creationflags'] == FakeProc.CREATE_NO_WINDOW)
p, out = kill(True, fail='run'); check('снятие процесса: сбой не выходит наружу, причина в консоли', 'Не удалось принудительно завершить searchd.exe: нет прав' in out)
e = bare(); open(e.pid_file, 'w').write('123'); quiet(e._clear_stale_pid_file); check('устаревший searchd.pid удаляется; если файла нет — ничего не происходит', not os.path.exists(e.pid_file) and quiet(e._clear_stale_pid_file)[0] is None)
real_remove = me.os.remove; open(e.pid_file, 'w').write('1'); me.os.remove = lambda p: (_ for _ in ()).throw(PermissionError('занят'))
_, out = quiet(e._clear_stale_pid_file); me.os.remove = real_remove
check('не удалось удалить pid-файл: исключения нет, причина в консоли', 'Не удалось удалить' in out and 'занят' in out); os.path.exists(e.pid_file) and os.remove(e.pid_file)
# ===================== I. подключение =====================
class Cur:
    def __init__(self, fail=False): self.fail = fail; self.q = []
    def execute(self, q): self.q.append(q); 
    def fetchone(self):
        if self.fail: raise RuntimeError('соединение потеряно')
        return (1,)
    def close(self): LOG.append(('cursor.close',))
class Connection:
    def __init__(self): self.cur = Cur()
    def cursor(self): return self.cur
    def close(self): LOG.append(('conn.close',))
made = []
pymysql.connect = lambda **k: (made.append(k), Connection())[1]
e = bare(); e._is_running = lambda: True; e._start_manticore = lambda: (_ for _ in ()).throw(AssertionError('запуск не нужен'))
check('connect: сервер работает — подключение с параметрами (без пароля, utf8mb4, автофиксация), индекс по умолчанию текущий', e.connect() is True and made[-1] == dict(host='localhost', port=9306, user='', password='', charset='utf8mb4', autocommit=True) and e._current_index == 'documents' and e.conn is not None)
e = bare(); e._is_running = lambda: True; e.connect('книга'); check('connect(source): индекс становится выбранным и текущим', e.index == 'книга' and e._current_index == 'книга')
e.connect(); check('connect повторно при живом соединении: проверка «SELECT 1», новое соединение не создаётся', len(made) == 2 and e.conn.cur.q == ['SELECT 1'])
e.connect('другой'); check('connect(source) при живом соединении меняет индекс', e.index == 'другой')
e.conn.cur.fail = True; n_before = len(made); e._is_running = lambda: True; r = e.connect()
check('соединение потеряно: переподключение (новое соединение)', r is True and len(made) == n_before + 1)
e = bare(); e._is_running = lambda: False; e._start_manticore = lambda: False; n_before = len(made); r = e.connect()
check('сервер не работает и не запустился: connect возвращает False, соединение не создаётся', r is False and len(made) == n_before and e.conn is None)
e = bare(); e._is_running = lambda: False; e._start_manticore = lambda: True; r = e.connect(); check('сервер не работал, но запустился: подключение выполняется', r is True and e.conn is not None)
e = bare(); e._is_running = lambda: True; pymysql.connect = lambda **k: (_ for _ in ()).throw(RuntimeError('отказ в подключении')); r, out = quiet(e.connect)
check('ошибка подключения: False с причиной в консоли', r is False and 'Ошибка подключения к Manticore: отказ в подключении' in out)
# ===================== J. закрытие =====================
real_p, real_s = me.subprocess, me.sys; p = FakeProc(); me.subprocess = p; me.sys = ns(platform='linux')
e = bare(_started_by_us=True); e.conn = Connection(); e.cursor = e.conn.cur; e._current_index = 'x'; LOG.clear(); quiet(e.close)
check('close: курсор и соединение закрыты; если сервер запустили мы — он останавливается (--stopwait); текущий индекс сброшен', LOG == [('cursor.close',), ('conn.close',)] and e.cursor is None and e.conn is None and p.calls[0][1][0] == [e.searchd_exe, '--config', e.conf_path, '--stopwait'] and e._current_index is None, str(LOG))
p.calls.clear(); e = bare(_started_by_us=False); quiet(e.close); check('close: сервер запустили не мы — не останавливается', not p.calls)
me.subprocess = FakeProc(fail='run'); e = bare(_started_by_us=True); _, out = quiet(e.close); check('close: сбой остановки не выходит наружу, причина в консоли', 'Ошибка при остановке Manticore: нет прав' in out)
me.subprocess, me.sys = real_p, real_s
# ===================== K. фабрика и окна =====================
class FakeManticore:
    def __init__(self, params, on_startup_failure=None): self.params = params; self.cb = on_startup_failure; self.engine_type = 'manticore'
real_cls = me.ManticoreEngine; me.ManticoreEngine = FakeManticore; handler = lambda t, m: None
eng = cfg_module.create_engine('manticore', {'manticore_host': 'h', 'manticore_port': 1, 'manticore_index': 'i', 'default_separator': 'N7', 'manticore_search_limit': 9}, on_startup_failure=handler)
check('create_engine: колбэк передаётся в Manticore, параметры собираются из настроек', eng.cb is handler and eng.params == {'host': 'h', 'port': 1, 'index': 'i', 'default_separator': 'N7', 'manticore_search_limit': 9}, str(eng.params))
check('create_engine: колбэк необязателен (по умолчанию None)', cfg_module.create_engine('manticore', {}).cb is None)
me.ManticoreEngine = real_cls
try: cfg_module.create_engine('нет_такого', {}); raised = False
except ValueError as e_: raised = 'Unknown engine type' in str(e_)
check('create_engine: неизвестный тип — ValueError', raised)
def py_files(rel): return [os.path.join(env.ROOT, rel, f) for f in sorted(os.listdir(os.path.join(env.ROOT, rel))) if f.endswith('.py')]
bad = []
for path in py_files('engines'):
    for node in ast.walk(ast.parse(open(path, encoding='utf-8').read())):
        if isinstance(node, ast.Import) and any(a.name.split('.')[0] == 'tkinter' for a in node.names): bad.append(os.path.basename(path))
        if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 'tkinter': bad.append(os.path.basename(path))
check('движки не импортируют tkinter: окна — забота интерфейса (раньше Manticore создавал скрытое окно сам)', not bad, str(bad))
missing = []
for rel in ('sp.py', os.path.join('ui', 'main_window.py')):
    for node in ast.walk(ast.parse(open(os.path.join(env.ROOT, rel), encoding='utf-8').read())):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'create_engine' and 'on_startup_failure' not in [k.arg for k in node.keywords]: missing.append(f'{rel}:{node.lineno}')
check('каждое создание движка в программе (запуск и смена движка) передаёт обработчик окна: иначе сообщение о неудаче не дошло бы до пользователя', not missing, str(missing))
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
