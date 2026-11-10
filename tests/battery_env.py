import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import env  # путь к проекту, подставной tkinter и заглушки — ДО импорта проекта
import importlib.util, shutil, subprocess, types, webbrowser

results = []
def check(name, cond, detail=''):
    results.append(bool(cond)); print(('OK   ' if cond else 'FAIL ') + name + (f'  -> {detail}' if (detail and not cond) else ''))

from tests.sources import project_sources

# ===== что считается исходниками проекта =====
root = env.tmpdir('proj_')
def touch(rel, data=b'x = 1\n'):
    path = os.path.join(root, *rel.split('/')); os.makedirs(os.path.dirname(path), exist_ok=True); open(path, 'wb').write(data)
for rel in ('m.py', 'notes.txt', 'engines/__init__.py', 'engines/a.py', 'ui/__init__.py', 'ui/sub/__init__.py', 'ui/sub/b.py', 'ui/__pycache__/c.py',
            'tests/__init__.py', 'tests/t.py', 'scripts/tool.py', 'build/x.py', 'DB/d.py', '.venv/pyvenv.cfg', '.venv/Lib/site-packages/pkg/__init__.py', 'Manticore/e.py'):
    touch(rel)
touch('.venv/Lib/site-packages/pkg/bad.py', b'# \xa4\xa5 not utf-8\n')
found = project_sources(root)
check('исходники проекта: корень и пакеты верхнего уровня (папки с __init__.py), вложенные пакеты тоже',
      set(found) == {'m.py', 'engines/__init__.py', 'engines/a.py', 'ui/__init__.py', 'ui/sub/__init__.py', 'ui/sub/b.py'}, str(sorted(found)))
check('виртуальное окружение .venv (с файлом не в UTF-8), DB, Manticore, build, кэш и папки без __init__.py не считаются',
      not any(x.startswith(('.venv', 'DB', 'Manticore', 'build', 'scripts')) or '__pycache__' in x for x in found))
check('папка tests в исходники проекта не входит', not any(x.startswith('tests') for x in found))

# ===== предохранитель: код проверок не может запускать программы =====
def blocked(call):
    try: call(); return False
    except RuntimeError as e: return 'внешнюю программу' in str(e)
check('subprocess.run из проверки заблокирован', blocked(lambda: subprocess.run([sys.executable, '-c', 'pass'])))
check('subprocess.Popen из проверки заблокирован', blocked(lambda: subprocess.Popen([sys.executable, '-c', 'pass'])))
check('os.system из проверки заблокирован', blocked(lambda: os.system('echo x')))
check('webbrowser.open из проверки заблокирован', blocked(lambda: webbrowser.open('http://example.com')))
fake_os = types.SimpleNamespace(calls=[], startfile=lambda path: fake_os.calls.append(path))
env._guard_function(fake_os, 'startfile', 'os.startfile')
check('os.startfile (его нет на Linux — проверяется на подставном объекте) заблокирован и НЕ вызван', blocked(lambda: fake_os.startfile('x.txt')) and fake_os.calls == [])

# проверка, которой запуск нужен, подменяет его сама — как делают батареи
recorded = []; real_system = os.system
os.system = lambda cmd: recorded.append(cmd) or 0
try: os.system('echo ok'); patched_ok = recorded == ['echo ok']
finally: os.system = real_system
check('блокировки записываются в env.BLOCKED (иначе проглоченный кодом проекта запуск остался бы незамеченным)', len(env.BLOCKED) >= 4, str(env.BLOCKED))
check('явная подмена в самой проверке работает (так батареи и проверяют запуск файлов)', patched_ok)

# ===== предохранитель не должен ломать сторонние библиотеки =====
outside = env.tmpdir('thirdparty_'); module_path = os.path.join(outside, 'thirdparty_like.py')
open(module_path, 'w').write("import subprocess, sys\ndef run_child():\n    return subprocess.run([sys.executable, '-c', 'print(42)'], capture_output=True, text=True)\n")
assert not os.path.abspath(module_path).startswith(env.ROOT + os.sep)
spec = importlib.util.spec_from_file_location('thirdparty_like', module_path); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
done = mod.run_child()
check('код ВНЕ проекта (как сторонняя библиотека) по-прежнему может запускать процессы', done.returncode == 0 and done.stdout.strip() == '42', str(done))
class FromPopen(subprocess.Popen): pass
check('subprocess.Popen остался классом: от него можно наследоваться (так делает asyncio на Windows)', isinstance(subprocess.Popen, type) and issubclass(FromPopen, subprocess.Popen))
env.BLOCKED.clear()  # блокировки выше — предмет проверки, а не ошибка
print(f"\nПроверок: {len(results)}, провалено: {results.count(False)}")
sys.exit(0 if all(results) else 1)
